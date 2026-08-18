"""幂等可重入的单元测试 —— 覆盖 skip/regen/preserve 分流、force 逃生阀、产物存在性兜底。"""
import os
import tempfile

from src import reentrancy


def _check(label, got, expected):
    ok = got == expected
    print(f"[{'OK ' if ok else 'FAIL'}] {label}\n       -> {got!r}  (expect {expected!r})")
    return ok


def _ids(units):
    """取一组单元的 segment_id（测试数据用它当唯一标识），便于断言分组结果。"""
    return [u.get("segment_id") for u in units]


def main():
    all_ok = True

    # 用临时目录承载「真实存在」的产物文件
    with tempfile.TemporaryDirectory() as output_dir:
        # 造两个真实文件：视频/seg_done.mp4、视频/seg_stale.mp4
        vdir = os.path.join(output_dir, "视频")
        os.makedirs(vdir, exist_ok=True)
        done_rel = "视频/seg_done.mp4"
        with open(os.path.join(output_dir, done_rel), "w", encoding="utf-8") as f:
            f.write("x")

        # ─── artifact_exists ────────────────────────────────────────
        all_ok &= _check("artifact_exists(存在的相对路径)",
                         reentrancy.artifact_exists(done_rel, output_dir), True)
        all_ok &= _check("artifact_exists(不存在的相对路径)",
                         reentrancy.artifact_exists("视频/nope.mp4", output_dir), False)
        all_ok &= _check("artifact_exists(空路径)",
                         reentrancy.artifact_exists("", output_dir), False)
        all_ok &= _check("artifact_exists(None)",
                         reentrancy.artifact_exists(None, output_dir), False)

        # ─── is_unit_done：completed + 文件在才算 done ─────────────────
        done_unit = {"segment_id": "done", "status": "completed", "video_path": done_rel}
        stale_unit = {"segment_id": "stale", "status": "completed", "video_path": "视频/missing.mp4"}
        failed_unit = {"segment_id": "failed", "status": "failed", "video_path": None}
        pending_unit = {"segment_id": "pending", "status": "pending", "video_path": None}
        upload_unit = {"segment_id": "upload", "status": "pending_upload", "video_path": None}

        all_ok &= _check("is_unit_done(completed+文件在)",
                         reentrancy.is_unit_done(done_unit, "video_path", output_dir), True)
        all_ok &= _check("is_unit_done(completed+文件缺)",
                         reentrancy.is_unit_done(stale_unit, "video_path", output_dir), False)
        all_ok &= _check("is_unit_done(failed)",
                         reentrancy.is_unit_done(failed_unit, "video_path", output_dir), False)

        # ─── is_unit_preserved：仅 pending_upload ────────────────────
        all_ok &= _check("is_unit_preserved(pending_upload)",
                         reentrancy.is_unit_preserved(upload_unit), True)
        all_ok &= _check("is_unit_preserved(completed)",
                         reentrancy.is_unit_preserved(done_unit), False)
        all_ok &= _check("is_unit_preserved(failed)",
                         reentrancy.is_unit_preserved(failed_unit), False)

        # ─── partition_units：默认（force=False）三分流 ───────────────
        units = [done_unit, stale_unit, failed_unit, pending_unit, upload_unit]
        skip, regen, preserve = reentrancy.partition_units(units, "video_path", output_dir)
        all_ok &= _check("partition skip = [done]", _ids(skip), ["done"])
        all_ok &= _check("partition regen = [stale, failed, pending]",
                         _ids(regen), ["stale", "failed", "pending"])
        all_ok &= _check("partition preserve = [upload]", _ids(preserve), ["upload"])

        # ─── partition_units：force=True 逃生阀 ──────────────────────
        skipf, regenf, preservef = reentrancy.partition_units(
            units, "video_path", output_dir, force=True)
        all_ok &= _check("force skip 为空", _ids(skipf), [])
        all_ok &= _check("force regen = 除 preserve 外全部",
                         _ids(regenf), ["done", "stale", "failed", "pending"])
        all_ok &= _check("force preserve 仍保留 upload", _ids(preservef), ["upload"])

        # ─── 顺序保持 ────────────────────────────────────────────────
        # regen 组内部保持原始相对顺序
        all_ok &= _check("regen 组保持原始顺序", _ids(regen), ["stale", "failed", "pending"])

        # ─── 边界：空列表 / None ─────────────────────────────────────
        s0, r0, p0 = reentrancy.partition_units([], "video_path", output_dir)
        all_ok &= _check("空列表 → 三组皆空", (s0, r0, p0), ([], [], []))
        s1, r1, p1 = reentrancy.partition_units(None, "video_path", output_dir)
        all_ok &= _check("None → 三组皆空", (s1, r1, p1), ([], [], []))

        # ─── 资产场景：path_key='image_path' ─────────────────────────
        img_rel = "资产/人物/主角.png"
        adir = os.path.join(output_dir, "资产", "人物")
        os.makedirs(adir, exist_ok=True)
        with open(os.path.join(output_dir, img_rel), "w", encoding="utf-8") as f:
            f.write("img")
        asset_done = {"segment_id": "a_done", "status": "completed", "image_path": img_rel}
        asset_new = {"segment_id": "a_new", "status": "pending", "image_path": "资产/人物/新角色.png"}
        sa, ra, pa = reentrancy.partition_units(
            [asset_done, asset_new], "image_path", output_dir)
        all_ok &= _check("资产 skip = [a_done]", _ids(sa), ["a_done"])
        all_ok &= _check("资产 regen = [a_new]", _ids(ra), ["a_new"])

    print("\n=== ALL PASS ===" if all_ok else "\n=== HAS FAILURES ===")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
