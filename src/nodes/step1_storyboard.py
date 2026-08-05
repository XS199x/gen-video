import os
import json
from typing import Dict, Any, List
from datetime import datetime

from ..state import WorkflowState, SceneInfo, ShotGroup
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..utils import load_asset_package
from ..logger import get_logger

logger = get_logger("nodes.storyboard")


async def step1_storyboard_node(
    state: WorkflowState, config_manager: ConfigManager,
    model_manager: ModelManager, prompt_manager: PromptManager,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "step1_storyboard"
    new_state["errors"] = []

    log_entry = {"node": "step1_storyboard", "start_time": datetime.now().isoformat(), "status": "running"}
    new_state["execution_log"].append(log_entry)

    try:
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))
        asset_package = load_asset_package(state, output_dir)
        structured_script = state.get("structured_script", state.get("script_content", ""))

        messages = prompt_manager.create_messages(
            "step1_storyboard",
            {
                "episode_id": state.get("episode_id", "01"),
                "structured_script": structured_script,
                "asset_package": asset_package,
            },
            system_prompt="你是一位专业的影视分镜导演，擅长将剧本转化为详细的分镜脚本。你的分镜需要包含完整的场景分析、机位设计、镜头序列和详细的视觉描述。",
        )

        llm = model_manager.get_llm_for_node("step1_storyboard")
        logger.info("生成分镜脚本...")
        storyboard_content = llm.generate(messages)

        step1_output_path = os.path.join(output_dir, "分镜脚本.md")
        with open(step1_output_path, "w", encoding="utf-8") as f:
            f.write(storyboard_content)

        scenes = _extract_scenes(storyboard_content)
        camera_positions = _extract_camera_positions(storyboard_content)
        shot_groups = _extract_shot_groups(storyboard_content)

        logger.info("分镜脚本完成: %d 个场景, %d 个机位, %d 组镜头", len(scenes), len(camera_positions), len(shot_groups))

        new_state.update({
            "step1_completed": True,
            "scene_table": scenes,
            "camera_positions": camera_positions,
            "shot_groups": shot_groups,
            "step1_output_path": step1_output_path,
        })

        log_entry["status"] = "completed"
        log_entry["end_time"] = datetime.now().isoformat()
        log_entry["output"] = step1_output_path
        log_entry["stats"] = {
            "scenes": len(scenes), "cameras": len(camera_positions), "shots": len(shot_groups),
        }

    except Exception as e:
        logger.error("分镜生成失败: %s", e, exc_info=True)
        new_state["errors"].append(f"step1_storyboard 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


def _extract_scenes(content: str) -> List[SceneInfo]:
    scenes = []
    sections = content.split("### 空间")
    for section in sections[1:]:
        lines = section.strip().split("\n")
        scene_info: SceneInfo = {
            "scene_id": f"scene_{len(scenes) + 1}",
            "scene_name": lines[0] if lines else "",
            "location": "", "time_of_day": "", "characters": [], "props": [], "description": "",
        }
        for line in lines[1:]:
            line = line.strip()
            if "场景" in line and ":" in line:
                scene_info["description"] = line.split(":", 1)[1].strip()
            if "人物" in line and ":" in line:
                chars = line.split(":", 1)[1].strip()
                scene_info["characters"] = [c.strip() for c in chars.split("、") if c.strip()]
            if "时间" in line and ":" in line:
                scene_info["time_of_day"] = line.split(":", 1)[1].strip()
        scenes.append(scene_info)
    return scenes


def _extract_camera_positions(content: str) -> List[Dict[str, Any]]:
    cameras = []
    if "## 机位表" in content:
        body = content.split("## 机位表")[1]
        if "##" in body:
            body = body.split("##")[0]
        for line in body.strip().split("\n"):
            line = line.strip()
            if line.startswith("- 机位") or line.startswith("- "):
                cam_id = line.split("（")[0].strip() if "（" in line else line
                cameras.append({"camera_id": cam_id.replace("- ", "").strip(), "description": line})
    return cameras


def _extract_shot_groups(content: str) -> List[ShotGroup]:
    shot_groups = []
    sections = content.split("## 镜头组")
    for section in sections[1:]:
        lines = section.strip().split("\n")
        first = lines[0] if lines else ""
        g: ShotGroup = {
            "group_id": f"group_{len(shot_groups)+1}", "group_name": first,
            "estimated_duration": "", "narrative_function": "", "transition": "",
            "status": "pending", "shots": [],
        }
        for key, cn in [("预计时长", "estimated_duration"), ("叙事功能", "narrative_function"), ("转场设计", "transition")]:
            if cn in first:
                g[cn] = first.split(f"{cn}：")[1].split("｜")[0].strip() if f"{cn}：" in first else ""

        shots, cur = [], None
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("镜头") and "：" in line:
                if cur: shots.append(cur)
                cur = {"shot_id": line.split("：")[0].strip(), "shot_type": "",
                       "content": line.split("：", 1)[1].strip() if len(line.split("：")) > 1 else ""}
            elif cur:
                for kw, field in [("画面构成", "framing"), ("台词", "dialogue"), ("镜头语言", "shot_type"),
                                   ("视觉风格", "visual_style"), ("环境音", "audio_notes")]:
                    if kw in line:
                        cur[field] = line.replace(f"{kw}：", "").strip()
        if cur: shots.append(cur)
        g["shots"] = shots
        shot_groups.append(g)
    return shot_groups
