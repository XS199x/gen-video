"""路径契约的单元测试 —— 覆盖各种 OS 脏路径输入。"""
from src.paths import to_project_relative, normalize_state_paths

PID = "abc123"


def _check(inp, expected):
    got = to_project_relative(inp, PID)
    status = "OK " if got == expected else "FAIL"
    print(f"[{status}] {inp!r}\n       -> {got!r}  (expect {expected!r})")
    return got == expected


def main():
    cases = [
        # 上传：全反斜杠，无 ./
        ("outputs\\abc123\\资产\\char_0.png", "资产/char_0.png"),
        # 生成：./ 前缀 + 混斜杠
        ("./outputs\\abc123\\资产/人物/天兵甲.png", "资产/人物/天兵甲.png"),
        # 绝对 Windows 路径
        ("C:\\Users\\x\\Desktop\\gen-video\\outputs\\abc123\\视频\\seg_1.mp4", "视频/seg_1.mp4"),
        # 已是干净相对 posix（幂等）
        ("资产/char_0.png", "资产/char_0.png"),
        # posix 绝对路径
        ("/home/user/gen-video/outputs/abc123/final.mp4", "final.mp4"),
        # 无锚点的相对路径，兜底保留
        ("资产/人物/x.png", "资产/人物/x.png"),
        # 防穿越：.. 被丢弃
        ("outputs/abc123/../../etc/passwd", "etc/passwd"),
        # 空
        ("", ""),
        (None, ""),
        # 重复斜杠
        ("outputs//abc123//资产//a.png", "资产/a.png"),
    ]
    all_ok = True
    for inp, exp in cases:
        all_ok &= _check(inp, exp)

    # normalize_state_paths 整体
    state = {
        "character_assets": [{"image_path": "outputs\\abc123\\资产\\c0.png"}],
        "scene_assets": [{"image_path": "./outputs\\abc123\\资产/场景/s0.png"}],
        "prop_assets": [],
        "video_segments": [{"video_path": "C:\\g\\outputs\\abc123\\视频\\v1.mp4"}],
        "final_video_path": "outputs\\abc123\\final.mp4",
    }
    normalize_state_paths(state, PID)
    expect_state = {
        "character_assets": [{"image_path": "资产/c0.png"}],
        "scene_assets": [{"image_path": "资产/场景/s0.png"}],
        "video_segments": [{"video_path": "视频/v1.mp4"}],
        "final_video_path": "final.mp4",
    }
    ok_state = (
        state["character_assets"][0]["image_path"] == expect_state["character_assets"][0]["image_path"]
        and state["scene_assets"][0]["image_path"] == expect_state["scene_assets"][0]["image_path"]
        and state["video_segments"][0]["video_path"] == expect_state["video_segments"][0]["video_path"]
        and state["final_video_path"] == expect_state["final_video_path"]
    )
    print(f"[{'OK ' if ok_state else 'FAIL'}] normalize_state_paths 整体")
    all_ok &= ok_state

    print("\n=== ALL PASS ===" if all_ok else "\n=== HAS FAILURES ===")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
