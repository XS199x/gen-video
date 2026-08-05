import os
import json
import asyncio
import subprocess
from typing import Dict, Any, List
from datetime import datetime

import httpx

from ..state import WorkflowState, VideoSegment
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..logger import get_logger

logger = get_logger("nodes.generate_videos")

KLING_CREATE_URL = "https://api.klingai.com/v1/videos/text2video"
KLING_STATUS_URL = "https://api.klingai.com/v1/videos/text2video/{task_id}"
POLL_INTERVAL = 3
POLL_MAX_WAIT = 600


async def generate_videos_node(
    state: WorkflowState, config_manager: ConfigManager,
    model_manager: ModelManager, prompt_manager: PromptManager,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "generate_videos"
    new_state.setdefault("errors", [])

    log_entry = {"node": "generate_videos", "start_time": datetime.now().isoformat(), "status": "running"}
    new_state["execution_log"].append(log_entry)

    try:
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))
        videos_dir = os.path.join(output_dir, "视频")
        os.makedirs(videos_dir, exist_ok=True)

        prompts = state.get("optimized_prompts", [])
        if not prompts:
            pp = os.path.join(output_dir, "视频提示词.json")
            if os.path.exists(pp):
                with open(pp, "r", encoding="utf-8") as f:
                    prompts = json.load(f)
                logger.info("从文件加载提示词: %s", pp)

        if not prompts:
            raise RuntimeError("没有可用的提示词，请先完成 step3_optimize_prompts")

        segments = _build_segments(prompts)
        video_config = config_manager.get_node_config("generate_videos")
        provider = video_config.get("video_provider", "kling")

        logger.info("视频生成: %d 个片段, 服务商=%s, 模型=%s",
                     len(segments), provider, video_config.get("video_model", "kling-v1"))

        try:
            if provider == "kling":
                segments = await _generate_via_kling(segments, videos_dir, video_config)
            elif provider == "runway":
                segments = await _generate_via_runway(segments, videos_dir, video_config)
            elif provider == "mock":
                segments = await _generate_mock_videos(segments, videos_dir)
            else:
                raise RuntimeError(f"未知的视频服务商: '{provider}'，支持: kling, runway, mock")
        except Exception as e:
            logger.warning("视频 API 不可用，输出提示词占位: %s", e)
            _make_placeholder_segments(segments, videos_dir, str(e))

        new_state.update({"videos_generated": True, "video_segments": segments, "video_output_dir": videos_dir})

        mpath = os.path.join(output_dir, "视频片段清单.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)

        ok = sum(1 for s in segments if s.get("status") == "completed")
        fail = sum(1 for s in segments if s.get("status") == "failed")
        log_entry.update({"status": "completed", "end_time": datetime.now().isoformat(),
                          "output": videos_dir, "total": len(segments), "ok": ok, "fail": fail})
        logger.info("视频生成完成: %d/%d 成功, %d 失败", ok, len(segments), fail)

    except Exception as e:
        logger.error("视频生成失败: %s", e, exc_info=True)
        new_state["errors"].append(f"generate_videos 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


def _build_segments(prompts: list) -> List[VideoSegment]:
    segments = []
    for gi, group in enumerate(prompts):
        for si, shot in enumerate(group.get("shots", [])):
            prompt = shot.get("prompt") or shot.get("description") or shot.get("dialogue") or f"镜头 {si}"
            segments.append(VideoSegment(
                segment_id=f"seg_{gi}_{si}",
                shot_id=f"{group.get('group_name', f'group_{gi}')}_{shot.get('shot_name', si)}",
                prompt=str(prompt), video_path=None, status="pending", duration=5.0,
            ))
    return segments


def _make_placeholder_segments(segments, videos_dir, error_msg):
    """视频 API 不可用时，输出提示词占位文件，标记为待上传。"""
    for seg in segments:
        prompt = seg.get("prompt", "")
        # 保存提示词到文本文件，方便用户复制
        txt_path = os.path.join(videos_dir, f"{seg['segment_id']}.prompt.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"镜头: {seg.get('shot_id', '')}\n")
            f.write(f"提示词:\n{prompt}\n\n")
            f.write("可复制此提示词到其他视频生成平台，然后将生成的视频拖入本页面。\n")
        seg["prompt_file"] = txt_path
        seg["status"] = "pending_upload"
        seg["_api_error"] = error_msg[:200]
        seg["video_path"] = None
    logger.info("已生成 %d 个占位提示词，等待用户手动上传视频", len(segments))


# ─── Kling ───────────────────────────────────────────────────────

async def _generate_via_kling(segments, videos_dir, config):
    api_key = config.get("video_api_key") or config.get("api_key") or os.environ.get("KLING_API_KEY")
    if not api_key:
        raise RuntimeError("未找到 Kling API Key。请在 .env 中设置 KLING_API_KEY")

    model = config.get("video_model", "kling-v1")
    duration = str(config.get("video_duration", 5))
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60) as client:
        logger.info("提交 %d 个任务到 Kling (模型=%s)...", len(segments), model)
        for seg in segments:
            try:
                resp = await client.post(KLING_CREATE_URL, json={
                    "model_name": model, "prompt": seg.get("prompt", ""), "duration": duration,
                }, headers=headers)
                data = resp.json()
                if data.get("code") == 0:
                    seg["task_id"] = data["data"]["task_id"]
                    seg["status"] = "processing"
                    logger.info("  [%s] 已提交, task_id=%s", seg["segment_id"], seg["task_id"])
                else:
                    seg["status"] = "failed"
                    seg["error"] = f"Kling API 错误: code={data.get('code')}, msg={data.get('message')}"
                    logger.error("  [%s] 提交失败: %s", seg["segment_id"], seg["error"])
            except Exception as e:
                seg["status"] = "failed"
                seg["error"] = f"提交异常: {e}"
                logger.error("  [%s] %s", seg["segment_id"], e)

        pending = [s for s in segments if s.get("status") == "processing"]
        if pending:
            logger.info("轮询 %d 个 Kling 任务 (间隔=%ds, 最长等待=%ds)...", len(pending), POLL_INTERVAL, POLL_MAX_WAIT)
            await _poll_kling(pending, client, headers)

        ready = [s for s in segments if s.get("status") == "completed"]
        if ready:
            logger.info("下载 %d 个已完成的视频...", len(ready))
            await _download_kling(ready, videos_dir, client)

    return segments


async def _poll_kling(segments, client, headers):
    start = asyncio.get_event_loop().time()
    pending = {s["task_id"]: s for s in segments}
    while pending:
        elapsed = asyncio.get_event_loop().time() - start
        if elapsed > POLL_MAX_WAIT:
            logger.warning("轮询超时 (%.0fs)，%d 个任务未完成", elapsed, len(pending))
            for s in pending.values():
                s["status"] = "failed"
                s["error"] = f"轮询超时 ({POLL_MAX_WAIT}s)"
            break

        for tid, seg in list(pending.items()):
            try:
                resp = await client.get(KLING_STATUS_URL.format(task_id=tid), headers=headers)
                data = resp.json()
                if data.get("code") != 0:
                    seg["status"] = "failed"
                    seg["error"] = f"查询失败: {data.get('message')}"
                    del pending[tid]
                    continue
                st = data["data"]["task_status"]
                if st == "succeed":
                    videos = data["data"].get("task_result", {}).get("videos", [])
                    if videos:
                        seg["video_url"] = videos[0].get("url")
                        seg["status"] = "completed"
                        seg["duration"] = float(videos[0].get("duration", 5))
                        del pending[tid]
                        logger.info("  [%s] ✓ 完成 (%ss)", seg["segment_id"], seg.get("duration"))
                    else:
                        seg["status"] = "failed"
                        seg["error"] = "任务成功但无视频链接"
                        del pending[tid]
                elif st == "failed":
                    seg["status"] = "failed"
                    seg["error"] = "Kling 生成失败"
                    del pending[tid]
                    logger.warning("  [%s] ✗ 生成失败", seg["segment_id"])
            except Exception as e:
                seg["status"] = "failed"
                seg["error"] = f"轮询异常: {e}"
                del pending[tid]

        if pending:
            logger.debug("  %d 个任务处理中，等待 %ds...", len(pending), POLL_INTERVAL)
            await asyncio.sleep(POLL_INTERVAL)


async def _download_kling(segments, videos_dir, client):
    sem = asyncio.Semaphore(3)

    async def _one(seg):
        url = seg.get("video_url")
        if not url:
            seg["status"] = "failed"
            seg["error"] = "无下载链接"
            return
        path = os.path.join(videos_dir, f"{seg['segment_id']}.mp4")
        try:
            async with sem:
                resp = await client.get(url, timeout=120)
                resp.raise_for_status()
                with open(path, "wb") as f:
                    f.write(resp.content)
                seg["video_path"] = path
                logger.info("  [%s] 下载完成 (%d bytes)", seg["segment_id"], len(resp.content))
        except Exception as e:
            seg["status"] = "failed"
            seg["error"] = f"下载失败: {e}"
            logger.warning("  [%s] %s", seg["segment_id"], e)

    await asyncio.gather(*[_one(s) for s in segments])


# ─── Runway ──────────────────────────────────────────────────────

async def _generate_via_runway(segments, videos_dir, config):
    api_key = config.get("video_api_key") or config.get("api_key") or os.environ.get("RUNWAY_API_KEY")
    if not api_key:
        raise RuntimeError("未找到 Runway API Key。请设置 RUNWAY_API_KEY")

    model = config.get("video_model", "gen-3")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=300) as client:
        for seg in segments:
            try:
                resp = await client.post("https://api.runwayml.com/v1/generate", json={
                    "model": model, "prompt": seg.get("prompt", ""),
                    "duration": config.get("video_duration", 5),
                    "resolution": config.get("video_resolution", "720p"),
                }, headers=headers)
                if resp.status_code == 200:
                    url = resp.json().get("output", {}).get("video")
                    if url:
                        vp = os.path.join(videos_dir, f"{seg['segment_id']}.mp4")
                        vr = await client.get(url)
                        with open(vp, "wb") as f:
                            f.write(vr.content)
                        seg["video_path"] = vp
                        seg["status"] = "completed"
                        logger.info("  [%s] Runway 生成完成", seg["segment_id"])
                    else:
                        seg["status"] = "failed"
                        seg["error"] = "响应中无视频链接"
                else:
                    seg["status"] = "failed"
                    seg["error"] = f"HTTP {resp.status_code}"
            except Exception as e:
                seg["status"] = "failed"
                seg["error"] = str(e)
    return segments


# ─── Mock ────────────────────────────────────────────────────────

async def _generate_mock_videos(segments, videos_dir):
    has_ff = False
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5, check=True)
        has_ff = True
    except Exception:
        pass

    if not has_ff:
        logger.warning("ffmpeg 未安装，生成文本占位")
        for seg in segments:
            path = os.path.join(videos_dir, f"{seg['segment_id']}.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"占位: {seg.get('prompt', '')}\n")
            seg["video_path"] = path
            seg["status"] = "completed"
            seg["_mock"] = True
        return segments

    for seg in segments:
        prompt = seg.get("prompt", "")[:80].replace("'", "").replace('"', "")
        path = os.path.join(videos_dir, f"{seg['segment_id']}.mp4")
        try:
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x1a1a2e:s=1280x720:d=5:r=24",
                   "-vf", f"drawtext=text='Seg {seg['segment_id']}':fontcolor=white:fontsize=20:x=10:y=10,"
                          f"drawtext=text='{prompt[:60]}':fontcolor=#aaaaaa:fontsize=14:x=10:y=40",
                   "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path]
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            if r.returncode == 0 and os.path.exists(path):
                seg["video_path"] = path
                seg["status"] = "completed"
            else:
                cmd2 = ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=0x1a1a2e:s=1280x720:d=5:r=24",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", path]
                r2 = subprocess.run(cmd2, capture_output=True, timeout=30)
                if r2.returncode == 0:
                    seg["video_path"] = path
                    seg["status"] = "completed"
                else:
                    seg["status"] = "failed"
                    seg["error"] = f"ffmpeg: {(r2.stderr or b'?').decode(errors='replace')[:200]}"
        except Exception as e:
            seg["status"] = "failed"
            seg["error"] = str(e)
    return segments
