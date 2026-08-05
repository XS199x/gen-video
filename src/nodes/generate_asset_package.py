import os
import json
from typing import Dict, Any, List
from datetime import datetime

from pydantic import BaseModel, Field

from ..state import WorkflowState
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..image_generator import create_image_generator
from ..utils import load_asset_package
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
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))
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
        if image_config:
            try:
                image_generator = create_image_generator(image_config)
                logger.info("使用即梦生成资产图片...")
                all_assets = character_assets + scene_assets + prop_assets
                prompts_with_paths = []

                for asset in all_assets:
                    prompt = asset.get("prompt", "")
                    image_path = asset.get("image_path", "")
                    if prompt and image_path:
                        full_path = os.path.join(output_dir, image_path)
                        asset["image_path"] = full_path
                        prompts_with_paths.append({"prompt": prompt, "save_path": full_path})

                if prompts_with_paths:
                    results = image_generator.generate_batch(prompts_with_paths, delay=1.0)
                    generated_count = sum(1 for r in results if r)
                    for idx, asset in enumerate(all_assets):
                        if idx < len(results) and results[idx]:
                            asset["image_generated"] = True
                            asset["image_status"] = "generated"
                        else:
                            asset["image_generated"] = False
                            asset["image_status"] = "failed"
                    images_generated = generated_count > 0
                    logger.info("图片生成完成: %d/%d", generated_count, len(prompts_with_paths))
            except Exception as e:
                logger.warning("图片生成器初始化失败，跳过图片生成: %s", e)
                for asset in character_assets + scene_assets + prop_assets:
                    asset["image_generated"] = False
                    asset["image_status"] = "api_unavailable"
        else:
            logger.info("未配置图片生成，跳过（可后续手动上传图片）")
            for asset in character_assets + scene_assets + prop_assets:
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
