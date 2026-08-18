from langgraph.graph import StateGraph, END
from .state import WorkflowState, create_initial_state
from .config_manager import ConfigManager
from .model_manager import ModelManager
from .prompt_manager import PromptManager
from . import lineage
from .logger import setup_logging, get_logger
from .nodes.parse_docx import parse_docx_node
from .nodes.generate_asset_package import generate_asset_package_node
from .nodes.step1_storyboard import step1_storyboard_node
from .nodes.step2_consistency import step2_consistency_node
from .nodes.step3_optimize_prompts import step3_optimize_prompts_node
from .nodes.generate_videos import generate_videos_node
from .nodes.merge_videos import merge_videos_node

logger = get_logger("workflow")

# 步骤顺序 / 标签 / 免费付费切分统一复用血缘单一权威（src/lineage.py）。
NODE_NAMES = lineage.STEP_LABELS
STEP_ORDER = lineage.STEP_ORDER
PREVIEW_STEPS = lineage.PREVIEW_STEPS   # 预览阶段（免费）
GENERATE_STEPS = lineage.GENERATE_STEPS  # 生成阶段（付费）

# NODE_FUNCS 是节点函数映射，属 workflow 职责，保留在本地。
NODE_FUNCS = {
    "parse_docx": parse_docx_node,
    "generate_asset_package": generate_asset_package_node,
    "step1_storyboard": step1_storyboard_node,
    "step2_consistency": step2_consistency_node,
    "step3_optimize_prompts": step3_optimize_prompts_node,
    "generate_videos": generate_videos_node,
    "merge_videos": merge_videos_node,
}


class VideoWorkflow:
    def __init__(self, config_path: str = None):
        self.config_manager = ConfigManager(config_path)

        log_level = self.config_manager.get_global("log_level", "INFO")
        output_dir = self.config_manager.get_global("output_base_dir", "./outputs")
        setup_logging(log_level, log_dir=output_dir)

        self.model_manager = ModelManager(self.config_manager)
        self.prompt_manager = PromptManager(self.config_manager)
        self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(WorkflowState)

        for name in STEP_ORDER:
            workflow.add_node(name, self._wrap_node(name, NODE_FUNCS[name]))

        workflow.set_entry_point(STEP_ORDER[0])
        for i in range(len(STEP_ORDER) - 1):
            workflow.add_edge(STEP_ORDER[i], STEP_ORDER[i + 1])
        workflow.add_edge(STEP_ORDER[-1], END)

        self.graph = workflow.compile()

    def _wrap_node(self, node_name, node_func):
        async def wrapped(state: WorkflowState) -> WorkflowState:
            label = NODE_NAMES.get(node_name, node_name)
            logger.info("--- 步骤: %s ---", label)
            result = await node_func(state, self.config_manager, self.model_manager, self.prompt_manager)
            errors = result.get("errors", [])
            if errors:
                logger.warning("%s 完成，但有 %d 个错误: %s", label, len(errors), errors)
            return result
        return wrapped

    async def run(self, episode_id: str, episode_title: str, input_file_path: str) -> WorkflowState:
        initial = create_initial_state(episode_id, episode_title, input_file_path)
        final = await self.graph.ainvoke(initial)
        return final

    async def run_step(self, step_name: str, state: WorkflowState) -> WorkflowState:
        """执行单个步骤，传入当前状态，返回更新后的状态。"""
        if step_name not in NODE_FUNCS:
            raise ValueError(f"未知步骤: {step_name}，可用步骤: {list(NODE_FUNCS.keys())}")
        label = NODE_NAMES.get(step_name, step_name)
        logger.info("--- 单步执行: %s ---", label)
        result = await self._wrap_node(step_name, NODE_FUNCS[step_name])(dict(state))
        return result

    async def run_preview_phase(self, episode_id: str, episode_title: str,
                                 input_file_path: str) -> WorkflowState:
        """执行预览阶段（前5步），在视频生成前停止。"""
        state = create_initial_state(episode_id, episode_title, input_file_path)
        for name in PREVIEW_STEPS:
            state = await self.run_step(name, state)
        return state

    async def run_from_step(self, start_step: str, episode_id: str, episode_title: str,
                            input_file_path: str, existing_state: WorkflowState = None) -> WorkflowState:
        state = existing_state or create_initial_state(episode_id, episode_title, input_file_path)
        idx = STEP_ORDER.index(start_step) if start_step in STEP_ORDER else 0
        for name in STEP_ORDER[idx:]:
            state = await self.run_step(name, state)
        return state

    def get_model_manager(self):
        return self.model_manager

    def get_config_manager(self):
        return self.config_manager

    def get_prompt_manager(self):
        return self.prompt_manager
