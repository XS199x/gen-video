import os
import json
import subprocess
import shutil
from typing import Dict, Any, List
from datetime import datetime

from ..state import WorkflowState
from ..config_manager import ConfigManager
from ..model_manager import ModelManager
from ..prompt_manager import PromptManager
from ..logger import get_logger

logger = get_logger("nodes.merge_videos")


async def merge_videos_node(
    state: WorkflowState, config_manager: ConfigManager,
    model_manager: ModelManager = None, prompt_manager: PromptManager = None,
) -> WorkflowState:
    new_state = dict(state)
    new_state["current_node"] = "merge_videos"
    new_state.setdefault("errors", [])

    log_entry = {"node": "merge_videos", "start_time": datetime.now().isoformat(), "status": "running"}
    new_state["execution_log"].append(log_entry)

    try:
        output_dir = config_manager.get_output_dir(state.get("episode_id", "unknown"))
        videos_dir = state.get("video_output_dir") or os.path.join(output_dir, "视频")

        segments = state.get("video_segments", [])
        if not segments:
            sp = os.path.join(output_dir, "视频片段清单.json")
            if os.path.exists(sp):
                with open(sp, "r", encoding="utf-8") as f:
                    segments = json.load(f)
                logger.info("从文件加载视频片段: %s", sp)

        if not segments:
            segments = [{"segment_id": "fallback", "video_path": None, "status": "completed", "prompt": "回退片段"}]
            logger.warning("没有视频片段，使用回退")

        valid = [s for s in segments if s.get("status") == "completed"]
        if not valid:
            logger.warning("没有已完成的视频片段")
            valid = segments

        video_files = [s["video_path"] for s in valid if s.get("video_path") and os.path.exists(s["video_path"])]
        final_path = await _merge(video_files, valid, videos_dir, output_dir)

        manifest = {
            "episode_id": state.get("episode_id", ""),
            "episode_title": state.get("episode_title", ""),
            "final_video_path": final_path,
            "total": len(segments), "valid": len(valid),
            "segments": [{
                "id": s.get("segment_id"), "prompt": s.get("prompt", "")[:200],
                "status": s.get("status"), "path": s.get("video_path"),
            } for s in segments],
            "created_at": datetime.now().isoformat(),
        }
        mpath = os.path.join(output_dir, "输出清单.json")
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        new_state.update({
            "videos_merged": True, "final_video_path": final_path,
            "output_manifest_path": mpath, "total_segments": len(segments), "valid_segments_count": len(valid),
        })

        logger.info("视频合并完成: %d/%d 片段 -> %s", len(valid), len(segments), final_path)

        log_entry["status"] = "completed"
        log_entry["end_time"] = datetime.now().isoformat()
        log_entry["output"] = final_path
        log_entry["total"] = len(segments)
        log_entry["valid"] = len(valid)

    except Exception as e:
        logger.error("视频合并失败: %s", e, exc_info=True)
        new_state["errors"].append(f"merge_videos 错误: {str(e)}")
        log_entry["status"] = "failed"
        log_entry["error"] = str(e)
        log_entry["end_time"] = datetime.now().isoformat()

    new_state["updated_at"] = datetime.now().isoformat()
    return new_state


async def _merge(video_files, segments, videos_dir, output_dir):
    has_ff = False
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5, check=True)
        has_ff = True
    except Exception:
        pass

    if not has_ff:
        raise RuntimeError("未安装 ffmpeg，无法合并视频。请下载: https://ffmpeg.org/download.html")

    if not video_files:
        raise RuntimeError("没有可合并的视频文件，所有视频片段生成失败")

    if len(video_files) == 1:
        final = os.path.join(output_dir, "最终视频.mp4")
        shutil.copy2(video_files[0], final)
        logger.info("单个视频片段直接复制: %s", final)
        return final

    list_path = os.path.join(videos_dir, "视频合并列表.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for vf in video_files:
            f.write(f"file '{os.path.abspath(vf).replace(chr(92), '/')}'\n")

    final = os.path.join(output_dir, "最终视频.mp4")
    logger.info("运行 ffmpeg 合并 (%d 个文件)...", len(video_files))
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
           "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p", final]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode == 0 and os.path.exists(final):
        logger.info("最终视频: %s", final)
        return final
    err = r.stderr.decode(errors="replace")[:500] if r.stderr else "未知"
    raise RuntimeError(f"ffmpeg 合并失败: {err}")
