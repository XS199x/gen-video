"""设计3 端到端行为验证 —— 幂等可重入续跑（不花钱、不依赖 ffmpeg/真实配置）。

用一个轻量 fake config_manager（provider=mock）+ monkeypatch 掉真正的 mock 出图函数
（改为「只记录收到哪些 segment 并给它们建占位文件」），直接调用 generate_videos_node，
验证四类行为：

  A. 增量续跑（force=false）：
     - completed+文件在 → 跳过（不进 provider、文件 mtime 不变）
     - failed / pending → 被补跑（进 provider、拿到产物）
     - pending_upload   → 保留不动（不进 provider、状态与占位保留）
  B. force 逃生阀（force=true）：除 pending_upload 外全部重跑。
  C. 资产续跑：_backfill + partition 让已出图资产跳过、新资产补跑。

用临时目录承载产物，用完即删。
"""

import asyncio
import os
import sys
import tempfile
import time

from src.nodes import generate_videos as gv
from src.nodes import generate_asset_package as gap

FAILS = []


def check(label, cond, extra=""):
    tag = "OK " if cond else "BAD"
    if not cond:
        FAILS.append(label)
    print(f"  [{tag}] {label}{('  ' + extra) if extra else ''}")


class FakeCM:
    """最小 config_manager：只提供节点需要的两个方法。"""
    def __init__(self, output_dir):
        self._out = output_dir

    def get_output_dir(self, episode_id):
        return self._out

    def get_node_config(self, node_name):
        return {"video_provider": "mock", "video_model": "mock-v1"}

    def get_image_config(self):
        return None  # 资产验证单独构造


def _make_prompts(n):
    """构造 n 个镜头，segment_id 会是 seg_0_0 .. seg_0_{n-1}。"""
    return [{"group_name": "g0", "shots": [
        {"prompt": f"镜头{i}", "shot_name": i} for i in range(n)
    ]}]


async def verify_videos():
    print("=== A/B. 视频续跑 + force 逃生阀 ===")
    with tempfile.TemporaryDirectory() as output_dir:
        cm = FakeCM(output_dir)
        videos_dir = os.path.join(output_dir, "视频")
        os.makedirs(videos_dir, exist_ok=True)

        # 造一个 completed 片段的真实产物文件（seg_0_0）
        done_abs = os.path.join(videos_dir, "seg_0_0.mp4")
        with open(done_abs, "w", encoding="utf-8") as f:
            f.write("done-original")
        done_mtime = os.path.getmtime(done_abs)

        # monkeypatch mock 出图：只记录收到哪些 segment，并给它们建文件+标 completed
        called = {"ids": None}

        async def fake_mock(segments, vdir):
            called["ids"] = [s["segment_id"] for s in segments]
            for s in segments:
                p = os.path.join(vdir, f"{s['segment_id']}.mp4")
                with open(p, "w", encoding="utf-8") as fp:
                    fp.write("regen")
                s["video_path"] = p
                s["status"] = "completed"
            return segments

        orig = gv._generate_mock_videos
        gv._generate_mock_videos = fake_mock
        try:
            # 已有 4 个片段：completed+文件在 / failed / pending_upload / (缺 seg_0_3 由 fresh 补)
            existing = [
                {"segment_id": "seg_0_0", "status": "completed", "video_path": "视频/seg_0_0.mp4", "prompt": "旧0"},
                {"segment_id": "seg_0_1", "status": "failed", "video_path": None, "prompt": "旧1", "error": "旧错误"},
                {"segment_id": "seg_0_2", "status": "pending_upload", "video_path": None, "prompt": "旧2"},
            ]
            state = {
                "episode_id": "verify3",
                "optimized_prompts": _make_prompts(4),  # seg_0_0..seg_0_3
                "video_segments": existing,
                "execution_log": [],
            }

            # 让 to_project_relative 能识别锚点：episode_id 用 output_dir 末段
            state["episode_id"] = os.path.basename(output_dir)
            cm._out = output_dir

            # 时间戳分辨率兜底
            time.sleep(0.02)

            # ── A. force=false 增量续跑 ──
            res = await gv.generate_videos_node(state, cm, None, None)
            segs = {s["segment_id"]: s for s in res["video_segments"]}

            check("provider 只收到未完成的 (seg_0_1, seg_0_3)",
                  sorted(called["ids"] or []) == ["seg_0_1", "seg_0_3"],
                  f"called={called['ids']}")
            check("seg_0_0 completed 未被重发（mtime 不变）",
                  os.path.getmtime(done_abs) == done_mtime)
            check("seg_0_0 状态仍 completed", segs["seg_0_0"]["status"] == "completed")
            check("seg_0_1 被补跑 → completed", segs["seg_0_1"]["status"] == "completed")
            check("seg_0_2 pending_upload 保留不动", segs["seg_0_2"]["status"] == "pending_upload")
            check("seg_0_3 新镜头被补跑 → completed", segs["seg_0_3"]["status"] == "completed")
            check("合并后共 4 个片段（保持顺序）",
                  [s["segment_id"] for s in res["video_segments"]] ==
                  ["seg_0_0", "seg_0_1", "seg_0_2", "seg_0_3"])
            check("_force_regenerate 未泄漏进 state", "_force_regenerate" not in res)

            # ── B. force=true 逃生阀 ──
            called["ids"] = None
            state2 = {
                "episode_id": os.path.basename(output_dir),
                "optimized_prompts": _make_prompts(4),
                "video_segments": res["video_segments"],  # 现在 3 completed + 1 preserve
                "execution_log": [],
                "_force_regenerate": True,
            }
            res2 = await gv.generate_videos_node(state2, cm, None, None)
            check("force=true 时除 pending_upload 外全部重跑",
                  sorted(called["ids"] or []) == ["seg_0_0", "seg_0_1", "seg_0_3"],
                  f"called={called['ids']}")
            segs2 = {s["segment_id"]: s for s in res2["video_segments"]}
            check("force 下 pending_upload 仍保留", segs2["seg_0_2"]["status"] == "pending_upload")
        finally:
            gv._generate_mock_videos = orig


