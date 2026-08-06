"""
短剧生成工作流 — Web 服务入口。

Usage:
    uv run uvicorn server:app --reload --port 8000

API:
    配置:
        GET  /api/config/status          — 检查各 API Key 配置状态
        POST /api/config/test-key        — 测试 API Key 有效性
        POST /api/config/save-key        — 保存 API Key 到 .env

    项目管理:
        GET    /api/projects             — 项目列表
        POST   /api/projects             — 创建项目
        GET    /api/projects/{id}        — 项目详情
        DELETE /api/projects/{id}        — 删除项目
        POST   /api/projects/{id}/upload — 上传剧本

    分步执行:
        POST /api/projects/{id}/steps/{step}/run    — 执行步骤
        POST /api/projects/{id}/steps/{step}/redo   — 重新执行
        GET  /api/projects/{id}/steps/{step}/result — 步骤结果

    成本:
        GET /api/projects/{id}/estimate  — 估算视频生成成本

    文件:
        GET /api/projects/{id}/files/{path:path} — 提供项目输出文件
"""

import asyncio
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from src.workflow import VideoWorkflow, PREVIEW_STEPS, STEP_ORDER
from src.state import WorkflowState, state_to_dict, create_initial_state
from src.project_manager import get_project_manager
from src.logger import get_logger, setup_logging

setup_logging("INFO")
logger = get_logger("server")

app = FastAPI(title="短剧生成工作流", version="0.2.0")

pm = get_project_manager()

# 全局 workflow 实例
_workflow: Optional[VideoWorkflow] = None
_running_steps: dict = {}  # project_id -> set of running step names


def get_workflow() -> VideoWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = VideoWorkflow()
    return _workflow


# ═══════════════════════════════════════════════════════════════════
# 配置 API
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/config/status")
async def config_status():
    """检查各 API Key 的配置状态。"""
    return {
        "deepseek": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "openai": bool(os.environ.get("OPENAI_API_KEY")),
        "kling": bool(os.environ.get("KLING_API_KEY")),
        "jimeng": bool(os.environ.get("VOLCENGINE_AK") and os.environ.get("VOLCENGINE_SK")),
    }


@app.post("/api/config/test-key")
async def test_key(req: Request):
    """测试某个 API Key 是否有效。"""
    body = await req.json()
    provider = body.get("provider", "")
    key = body.get("key", "")

    if not provider or not key:
        raise HTTPException(400, "请提供 provider 和 key")

    ok = False
    msg = ""

    try:
        if provider == "deepseek":
            import httpx
            async with httpx.AsyncClient(timeout=15) as cli:
                resp = await cli.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
                )
                ok = resp.status_code == 200
                msg = "连接成功" if ok else f"HTTP {resp.status_code}: {resp.text[:200]}"

        elif provider == "openai":
            import httpx
            async with httpx.AsyncClient(timeout=15) as cli:
                resp = await cli.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 5},
                )
                ok = resp.status_code == 200
                msg = "连接成功" if ok else f"HTTP {resp.status_code}: {resp.text[:200]}"

        elif provider == "kling":
            import httpx
            async with httpx.AsyncClient(timeout=15) as cli:
                resp = await cli.post(
                    "https://api.klingai.com/v1/videos/text2video",
                    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                    json={"model_name": "kling-v1", "prompt": "test", "duration": "5"},
                )
                data = resp.json()
                # Kling 返回 code=0 表示认证通过（即使 prompt 是 test 也没关系）
                ok = data.get("code") in (0, 1000, 1100)
                msg = "连接成功" if ok else f"API 错误: {data.get('message', resp.text[:200])}"

        elif provider == "jimeng":
            # 即梦需要 AK + SK，这里只做简单验证
            ok = len(key) > 10
            msg = "格式有效" if ok else "Key 太短"

        else:
            msg = f"未知服务商: {provider}"

    except Exception as e:
        msg = f"测试失败: {e}"

    return {"ok": ok, "message": msg}


