import os
from typing import Any, Dict, List
from datetime import datetime

from ..state import WorkflowState, ConsistencyAnchor
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..utils import load_asset_package, load_storyboard
from ..logger import get_logger

logger = get_logger("nodes.consistency")


async def step2_consistency_node(
    state: WorkflowState, config_manager: ConfigManager,
    model_manager: ModelManager, prompt_manager: PromptManager,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "step2_consistency"
    new_state["errors"] = []

    log_entry = {"node": "step2_consistency", "start_time": datetime.now().isoformat(), "status": "running"}
    new_state["execution_log"].append(log_entry)

    try:
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))
        storyboard = load_storyboard(state, output_dir)
        assets = load_asset_package(state, output_dir)

        messages = prompt_manager.create_messages(
            "step2_consistency",
            {"episode_id": state.get("episode_id", "01"), "step1_storyboard": storyboard, "asset_package": assets},
            system_prompt="你是一位专业的影视制片专家，擅长检查分镜脚本的视觉一致性和逻辑连贯性。",
        )

        llm = model_manager.get_llm_for_node("step2_consistency")
        logger.info("运行一致性检查...")
        result = llm.generate(messages)

        step2_output_path = os.path.join(output_dir, "一致性检查报告.md")
        with open(step2_output_path, "w", encoding="utf-8") as f:
            f.write(result)

        anchors = _extract_anchors(result)
        optimized = _extract_optimized_storyboard(result)

        if optimized:
            opt_path = os.path.join(output_dir, "分镜脚本_优化版.md")
            with open(opt_path, "w", encoding="utf-8") as f:
                f.write(optimized)
            new_state["step1_optimized_path"] = opt_path
            logger.info("优化后分镜已保存: %s", opt_path)

        logger.info("一致性检查完成: %d 个锚点", len(anchors))

        new_state.update({
            "step2_completed": True,
            "consistency_anchors": anchors,
            "step2_output_path": step2_output_path,
        })

        log_entry["status"] = "completed"
        log_entry["end_time"] = datetime.now().isoformat()
        log_entry["output"] = step2_output_path
        log_entry["anchors_count"] = len(anchors)

    except Exception as e:
        logger.error("一致性检查失败: %s", e, exc_info=True)
        new_state["errors"].append(f"step2_consistency 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


def _extract_anchors(content: str) -> List[ConsistencyAnchor]:
    anchors = []
    for section in content.split("### "):
        if "一致性检查" in section or "检查点" in section:
            for line in section.strip().split("\n")[1:]:
                line = line.strip()
                if "**" in line and ":" in line:
                    parts = line.split(":", 1)
                    name = parts[0].replace("**", "").strip()
                    val = parts[1].strip() if len(parts) > 1 else ""
                    if val and len(val) > 5:
                        anchors.append(ConsistencyAnchor(
                            anchor_type="consistency", anchor_name=name,
                            anchor_value=val, affected_scenes=[], notes="",
                        ))
    return anchors


def _extract_optimized_storyboard(content: str) -> str:
    if "优化后的分镜脚本" in content:
        body = content.split("优化后的分镜脚本")[1]
        if "##" in body:
            body = body.split("##")[0]
        if "```" in body:
            for part in body.split("```"):
                if part and len(part.strip()) > 500:
                    return part.strip()
        return body.strip()
    if "优化说明" in content:
        body = content.split("优化说明")[1]
        if "```" in body:
            parts = body.split("```")
            if len(parts) > 2:
                return parts[2].strip()
    return ""
