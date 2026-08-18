"""设计2 端到端行为验证（绕过 TestClient，直接调 pm/lineage/server 逻辑）。

验证两大核心行为：
  A. 标脏不清空 —— 编辑 step3 字段后，generate_videos/merge_videos 被标 stale，
     但 video_segments 产物仍在（不被物理清空）。
  B. 付费墙闸门 —— 复刻 server.run_step 的闸门判定：付费步骤 stale/有产物且未 confirm
     时应拦截并给出成本预估；带 confirm 时放行。

用完即删临时项目，不污染生产数据。
"""

import sys

from src.project_manager import ProjectManager
from src import lineage

pm = ProjectManager()

FAILS = []


def check(label, cond, extra=""):
    tag = "OK " if cond else "BAD"
    if not cond:
        FAILS.append(label)
    print(f"  [{tag}] {label}{('  ' + extra) if extra else ''}")


# ─── 准备临时项目 ────────────────────────────────────────────────
p = pm.create_project(name="__design2_verify__", episode_id="verify", episode_title="验证")
pid = p["id"]
print(f"临时项目: {pid}\n")

try:
    # 造一个「已生成到视频」的状态：optimized_prompts + video_segments 都有产物
    state = pm.load_state(pid)
    state["optimized_prompts"] = [
        {"group": "g1", "shots": [{"shot_id": "s1", "prompt": "旧提示词A"},
                                  {"shot_id": "s2", "prompt": "旧提示词B"}]},
    ]
    state["video_segments"] = [
        {"segment_id": "s1", "video_path": "视频/seg_s1.mp4"},
        {"segment_id": "s2", "video_path": "视频/seg_s2.mp4"},
    ]
    state["final_video_path"] = "视频/final.mp4"
    pm.save_state(pid, state)

    # 把 step3/generate_videos/merge_videos 都置为 completed（模拟已跑完付费步骤）
    for sn in ("step3_optimize_prompts", "generate_videos", "merge_videos"):
        pm.set_step_status(pid, sn, "completed")

    # ─── A. 标脏不清空 ───────────────────────────────────────────
    print("=== A. 编辑上游 → 标脏但保留产物 ===")
    pm.update_state_field(pid, "optimized_prompts.0.shots.0.prompt", "新提示词A", reset_downstream=True)

    st_vid = pm.get_step_status(pid, "generate_videos")
    st_merge = pm.get_step_status(pid, "merge_videos")
    st_step3 = pm.get_step_status(pid, "step3_optimize_prompts")
    check("step3 自身被标 stale", bool(st_step3 and st_step3.get("stale")))
    check("generate_videos 被标 stale", bool(st_vid and st_vid.get("stale")))
    check("merge_videos 被标 stale", bool(st_merge and st_merge.get("stale")))

    after = pm.load_state(pid)
    segs = after.get("video_segments") or []
    check("video_segments 产物仍在（未被清空）", len(segs) == 2,
          f"len={len(segs)}")
    check("video_segments 路径保留", segs and segs[0].get("video_path") == "视频/seg_s1.mp4",
          f"path={segs[0].get('video_path') if segs else None}")
    check("final_video_path 保留", after.get("final_video_path") == "视频/final.mp4")
    check("编辑内容已写入", after["optimized_prompts"][0]["shots"][0]["prompt"] == "新提示词A")

    # ─── B. 付费墙闸门判定 ───────────────────────────────────────
    print("\n=== B. 付费墙闸门（复刻 server.run_step 判定）===")

    def gate(step_name, confirm):
        """复刻 server.py run_step 中的闸门逻辑，返回 (拦截?, 预估或None)。"""
        if lineage.is_paid_step(step_name) and not confirm:
            st = pm.get_step_status(pid, step_name)
            is_stale = bool(st and st.get("stale"))
            has_output = bool(st and st.get("status") == "completed")
            if is_stale or has_output:
                return True, pm.estimate_cost(pid)
        return False, None

    blocked, est = gate("generate_videos", confirm=False)
    check("stale 付费步骤未确认 → 拦截", blocked)
    check("拦截时给出成本预估", bool(est and "estimated_cost" in est),
          f"est={est}")

    blocked2, _ = gate("generate_videos", confirm=True)
    check("带 confirm=True → 放行", not blocked2)

    # 免费步骤永不拦截
    blocked3, _ = gate("step3_optimize_prompts", confirm=False)
    check("免费步骤（step3）不走闸门", not blocked3)

    # ─── C. 重跑清脏 ─────────────────────────────────────────────
    print("\n=== C. 重跑成功 → 清脏 ===")
    pm.set_step_stale(pid, "generate_videos", stale=False)
    st_after = pm.get_step_status(pid, "generate_videos")
    check("set_step_stale(False) 后 stale=0", not bool(st_after and st_after.get("stale")))
    # 清脏后不再拦截
    blocked4, _ = gate("generate_videos", confirm=False)
    # 注意：status 仍是 completed（有产物）→ 仍会因 has_output 拦截，这是预期（覆盖确认）
    check("清脏但仍 completed → 因将覆盖仍拦截", blocked4)

finally:
    pm.delete_project(pid)
    print(f"\n已清理临时项目 {pid}")

print("\n=== ALL PASS ===" if not FAILS else f"\n=== {len(FAILS)} FAIL: {FAILS} ===")
sys.exit(1 if FAILS else 0)
