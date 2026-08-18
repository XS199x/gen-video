"""
路径契约 —— 项目产物路径的单一权威。

痛点背景：
    后端把落盘文件的 OS 原始路径（Windows 反斜杠、绝对路径、混斜杠、./ 前缀）
    直接写进 state，前端再各自猜着解析成 HTTP URL。这个"隐式契约"一旦 OS
    差异介入就击穿下游（图片/视频裂图）。

契约（显式化）：
    所有需要暴露给前端渲染的产物路径（image_path / video_path / final_video_path
    等），在写入 state 之前，一律经 `to_project_relative()` 规范化为
    「相对 outputs/{project_id}/ 的 posix 相对路径」，例如：

        C:\\...\\outputs\\abc\\资产\\char_0.png   → 资产/char_0.png
        ./outputs\\abc\\资产/人物/x.png            → 资产/人物/x.png
        资产/char_0.png                             → 资产/char_0.png（幂等）

    前端 fileUrl 只做纯拼接：/api/projects/{id}/files/{相对posix路径}
"""

from pathlib import PurePosixPath, PureWindowsPath
import re

# 输出根目录名（与 config_manager.output_base_dir 的末段一致）
OUTPUTS_DIRNAME = "outputs"


def _to_posix(path: str) -> str:
    """把任意 OS 路径字符串统一成正斜杠、去掉 ./ 前缀（不触碰文件系统）。"""
    if not path:
        return ""
    # 统一分隔符：反斜杠 → 正斜杠
    s = str(path).replace("\\", "/")
    # 去掉重复斜杠与开头的 ./
    s = re.sub(r"/+", "/", s)
    s = re.sub(r"^\./", "", s)
    return s


def to_project_relative(path: str, project_id: str) -> str:
    """
    把任意产物路径规范化为「相对 outputs/{project_id}/ 的 posix 相对路径」。

    幂等：已经是干净相对路径的输入原样返回。
    兜底：找不到 outputs/{project_id}/ 锚点时，退化为去掉盘符/前导斜杠的 posix 路径，
         保证结果始终是安全的相对路径（不含 .. 穿越、不含盘符）。
    """
    if not path:
        return ""

    posix = _to_posix(path)

    # 优先按 outputs/{project_id}/ 锚点截断（大小写敏感，路径本就区分）
    anchor = f"{OUTPUTS_DIRNAME}/{project_id}/"
    idx = posix.find(anchor)
    if idx >= 0:
        rel = posix[idx + len(anchor):]
    else:
        # 兜底：可能是已规范化的相对路径，或无法识别锚点的路径。
        # 去掉可能的盘符（c:/...）与前导斜杠，剥掉可能残留的 outputs/ 前缀。
        rel = re.sub(r"^[a-zA-Z]:/", "", posix)
        rel = rel.lstrip("/")
        # 若仍以 outputs/{project_id} 开头但缺尾斜杠等边界情况，再尝试一次宽松剥离
        loose = f"{OUTPUTS_DIRNAME}/{project_id}"
        if rel == loose or rel.startswith(loose + "/"):
            rel = rel[len(loose):].lstrip("/")

    # 归一化并防穿越：丢弃任何 .. 段
    parts = [p for p in PurePosixPath(rel).parts if p not in ("", ".", "..")]
    return "/".join(parts)


def normalize_state_paths(state: dict, project_id: str) -> dict:
    """
    就地规范化 state 中所有「前端消费的产物路径」字段。
    只处理 A 类（会被 fileUrl 渲染的）路径，不触碰后端内部读取用的路径。

    返回同一个 state 对象（就地修改），便于链式调用。
    """
    if not state:
        return state

    # 资产图片：character_assets / scene_assets / prop_assets 里的 image_path
    for cat in ("character_assets", "scene_assets", "prop_assets"):
        for asset in state.get(cat, []) or []:
            ip = asset.get("image_path")
            if ip:
                asset["image_path"] = to_project_relative(ip, project_id)

    # 视频片段：video_segments 里的 video_path
    for seg in state.get("video_segments", []) or []:
        vp = seg.get("video_path")
        if vp:
            seg["video_path"] = to_project_relative(vp, project_id)

    # 最终成片
    fv = state.get("final_video_path")
    if fv:
        state["final_video_path"] = to_project_relative(fv, project_id)

    return state