@app.post("/api/config/save-key")
async def save_key(req: Request):
    """保存 API Key 到 .env 文件。"""
    body = await req.json()
    provider = body.get("provider", "")
    key = body.get("key", "")

    if not provider or not key:
        raise HTTPException(400, "请提供 provider 和 key")

    env_map = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "kling": "KLING_API_KEY",
    }

    env_var = env_map.get(provider)
    if not env_var:
        raise HTTPException(400, f"未知服务商: {provider}")

    # 写入 .env 文件
    env_path = Path(".env")
    lines = []
    found = False
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    new_lines = []
    for line in lines:
        if line.startswith(f"{env_var}=") or line.startswith(f"# {env_var}"):
            new_lines.append(f"{env_var}={key}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{env_var}={key}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 立即设置环境变量
    os.environ[env_var] = key

    logger.info("API Key 已保存: %s", provider)
    return {"ok": True, "message": f"{provider} Key 已保存"}


# ═══════════════════════════════════════════════════════════════════
# 项目管理 API
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/projects")
async def list_projects():
    return pm.list_projects()


@app.post("/api/projects")
async def create_project(req: Request):
    body = await req.json()
    name = body.get("name", "")
    episode_id = body.get("episode_id", "01")
    episode_title = body.get("episode_title", "")
    return pm.create_project(name=name, episode_id=episode_id, episode_title=episode_title)


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    return p


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    ok = pm.delete_project(project_id)
    if not ok:
        raise HTTPException(404, "项目不存在")
    return {"ok": True}


@app.post("/api/projects/{project_id}/upload")
async def upload_script(project_id: str, file: UploadFile = File(...)):
    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    if not file.filename or not file.filename.endswith(".docx"):
        raise HTTPException(400, "请上传 .docx 格式的剧本文件")

    content = await file.read()
    saved_path = pm.save_upload(project_id, content, file.filename)
    return {"ok": True, "path": saved_path, "filename": file.filename}


# ═══════════════════════════════════════════════════════════════════
# 分步执行 API
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/projects/{project_id}/steps/{step_name}/run")
async def run_step(project_id: str, step_name: str):
    """执行单个工作流步骤。

    预览步骤（解析/资产/分镜/一致性/提示词）通常很快，同步执行并返回结果。
    生成步骤（generate_videos / merge_videos）可能耗时数分钟，改为后台任务：
    立即返回 202，前端通过轮询 GET /api/projects/{id} 观察步骤状态。
    """
    if step_name not in STEP_ORDER:
        raise HTTPException(400, f"未知步骤: {step_name}")

    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    # 检查是否已在运行
    running = _running_steps.get(project_id, set())
    if step_name in running:
        raise HTTPException(409, f"步骤 {step_name} 已在执行中")

    # 检查此步骤是否可以执行（前面步骤必须完成，generate_videos 和 merge_videos 除外）
    idx = STEP_ORDER.index(step_name)
    for i in range(idx):
        prev = STEP_ORDER[i]
        # 视频生成步骤不受前面步骤限制（允许单独重试）
        if step_name in ("generate_videos", "merge_videos"):
            break
        st = pm.get_step_status(project_id, prev)
        if st and st["status"] != "completed":
            raise HTTPException(400, f"请先完成「{prev}」步骤")

    # 标记运行状态并设为 running（同步/异步都先置位，前端立即能看到）
    running.add(step_name)
    _running_steps[project_id] = running
    pm.set_step_status(project_id, step_name, "running")
    pm.update_project(project_id, status="generating" if step_name in ("generate_videos", "merge_videos") else "editing")

    # 生成步骤：后台执行，立即返回，前端轮询
    if step_name in ("generate_videos", "merge_videos"):
        asyncio.create_task(_execute_step(project_id, step_name, p, background=True))
        return JSONResponse(status_code=202, content={
            "ok": True, "step": step_name, "status": "running", "async": True,
        })

    # 预览步骤：同步执行
    return await _execute_step(project_id, step_name, p)


async def _execute_step(project_id: str, step_name: str, p: dict, background: bool = False):
    """实际执行一个步骤：加载状态 → 运行节点 → 持久化 → 更新状态位。

    同步路径返回结果作为响应；后台路径 background=True，异常只落库为 failed，
    不抛出 HTTPException（避免未捕获的后台任务异常）。
    """
    # 加载或创建状态
    state = pm.load_state(project_id)
    if state is None:
        input_file = p.get("input_file", "")
        # 用 project_id 作为 episode_id，确保输出目录和文件服务对齐
        state = create_initial_state(project_id, p.get("episode_title", ""), input_file)
        state["episode_id"] = project_id

    # 确保关键字段正确
    if not state.get("input_file_path"):
        state["input_file_path"] = p.get("input_file", "")
    state["episode_id"] = project_id  # 保持输出目录与项目 ID 一致

    try:
        wf = get_workflow()
        state = await wf.run_step(step_name, state)
        pm.save_state(project_id, state)

        has_errors = bool(state.get("errors"))
        error_msg = "; ".join(state.get("errors", [])) if has_errors else ""

        if has_errors:
            pm.set_step_status(project_id, step_name, "failed", error=error_msg)
        else:
            pm.set_step_status(project_id, step_name, "completed")

        pm.update_project(project_id, status="editing")

        return {
            "ok": not has_errors,
            "step": step_name,
            "status": "failed" if has_errors else "completed",
            "errors": state.get("errors", []),
        }

    except Exception as e:
        logger.error("步骤 %s 执行失败: %s", step_name, e)
        pm.set_step_status(project_id, step_name, "failed", error=str(e))
        pm.update_project(project_id, status="editing")
        if background:
            return {"ok": False, "step": step_name, "status": "failed", "errors": [str(e)]}
        raise HTTPException(500, f"步骤执行失败: {e}")

    finally:
        running = _running_steps.get(project_id)
        if running is not None:
            running.discard(step_name)
            if not running:
                _running_steps.pop(project_id, None)


@app.post("/api/projects/{project_id}/steps/{step_name}/redo")
async def redo_step(project_id: str, step_name: str):
    """重新执行某步骤（清除该步骤及后续步骤结果）。"""
    if step_name not in STEP_ORDER:
        raise HTTPException(400, f"未知步骤: {step_name}")

    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    # 清除此步骤及后续步骤
    pm.reset_steps_from(project_id, step_name)

    # 加载现有状态，清除相关字段
    state = pm.load_state(project_id)
    if state:
        state = clear_state_from_step(state, step_name)
        pm.save_state(project_id, state)

    logger.info("步骤已重置: %s/%s", project_id, step_name)
    return {"ok": True, "message": f"步骤 {step_name} 已重置，可以重新执行"}


@app.get("/api/projects/{project_id}/steps/{step_name}/result")
async def get_step_result(project_id: str, step_name: str):
    """获取步骤结果数据。"""
    if step_name not in STEP_ORDER:
        raise HTTPException(400, f"未知步骤: {step_name}")

    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    result = pm.get_step_result(project_id, step_name)
    return result


@app.get("/api/projects/{project_id}/steps/{step_name}/editable")
async def get_editable_result(project_id: str, step_name: str):
    """获取步骤的完整可编辑数据（含原始字段、编辑元信息）。"""
    if step_name not in STEP_ORDER:
        raise HTTPException(400, f"未知步骤: {step_name}")

    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    return pm.get_editable_result(project_id, step_name)


@app.put("/api/projects/{project_id}/state/field")
async def update_state_field(project_id: str, req: Request):
    """更新项目状态中的某个字段并持久化。

    Body: { "path": "optimized_prompts.0.shots.2.prompt", "value": "new text" }
    """
    body = await req.json()
    field_path = body.get("path", "")
    value = body.get("value")
    reset_downstream = body.get("reset", True)

    if not field_path:
        raise HTTPException(400, "请提供 field path")

    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    try:
        result = pm.update_state_field(project_id, field_path, value, reset_downstream=reset_downstream)
        return result
    except Exception as e:
        raise HTTPException(500, f"字段更新失败: {e}")


@app.post("/api/projects/{project_id}/duplicate")
async def duplicate_project(project_id: str, req: Request):
    """复制项目（含所有状态和步骤）。"""
    body = await req.json()
    new_name = body.get("name", "")

    new_id = pm.duplicate_project(project_id, new_name)
    if not new_id:
        raise HTTPException(404, "原项目不存在")

    return {"ok": True, "new_id": new_id}


def clear_state_from_step(state: WorkflowState, step_name: str) -> WorkflowState:
    """清除指定步骤及之后步骤产生的状态字段。"""
    idx = STEP_ORDER.index(step_name) if step_name in STEP_ORDER else 0
    steps_to_clear = STEP_ORDER[idx:]

    clear_map = {
        "parse_docx": ["script_content", "structured_script", "parsed_characters", "parsed_scenes", "parsed_props"],
        "generate_asset_package": ["assets_generated", "character_assets", "scene_assets", "prop_assets",
                                     "asset_prompts", "asset_table_path", "images_generated"],
        "step1_storyboard": ["step1_completed", "scene_table", "camera_positions", "opening_state",
                              "shot_groups", "step1_output_path", "step1_optimized_path"],
        "step2_consistency": ["step2_completed", "consistency_anchors", "step2_output_path"],
        "step3_optimize_prompts": ["step3_completed", "optimized_prompts", "step3_output_path"],
        "generate_videos": ["videos_generated", "video_segments", "video_output_dir"],
        "merge_videos": ["videos_merged", "final_video_path"],
    }

    for sn in steps_to_clear:
        for field in clear_map.get(sn, []):
            if field in state:
                if isinstance(state[field], bool):
                    state[field] = False
                elif isinstance(state[field], list):
                    state[field] = []
                elif isinstance(state[field], dict):
                    state[field] = {}
                else:
                    state[field] = None

    state["errors"] = []
    state["current_node"] = "editing"
    state["updated_at"] = datetime.now().isoformat()
    return state


# ═══════════════════════════════════════════════════════════════════
# 手动上传（图片/视频 API 不可用时的降级方案）
# ═══════════════════════════════════════════════════════════════════

@app.post("/api/projects/{project_id}/assets/upload-image")
async def upload_asset_image(project_id: str, category: str = Form(...), index: int = Form(...),
                              file: UploadFile = File(...)):
    """手动上传资产图片，更新到对应的 asset 记录中。

    category: character_assets / scene_assets / prop_assets
    index: 该类别下的索引
    """
    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    state = pm.load_state(project_id)
    if state is None:
        raise HTTPException(404, "项目状态不存在")

    assets = state.get(category, [])
    if index < 0 or index >= len(assets):
        raise HTTPException(400, f"索引 {index} 超出范围 (共 {len(assets)} 个)")

    content = await file.read()
    output_dir = Path("./outputs") / project_id / "资产"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 保存文件
    ext = os.path.splitext(file.filename)[1] or ".png"
    filename = f"{category}_{index}{ext}"
    filepath = output_dir / filename
    with open(filepath, "wb") as f:
        f.write(content)

    # 更新状态
    assets[index]["image_path"] = str(filepath)
    assets[index]["image_generated"] = True
    assets[index]["image_status"] = "manual_upload"
    pm.save_state(project_id, state)
    pm.update_project(project_id, updated_at=datetime.now().isoformat())

    logger.info("手动上传资产图片: %s/%s[%d] -> %s", project_id, category, index, filepath)
    return {"ok": True, "path": str(filepath)}


@app.post("/api/projects/{project_id}/videos/upload-segment")
async def upload_video_segment(project_id: str, segment_id: str = Form(...),
                                file: UploadFile = File(...)):
    """手动上传视频片段，更新到对应的 video_segment 记录中。"""
    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")

    state = pm.load_state(project_id)
    if state is None:
        raise HTTPException(404, "项目状态不存在")

    segments = state.get("video_segments", [])
    target = None
    for seg in segments:
        if seg.get("segment_id") == segment_id:
            target = seg
            break

    if target is None:
        raise HTTPException(400, f"未找到 segment_id={segment_id}")

    content = await file.read()
    videos_dir = Path("./outputs") / project_id / "视频"
    videos_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{segment_id}.mp4"
    filepath = videos_dir / filename
    with open(filepath, "wb") as f:
        f.write(content)

    target["video_path"] = str(filepath)
    target["status"] = "completed"
    pm.save_state(project_id, state)
    pm.update_project(project_id, updated_at=datetime.now().isoformat())

    logger.info("手动上传视频片段: %s/%s -> %s", project_id, segment_id, filepath)
    return {"ok": True, "path": str(filepath)}


# ═══════════════════════════════════════════════════════════════════
# 成本估算
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/projects/{project_id}/estimate")
async def estimate_cost(project_id: str):
    p = pm.get_project(project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    return pm.estimate_cost(project_id)


# ═══════════════════════════════════════════════════════════════════
# 文件服务
# ═══════════════════════════════════════════════════════════════════

@app.get("/api/projects/{project_id}/files/{file_path:path}")
async def serve_project_file(project_id: str, file_path: str):
    """提供项目输出目录中的文件（图片、视频等）。"""
    output_dir = Path("./outputs") / project_id
    full_path = output_dir / file_path

    if not full_path.exists():
        raise HTTPException(404, "文件不存在")

    return FileResponse(str(full_path))


@app.get("/api/health")
async def health():
    return {"status": "ok"}


# ═══════════════════════════════════════════════════════════════════
# 静态文件
# ═══════════════════════════════════════════════════════════════════

web_dir = Path(__file__).parent / "web"
if web_dir.exists():
    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str = ""):
        """SPA 回退：非 API 路径返回 index.html，静态文件直接返回。"""
        if full_path.startswith("api/"):
            raise HTTPException(404)
        file_path = (web_dir / full_path).resolve()
        # 安全检查：确保文件在 web_dir 下
        try:
            file_path.relative_to(web_dir.resolve())
        except ValueError:
            raise HTTPException(404)
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(web_dir / "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
