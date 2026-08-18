"""
数据血缘（Lineage）—— 工作流步骤依赖关系的单一权威。

痛点背景：
    「步骤顺序 / 标签 / 免费付费切分 / 字段→步骤映射 / 步骤→产出字段」
    原先散落在多处硬编码副本：
      - project_manager.STEP_NAMES / STEP_LABELS / PREVIEW_STEPS / GENERATE_STEPS
      - workflow.STEP_ORDER / NODE_NAMES / PREVIEW_STEPS / GENERATE_STEPS
      - project_manager._field_path_to_step 的内联 map
      - server.clear_state_from_step 的 clear_map
    多份副本一旦漂移，血缘失效逻辑就会静默出错。

契约（显式化）：
    本模块是步骤血缘的唯一来源。所有需要「某字段属于哪一步」「某步的下游有哪些」
    「某步是否付费」「某步产出哪些 state 字段」的地方，一律 import 这里，不再各自维护。

血缘模型（步骤级）：
    7 步线性流水线，编辑属于步骤 N 的字段 → N 及其所有下游步骤失效（标脏）。
"""

from typing import List, Optional


# ─── 步骤线性血缘（唯一权威）────────────────────────────────────────

STEP_ORDER: List[str] = [
    "parse_docx",
    "generate_asset_package",
    "step1_storyboard",
    "step2_consistency",
    "step3_optimize_prompts",
    "generate_videos",
    "merge_videos",
]

STEP_LABELS = {
    "parse_docx": "解析剧本",
    "generate_asset_package": "生成资产包",
    "step1_storyboard": "分镜生成",
    "step2_consistency": "一致性检查",
    "step3_optimize_prompts": "优化提示词",
    "generate_videos": "生成视频",
    "merge_videos": "合并视频",
}

# 预览阶段（免费，不含视频生成和合并）
PREVIEW_STEPS: List[str] = STEP_ORDER[:5]
# 生成阶段（付费）
GENERATE_STEPS: List[str] = STEP_ORDER[5:]


# ─── 字段前缀 → 步骤（取代 _field_path_to_step 内联 map）──────────────
#
# 编辑某个 state 字段时，用于定位它属于哪一步。按前缀匹配（field_path
# 形如 "optimized_prompts.0.shots.2.prompt"）。

FIELD_TO_STEP = {
    "script_content": "parse_docx",
    "structured_script": "parse_docx",
    "parsed_characters": "parse_docx",
    "parsed_scenes": "parse_docx",
    "parsed_props": "parse_docx",
    "character_assets": "generate_asset_package",
    "scene_assets": "generate_asset_package",
    "prop_assets": "generate_asset_package",
    "shot_groups": "step1_storyboard",
    "scene_table": "step1_storyboard",
    "camera_positions": "step1_storyboard",
    "consistency_anchors": "step2_consistency",
    "optimized_prompts": "step3_optimize_prompts",
    "video_segments": "generate_videos",
    "final_video_path": "merge_videos",
}


# ─── 步骤 → 该步产出的 state 字段（取代 clear_state_from_step 的 clear_map）──

STEP_OUTPUT_FIELDS = {
    "parse_docx": [
        "script_content", "structured_script",
        "parsed_characters", "parsed_scenes", "parsed_props",
    ],
    "generate_asset_package": [
        "assets_generated", "character_assets", "scene_assets", "prop_assets",
        "asset_prompts", "asset_table_path", "images_generated",
    ],
    "step1_storyboard": [
        "step1_completed", "scene_table", "camera_positions", "opening_state",
        "shot_groups", "step1_output_path", "step1_optimized_path",
    ],
    "step2_consistency": [
        "step2_completed", "consistency_anchors", "step2_output_path",
    ],
    "step3_optimize_prompts": [
        "step3_completed", "optimized_prompts", "step3_output_path",
    ],
    "generate_videos": [
        "videos_generated", "video_segments", "video_output_dir",
    ],
    "merge_videos": [
        "videos_merged", "final_video_path",
    ],
}


# ─── 查询函数 ──────────────────────────────────────────────────────

def field_to_step(field_path: str) -> Optional[str]:
    """把 state 字段路径映射到它所属的步骤（按前缀）。找不到返回 None。"""
    if not field_path:
        return None
    for prefix, step in FIELD_TO_STEP.items():
        # 精确边界匹配：整串相等，或以 "prefix." 开头（数组/嵌套字段）。
        # 避免 startswith(prefix) 的前缀歧义（如 foo 误匹配 foobar）。
        if field_path == prefix or field_path.startswith(prefix + "."):
            return step
    return None


def downstream_steps(step_name: str, include_self: bool = True) -> List[str]:
    """返回该步骤及其所有下游步骤（默认含自身）。未知步骤返回空列表。"""
    if step_name not in STEP_ORDER:
        return []
    idx = STEP_ORDER.index(step_name)
    start = idx if include_self else idx + 1
    return STEP_ORDER[start:]


def is_paid_step(step_name: str) -> bool:
    """该步骤是否属于付费阶段（generate_videos / merge_videos）。"""
    return step_name in GENERATE_STEPS
