"""
幂等可重入 —— 付费产物「最小生产单元」的续跑判定单一权威。

痛点背景：
    generate_videos / generate_asset_package 这类「批量生产型」节点，原先每次执行
    都从零重建全部单元并无差别地重新调用付费 API：
      - 8 个镜头第 5 个失败 → 重跑会把已成功的 1-4 号也重新烧钱生成一遍；
      - API 不可用时落 pending_upload 占位、用户手动上传了成果 → 全量重跑覆盖丢弃；
      - 失败恢复只能「全量重来」而非「断点续跑」。

契约（显式化）：
    本模块是「一个单元是否需要重跑 / 跳过 / 保留」的唯一判定来源。视频 segment、
    资产 image 都是「单元」——它们各带一个 status 和一个产物路径字段（path_key）。
    需要续跑判定的节点一律 import 这里的 partition_units，不再各写一份易漂移的逻辑。

判定模型：
    - skip    ：已完成且产物文件真实存在（信任状态位 + 文件存在性兜底）→ 不再调 API。
    - regen   ：failed / pending / processing，或 completed 但产物文件缺失 → 需重跑。
    - preserve：pending_upload（用户手动占位待上传）→ 保留不动，不覆盖手动成果。
    - force=True 逃生阀：除 preserve 外全部进 regen（显式全量重生成，如换风格）。
"""

import os
from typing import Any, Dict, List, Tuple

from .logger import get_logger

logger = get_logger("reentrancy")

# 用户手动占位、待上传的状态：这类单元永远保留，不被自动重跑覆盖。
PRESERVE_STATUS = "pending_upload"
# 「已完成」状态：配合产物存在性判定才算真正可跳过。
DONE_STATUS = "completed"


def artifact_exists(rel_path: Any, output_dir: str) -> bool:
    """产物文件是否真实存在。

    rel_path 是路径契约（src/paths.py）产出的「相对项目根的 posix 相对路径」，
    这里用 output_dir 还原为绝对路径后判存在性。空路径 → False。
    绝对路径（历史脏数据兜底）也直接判存在性。
    """
    if not rel_path:
        return False
    p = str(rel_path)
    full = p if os.path.isabs(p) else os.path.join(output_dir, p)
    return os.path.exists(full)


def is_unit_preserved(unit: Dict[str, Any]) -> bool:
    """单元是否应保留不动（用户手动占位待上传）。"""
    return (unit or {}).get("status") == PRESERVE_STATUS


def is_unit_done(unit: Dict[str, Any], path_key: str, output_dir: str) -> bool:
    """单元是否「已完成、可跳过」：status=='completed' 且产物文件真实存在。"""
    u = unit or {}
    if u.get("status") != DONE_STATUS:
        return False
    return artifact_exists(u.get(path_key), output_dir)


def partition_units(
    units: List[Dict[str, Any]],
    path_key: str,
    output_dir: str,
    force: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """把单元列表分成 (skip, regen, preserve) 三组。

    参数：
        units      ：单元列表（视频 segment 或资产 asset）。
        path_key   ：产物路径字段名，视频用 "video_path"，资产用 "image_path"。
        output_dir ：项目输出目录，用于还原相对路径判存在性。
        force      ：逃生阀。True 时除 preserve 外全部进 regen（显式全量重生成）。

    返回：
        (skip, regen, preserve)：保持原始顺序的三组引用（不复制、不改写单元）。
    """
    skip: List[Dict[str, Any]] = []
    regen: List[Dict[str, Any]] = []
    preserve: List[Dict[str, Any]] = []

    for unit in units or []:
        # pending_upload 永远保留，即便 force 也不覆盖用户手动成果。
        if is_unit_preserved(unit):
            preserve.append(unit)
            continue
        # force 逃生阀：其余单元一律重跑。
        if force:
            regen.append(unit)
            continue
        if is_unit_done(unit, path_key, output_dir):
            skip.append(unit)
        else:
            regen.append(unit)

    return skip, regen, preserve
