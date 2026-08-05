import os
from typing import Dict, Any
from datetime import datetime

from pydantic import BaseModel, Field

from ..state import WorkflowState
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..logger import get_logger

logger = get_logger("nodes.parse_docx")


class ScriptStructure(BaseModel):
    title: str = Field(default="未命名", description="剧本标题")
    episode_info: str = Field(default="", description="集数信息")
    characters: list[dict] = Field(default_factory=list, description="人物列表")
    scenes: list[dict] = Field(default_factory=list, description="场景列表")
    props: list[dict] = Field(default_factory=list, description="道具列表")
    content_by_scene: list[dict] = Field(default_factory=list, description="按场景分段的对话内容")
    summary: str = Field(default="", description="剧情摘要")


async def parse_docx_node(
    state: WorkflowState,
    config_manager: ConfigManager,
    model_manager: ModelManager,
    prompt_manager: PromptManager,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "parse_docx"
    new_state["errors"] = []

    log_entry = {
        "node": "parse_docx",
        "start_time": datetime.now().isoformat(),
        "status": "running",
    }
    new_state["execution_log"].append(log_entry)

    try:
        input_path = state.get("input_file_path", "")

        if not input_path or not os.path.exists(input_path):
            raise FileNotFoundError(f"输入文件不存在: {input_path}")

        from docx import Document

        doc = Document(input_path)
        full_text = [para.text for para in doc.paragraphs if para.text.strip()]
        script_content = "\n".join(full_text)

        if not script_content.strip():
            raise ValueError("文档为空或不包含文字")

        new_state["script_content"] = script_content
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))

        script_output_path = os.path.join(output_dir, "原始剧本.txt")
        with open(script_output_path, "w", encoding="utf-8") as f:
            f.write(script_content)
        logger.info("原始剧本已保存: %s (%d 字)", script_output_path, len(script_content))

        llm = model_manager.get_llm_for_node("parse_docx")
        if llm.provider_name == "mock":
            parsed = _fallback_parse(script_content)
            logger.info("使用基础模式解析剧本")
        else:
            messages = prompt_manager.create_messages(
                "parse_docx",
                {"script_content": script_content},
                system_prompt="你是一位专业的影视剧本分析师。请仔细阅读剧本，提取结构化的信息。只返回有效的JSON，不要包含markdown代码块标记。",
            )
            logger.info("调用 LLM 解析剧本结构...")
            parsed = llm.generate_structured(messages, ScriptStructure)
            logger.info(
                "剧本解析完成: 标题='%s', %d 个人物, %d 个场景",
                parsed.title, len(parsed.characters), len(parsed.scenes),
            )

        structured_lines = [f"# {parsed.title}"]
        if parsed.episode_info:
            structured_lines.append(f"**{parsed.episode_info}**")
        structured_lines.append("")

        if parsed.characters:
            structured_lines.append("## 人物列表")
            for c in parsed.characters:
                name = c.get("name", "未知")
                role = c.get("role", "")
                desc = c.get("description", "")
                structured_lines.append(f"- **{name}**（{role}）：{desc}")
            structured_lines.append("")

        if parsed.scenes:
            structured_lines.append("## 场景列表")
            for i, s in enumerate(parsed.scenes, 1):
                name = s.get("name", f"场景{i}")
                loc = s.get("location", "")
                tod = s.get("time_of_day", "")
                structured_lines.append(f"{i}. **{name}** — {loc} / {tod}")
            structured_lines.append("")

        if parsed.summary:
            structured_lines.append("## 剧情摘要")
            structured_lines.append(parsed.summary)
            structured_lines.append("")

        structured_lines.append("## 完整剧本内容")
        structured_lines.append(script_content)
        structured_script = "\n".join(structured_lines)

        new_state["structured_script"] = structured_script

        structured_output_path = os.path.join(output_dir, "结构化剧本.md")
        with open(structured_output_path, "w", encoding="utf-8") as f:
            f.write(structured_script)

        new_state["parsed_characters"] = parsed.characters
        new_state["parsed_scenes"] = parsed.scenes
        new_state["parsed_props"] = parsed.props

        log_entry["status"] = "completed"
        log_entry["end_time"] = datetime.now().isoformat()
        log_entry["output"] = script_output_path

    except Exception as e:
        logger.error("剧本解析失败: %s", e, exc_info=True)
        new_state["errors"].append(f"parse_docx 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


def _fallback_parse(script_content: str) -> ScriptStructure:
    lines = script_content.split("\n")
    title = ""
    for line in lines:
        line = line.strip()
        if "第" in line and "集" in line:
            title = line
            break

    scenes = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or i < 5:
            continue
        if ("【" in line and "】" in line) or line.startswith("##"):
            scenes.append({
                "scene_id": f"scene_{len(scenes)+1}",
                "name": line.replace("【", "").replace("】", "").replace("#", "").strip(),
                "location": "",
                "time_of_day": "",
                "description": "",
            })

    if not scenes:
        scenes.append({"scene_id": "scene_1", "name": "完整内容", "location": "", "time_of_day": "", "description": ""})

    return ScriptStructure(
        title=title or "未命名剧本",
        characters=[],
        scenes=scenes,
        props=[],
        content_by_scene=[],
        summary=script_content[:100] if script_content else "",
    )
