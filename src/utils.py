"""为各工作流节点提供的共享工具函数。"""

import os

from .state import WorkflowState


def load_asset_package(state: WorkflowState, output_dir: str) -> str:
    asset_path = state.get("asset_table_path")
    if asset_path and os.path.exists(asset_path):
        with open(asset_path, "r", encoding="utf-8") as f:
            return f.read()

    fallback_path = os.path.join(output_dir, "资产", "资产包.md")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return f.read()

    return "资产包尚未生成"


def load_storyboard(state: WorkflowState, output_dir: str) -> str:
    optimized = state.get("step1_optimized_path")
    if optimized and os.path.exists(optimized):
        with open(optimized, "r", encoding="utf-8") as f:
            return f.read()

    step1_path = state.get("step1_output_path")
    if step1_path and os.path.exists(step1_path):
        with open(step1_path, "r", encoding="utf-8") as f:
            return f.read()

    fallback_path = os.path.join(output_dir, "分镜脚本.md")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return f.read()

    return "分镜脚本尚未生成"


def load_consistency_report(state: WorkflowState, output_dir: str) -> str:
    step2_path = state.get("step2_output_path")
    if step2_path and os.path.exists(step2_path):
        with open(step2_path, "r", encoding="utf-8") as f:
            return f.read()

    fallback_path = os.path.join(output_dir, "一致性检查报告.md")
    if os.path.exists(fallback_path):
        with open(fallback_path, "r", encoding="utf-8") as f:
            return f.read()

    return "一致性检查报告尚未生成"


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path
