import os
from typing import Dict, Any, List
from datetime import datetime

from pydantic import BaseModel, Field

from ..state import WorkflowState
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..image_generator import create_image_generator
from ..utils import load_asset_package
from ..paths import to_project_relative
from .. import reentrancy
from ..logger import get_logger

logger = get_logger("nodes.generate_asset_package")


class AssetItem(BaseModel):
    name: str = Field(description="资产名称")
    description: str = Field(description="资产描述")
    prompt: str = Field(description="AI 图像生成提示词，包含完整视觉细节")


class AssetPackage(BaseModel):
    visual_style: str = Field(default="", description="固定视觉风格描述")
    character_angle: str = Field(default="", description="固定人物拍摄角度")
    characters: List[AssetItem] = Field(default_factory=list, description="人物资产")
    scenes: List[AssetItem] = Field(default_factory=list, description="场景资产")
    props: List[AssetItem] = Field(default_factory=list, description="道具资产")


async def generate_asset_package_node(
    state: WorkflowState,
    config_manager: ConfigManager,
    model_manager: ModelManager,
    prompt_manager: PromptManager,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "generate_asset_package"
    new_state["errors"] = []

    log_entry = {
        "node": "generate_asset_package",
        "start_time": datetime.now().isoformat(),
        "status": "running",
    }
    new_state["execution_log"].append(log_entry)

    try:
        episode_id = state.get("episode_id", "unknown")
        output_dir = config_manager.get_output_dir(episode_id)
        assets_dir = os.path.join(output_dir, "资产")
        os.makedirs(assets_dir, exist_ok=True)

        structured_script = state.get("structured_script", state.get("script_content", ""))

        context = {
            "episode_id": state.get("episode_id", "01"),
            "structured_script": structured_script,
        }

        llm = model_manager.get_llm_for_node("generate_asset_package")

        if llm.provider_name == "mock":
            asset = _fallback_asset_package()
            logger.info("使用 Mock 资产包")
        else:
            messages = prompt_manager.create_messages(
                "generate_asset_package",
                context,
                system_prompt=(
                    "你是一位专业的视觉资产设计师，擅长为影视分镜设计统一风格的角色、场景、道具描述。"
                    "只返回有效的 JSON，不要包含 markdown 代码块标记。"
                ),
            )
            logger.info("调用 LLM 生成资产包...")
            asset = llm.generate_structured(messages, AssetPackage)
            logger.info(
                "资产包生成完成: %d 个人物, %d 个场景, %d 个道具",
                len(asset.characters), len(asset.scenes), len(asset.props),
            )

        character_assets = [
            {
                "name": c.name,
                "description": c.description,
                "prompt": c.prompt,
                "category": "character",
                "image_path": f"资产/人物/{c.name.replace(' ', '_')}.png",
            }
            for c in asset.characters
        ]
        scene_assets = [
            {
                "name": s.name,
                "description": s.description,
                "prompt": s.prompt,
                "category": "scene",
                "image_path": f"资产/场景/{s.name.replace(' ', '_')}.png",
            }
            for s in asset.scenes
        ]
        prop_assets = [
            {
                "name": p.name,
                "description": p.description,
                "prompt": p.prompt,
                "category": "prop",
                "image_path": f"资产/道具/{p.name.replace(' ', '_')}.png",
            }
            for p in asset.props
        ]

        md_lines = [
            f"# 第{state.get('episode_id', '01')}集 一句话特征资产包表",
            "",
            "## 固定视觉风格",
            asset.visual_style or "国漫男主美型面部、3D微写实材质、Cinematic lighting",
            "",
            "## 固定人物角度",
            asset.character_angle or "正面基础上约20°轻微侧位",
            "",
            "## 人物资产",
            "| 人物 | 描述 | 一句话特征 |",
            "|------|------|-----------|",
        ]
        for c in character_assets:
            md_lines.append(f"| {c['name']} | {c['description'][:50]} | {c['prompt'][:80]} |")

        md_lines.extend(["", "## 场景资产（无人物）", "| 场景 | 描述 | 一句话特征 |", "|------|------|-----------|"])
        for s in scene_assets:
            md_lines.append(f"| {s['name']} | {s['description'][:50]} | {s['prompt'][:80]} |")

        md_lines.extend(["", "## 道具资产", "| 道具 | 描述 | 一句话特征 |", "|------|------|-----------|"])
        for p in prop_assets:
            md_lines.append(f"| {p['name']} | {p['description'][:50]} | {p['prompt'][:80]} |")

        asset_table_path = os.path.join(assets_dir, "资产包.md")
        with open(asset_table_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))

        asset_prompts = {
            "characters": [c.get("prompt", "") for c in character_assets],
            "scenes": [s.get("prompt", "") for s in scene_assets],
            "props": [p.get("prompt", "") for p in prop_assets],
        }

        # 图片生成（可选 — 失败不阻断管线）
        image_config = config_manager.get_image_config()
        images_generated = False

        # 幂等续跑：把上一轮 state 里同名资产（name+category 对齐）已有的图片
        # image_path/image_status 回填到本轮资产上，供分流判定「已出图可跳过」。
        _backfill_asset_images(
            character_assets + scene_assets + prop_assets, state)

        if image_config:
            try:
                image_generator = create_image_generator(image_config)
                logger.info("使用即梦生成资产图片...")
                all_assets = character_assets + scene_assets + prop_assets

                # 先把每个资产的 image_path 规范化为相对 posix（路径契约），
                # 并把 image_status 归一化到临时 status 字段供 reentrancy 判定。
                for asset in all_assets:
                    image_path = asset.get("image_path", "")
                    if image_path:
                        full_path = os.path.join(output_dir, image_path) \
                            if not os.path.isabs(image_path) else image_path
                        asset["image_path"] = to_project_relative(full_path, episode_id)
                    asset["status"] = _norm_status(asset.get("image_status"))

                # 幂等分流：已出图且文件在→skip；用户手动占位→preserve；其余→regen。
                force = bool(state.get("_force_regenerate", False))
                skip, regen, preserve = reentrancy.partition_units(
                    all_assets, "image_path", output_dir, force=force)
                logger.info("资产图片分流: 跳过 %d / 补跑 %d / 保留 %d（force=%s）",
                             len(skip), len(regen), len(preserve), force)

                # skip/preserve 的资产维持原状态；只对 regen 出图。
                for asset in skip:
                    asset["image_generated"] = True
                prompts_with_paths = []
                for asset in regen:
                    prompt = asset.get("prompt", "")
                    rel_path = asset.get("image_path", "")
                    if prompt and rel_path:
                        # 生成器需要绝对路径落盘
                        full_path = os.path.join(output_dir, rel_path)
                        prompts_with_paths.append({"prompt": prompt, "save_path": full_path})

                if prompts_with_paths:
                    results = image_generator.generate_batch(prompts_with_paths, delay=1.0)
                    generated_count = sum(1 for r in results if r)
                    for idx, asset in enumerate(regen):
                        if idx < len(results) and results[idx]:
                            asset["image_generated"] = True
                            asset["image_status"] = "generated"
                        else:
                            asset["image_generated"] = False
                            asset["image_status"] = "failed"
                    logger.info("图片生成完成: %d/%d（补跑）", generated_count, len(prompts_with_paths))
                images_generated = any(
                    a.get("image_status") == "generated" for a in all_assets)

                # 清理临时归一化字段，不污染持久化 state
                for asset in all_assets:
                    asset.pop("status", None)
            except Exception as e:
                logger.warning("图片生成器初始化失败，跳过图片生成: %s", e)
                for asset in character_assets + scene_assets + prop_assets:
                    asset.pop("status", None)
                    # 已有图的资产保留其状态，未出图的标 api_unavailable
                    if asset.get("image_status") != "generated":
                        asset["image_generated"] = False
                        asset["image_status"] = "api_unavailable"
        else:
            logger.info("未配置图片生成，跳过（可后续手动上传图片）")
            for asset in character_assets + scene_assets + prop_assets:
                # 已有图/手动上传的资产保留其状态，否则标待上传
                if asset.get("image_status") not in ("generated", "pending_upload"):
                    asset["image_generated"] = False
                    asset["image_status"] = "pending_upload"

        new_state.update({
            "assets_generated": True,
            "character_assets": character_assets,
            "scene_assets": scene_assets,
            "prop_assets": prop_assets,
            "asset_prompts": asset_prompts,
            "asset_table_path": asset_table_path,
            "images_generated": images_generated,
        })
        # 运行时临时控制字段，不持久化污染 state
        new_state.pop("_force_regenerate", None)

        log_entry["status"] = "completed"
        log_entry["end_time"] = datetime.now().isoformat()
        log_entry["output"] = asset_table_path
        log_entry["assets_count"] = {
            "characters": len(character_assets),
            "scenes": len(scene_assets),
            "props": len(prop_assets),
        }

    except Exception as e:
        logger.error("资产包生成失败: %s", e, exc_info=True)
        new_state["errors"].append(f"generate_asset_package 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


def _norm_status(image_status) -> str:
    """把资产的 image_status 归一化为 reentrancy 判定用的临时 status。

    资产状态语义与视频不同（用 image_status 而非 status），这里做映射：
      generated      → completed    （出图成功，配合文件存在性→skip）
      pending_upload → pending_upload（用户手动占位→preserve）
      其余/None       → pending       （未出图/失败→regen）
    """
    if image_status == "generated":
        return "completed"
    if image_status == "pending_upload":
        return "pending_upload"
    return "pending"


def _backfill_asset_images(assets: list, prev_state: dict) -> None:
    """用上一轮 state 的同名资产（name+category 对齐键）回填 image_path/image_status。

    LLM 每次可能生成略不同的资产名 → 用 (name, category) 作为对齐键。命中的资产
    把上一轮已有的 image_path/image_generated/image_status 带过来，供后续分流判定
    「已出图可跳过」；名字变了的视为新资产（无回填→regen）。就地修改 assets。
    """
    prev = (prev_state.get("character_assets") or []) \
        + (prev_state.get("scene_assets") or []) \
        + (prev_state.get("prop_assets") or [])
    by_key = {(a.get("name"), a.get("category")): a for a in prev}
    for asset in assets:
        old = by_key.get((asset.get("name"), asset.get("category")))
        if not old:
            continue
        for k in ("image_path", "image_generated", "image_status"):
            if old.get(k) is not None:
                asset[k] = old[k]


def _fallback_asset_package() -> AssetPackage:
    return AssetPackage(
        visual_style="国漫男主美型面部、3D微写实材质、Cinematic lighting, rim lighting, 8k resolution",
        character_angle="正面基础上约20°轻微侧位",
        characters=[AssetItem(
            name="主角",
            description="剧集主要角色",
            prompt="国漫美型男角色，冷白皮，3D微写实材质，正面20°侧位，逆光轮廓光，8k",
        )],
        scenes=[AssetItem(
            name="主场景",
            description="剧集主要场景",
            prompt="场景环境，无人物，Cinematic lighting, rim lighting, 8k resolution",
        )],
        props=[],
    )
