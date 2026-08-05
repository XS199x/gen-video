import os
import json
from typing import Dict, List
from datetime import datetime

from pydantic import BaseModel, Field

from ..state import WorkflowState
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..utils import load_asset_package, load_storyboard
from ..logger import get_logger

logger = get_logger("nodes.optimize_prompts")


class OptimizedShot(BaseModel):
    shot_name: str = Field(description="镜头名称/编号")
    description: str = Field(default="", description="画面构成描述")
    prompt: str = Field(default="", description="AI 视频生成提示词")
    dialogue: str = Field(default="", description="台词内容")
    visual_style: str = Field(default="", description="视觉风格描述")
    audio: str = Field(default="", description="环境音效描述")


class OptimizedPromptGroup(BaseModel):
    group_name: str = Field(description="镜头组名称")
    material_references: List[str] = Field(default_factory=list, description="@图 素材引用")
    character_voices: List[str] = Field(default_factory=list, description="@音频 音色指定")
    style_instructions: List[str] = Field(default_factory=list, description="风格约束指令")
    shots: List[OptimizedShot] = Field(default_factory=list, description="该组的所有镜头")


async def step3_optimize_prompts_node(
    state: WorkflowState, config_manager: ConfigManager,
    model_manager: ModelManager, prompt_manager: PromptManager,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "step3_optimize_prompts"
    new_state["errors"] = []

    log_entry = {"node": "step3_optimize_prompts", "start_time": datetime.now().isoformat(), "status": "running"}
    new_state["execution_log"].append(log_entry)

    try:
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))
        storyboard = load_storyboard(state, output_dir)
        assets = load_asset_package(state, output_dir)

        context = {
            "episode_id": state.get("episode_id", "01"),
            "step2_storyboard": storyboard,
            "asset_package": assets,
        }

        llm = model_manager.get_llm_for_node("step3_optimize_prompts")

        try:
            messages = prompt_manager.create_messages(
                "step3_optimize_prompts", context,
                system_prompt="你是一位专业的AI视频提示词工程师，将分镜脚本转化为用于AI视频生成的精确提示词。只返回有效的JSON。",
            )
            logger.info("调用 LLM 优化视频提示词...")
            result = llm.generate_structured(messages, OptimizedPromptGroup)
            prompts_data = [result.model_dump()]
            logger.info("结构化输出成功: 1 组, %d 个镜头", len(result.shots))
        except Exception as e:
            logger.warning("结构化输出失败，回退到文本解析: %s", e)
            optimized_content = llm.generate(prompt_manager.create_messages(
                "step3_optimize_prompts", context,
                system_prompt="你是一位专业的AI视频提示词工程师，将分镜脚本转化为用于AI视频生成的精确提示词。",
            ))
            prompts_data = _parse_optimized_prompts(optimized_content)
            logger.info("文本解析完成: %d 组镜头", len(prompts_data))

        md_content = _markdown_output(prompts_data)
        step3_output_path = os.path.join(output_dir, "优化提示词.md")
        with open(step3_output_path, "w", encoding="utf-8") as f:
            f.write(md_content)

        prompts_json_path = os.path.join(output_dir, "视频提示词.json")
        with open(prompts_json_path, "w", encoding="utf-8") as f:
            json.dump(prompts_data, f, ensure_ascii=False, indent=2)

        total_shots = sum(len(g.get("shots", [])) for g in prompts_data)
        logger.info("提示词优化完成: %d 组, %d 个镜头", len(prompts_data), total_shots)

        new_state.update({
            "step3_completed": True,
            "optimized_prompts": prompts_data,
            "step3_output_path": step3_output_path,
        })

        log_entry["status"] = "completed"
        log_entry["end_time"] = datetime.now().isoformat()
        log_entry["output"] = step3_output_path
        log_entry["prompts_count"] = total_shots

    except Exception as e:
        logger.error("提示词优化失败: %s", e, exc_info=True)
        new_state["errors"].append(f"step3_optimize_prompts 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


def _markdown_output(prompts_data: List[Dict]) -> str:
    lines = ["# 优化后的视频提示词", ""]
    for group in prompts_data:
        lines.append(f"## 镜头组 {group.get('group_name', 'Untitled')}")
        lines.append("")
        for ref in group.get("material_references", []):
            lines.append(f"- {ref}")
        for voice in group.get("character_voices", []):
            lines.append(voice)
        for inst in group.get("style_instructions", []):
            lines.append(inst)
        lines.append("")
        for shot in group.get("shots", []):
            lines.append(f"#### {shot.get('shot_name', '镜头')}")
            if shot.get("description"):
                lines.append(f"**画面构成：** {shot['description']}")
            if shot.get("prompt"):
                lines.append(f"**画面内容：** {shot['prompt']}")
            if shot.get("dialogue"):
                lines.append(f"**对话：** {shot['dialogue']}")
            if shot.get("visual_style"):
                lines.append(f"**视觉风格：** {shot['visual_style']}")
            if shot.get("audio"):
                lines.append(f"**环境音：** {shot['audio']}")
            lines.append("")
    return "\n".join(lines)


def _parse_optimized_prompts(content: str) -> list:
    prompts = []
    for section in content.split("## 镜头组")[1:]:
        lines = section.strip().split("\n")
        group = {
            "group_name": lines[0].strip() if lines else "unknown",
            "material_references": [], "character_voices": [],
            "style_instructions": [], "shots": [],
        }
        cur, field = None, None
        for line in lines[1:]:
            s = line.strip()
            if not s:
                continue
            if "@图" in s and s.startswith("-"):
                group["material_references"].append(s)
            elif "@音频" in s:
                group["character_voices"].append(s)
            elif "不要音乐" in s or "不要字幕" in s or "音效" in s:
                if s not in group["style_instructions"]:
                    group["style_instructions"].append(s)
            elif s.startswith("####") or ("镜头" in s and "**" in s):
                if cur: group["shots"].append(cur)
                cur = {"shot_name": s.replace("#### ", "").replace("**", "").strip(),
                       "description": "", "prompt": "", "dialogue": "", "visual_style": "", "audio": ""}
                field = None
            elif cur:
                for kw, f in [("画面构成", "description"), ("画面内容", "prompt"), ("对话", "dialogue"),
                               ("视觉风格", "visual_style"), ("环境音", "audio")]:
                    if kw in s:
                        field = f
                        cur[f] = s.replace(f"**{kw}**", "").replace(f"{kw}：", "").replace(f"{kw}", "").replace(":", "").strip()
                        break
                else:
                    if field and s.startswith("-"):
                        cur[field] = cur[field] + "\n" + s if cur[field] else s
        if cur: group["shots"].append(cur)
        if group["shots"]: prompts.append(group)
    return prompts or [{"group_name": "默认组", "shots": [{"shot_name": "完整内容", "prompt": content, "description": content}],
                        "material_references": [], "character_voices": [],
                        "style_instructions": ["不要音乐。不要字幕。音效自然。"]}]