def verify_assets():
    print("\n=== C. 资产图片续跑（回填 + 分流）===")
    with tempfile.TemporaryDirectory() as output_dir:
        pid = os.path.basename(output_dir)
        # 造一个已出图资产的真实文件
        adir = os.path.join(output_dir, "资产", "人物")
        os.makedirs(adir, exist_ok=True)
        img_rel = "资产/人物/主角.png"
        with open(os.path.join(output_dir, img_rel), "w", encoding="utf-8") as f:
            f.write("img")

        # 上一轮 state：主角已 generated，配角未出图
        prev_state = {
            "character_assets": [
                {"name": "主角", "category": "character", "image_path": img_rel,
                 "image_generated": True, "image_status": "generated"},
                {"name": "配角", "category": "character", "image_path": "资产/人物/配角.png",
                 "image_generated": False, "image_status": "failed"},
            ],
            "scene_assets": [], "prop_assets": [],
        }
        # 本轮 LLM 重新生成的资产（同名 → 应回填）
        this_round = [
            {"name": "主角", "category": "character", "prompt": "主角", "image_path": "资产/人物/主角.png"},
            {"name": "配角", "category": "character", "prompt": "配角", "image_path": "资产/人物/配角.png"},
            {"name": "新角色", "category": "character", "prompt": "新", "image_path": "资产/人物/新角色.png"},
        ]

        gap._backfill_asset_images(this_round, prev_state)
        by_name = {a["name"]: a for a in this_round}
        check("主角 回填到 image_status=generated",
              by_name["主角"].get("image_status") == "generated")
        check("配角 回填到 image_status=failed",
              by_name["配角"].get("image_status") == "failed")
        check("新角色 无回填（新资产）", "image_status" not in by_name["新角色"])

        # 归一化 + 分流（复刻节点内的判定）
        for a in this_round:
            a["status"] = gap._norm_status(a.get("image_status"))
        from src import reentrancy
        skip, regen, _ = reentrancy.partition_units(this_round, "image_path", output_dir)
        skip_names = [a["name"] for a in skip]
        regen_names = [a["name"] for a in regen]
        check("主角（已出图+文件在）→ skip", skip_names == ["主角"], f"skip={skip_names}")
        check("配角(failed)+新角色 → regen",
              sorted(regen_names) == ["新角色", "配角"], f"regen={regen_names}")


def main():
    asyncio.run(verify_videos())
    verify_assets()
    print("\n=== ALL PASS ===" if not FAILS else f"\n=== {len(FAILS)} FAIL: {FAILS} ===")
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
