"""短剧生成工作流 — CLI 入口。

用法:
    uv run python main.py --input "参考资料/第01集.docx"
    uv run python main.py --episode-id 02 --episode-title "第二集"
    uv run python main.py --start-step step2_consistency
"""

import asyncio
import sys
import os
import argparse
from src.workflow import VideoWorkflow
from src.state import WorkflowState
from src.logger import get_logger, setup_logging

logger = get_logger("main")


def parse_args():
    p = argparse.ArgumentParser(description="🎬 短剧生成工作流")
    p.add_argument("--input", "-i", type=str, default="参考资料/第01集.docx", help="输入 Word 文档路径")
    p.add_argument("--episode-id", type=str, default="01", help="剧集编号 (如 01, 02)")
    p.add_argument("--episode-title", type=str, default="第01集", help="剧集标题")
    p.add_argument("--config", "-c", type=str, default=None, help="配置文件路径")
    p.add_argument("--start-step", "-s", type=str, default=None,
                   choices=["parse_docx", "generate_asset_package", "step1_storyboard",
                            "step2_consistency", "step3_optimize_prompts", "generate_videos", "merge_videos"],
                   help="从指定步骤开始执行")
    p.add_argument("--node-model", type=str, nargs="+", default=None,
                   help="覆盖节点模型: node:provider:model")
    return p.parse_args()


async def main():
    args = parse_args()

    input_path = args.input
    if not os.path.isabs(input_path):
        input_path = os.path.join(os.getcwd(), input_path)

    if not os.path.exists(input_path):
        logger.error("输入文件不存在: %s", input_path)
        sys.exit(1)

    setup_logging("INFO")

    print("=" * 60)
    print("🎬 短剧生成工作流")
    print("=" * 60)
    print(f"   输入: {input_path}")
    print(f"   剧集: {args.episode_id} - {args.episode_title}")
    print("=" * 60)

    workflow = VideoWorkflow(args.config)

    if args.node_model:
        for ov in args.node_model:
            parts = ov.split(":")
            if len(parts) >= 3:
                logger.info("覆盖模型: %s -> %s/%s", parts[0], parts[1], parts[2])
                workflow.get_config_manager().update_node_model(parts[0], parts[1], parts[2])
                workflow.get_model_manager().clear_cache()

    try:
        if args.start_step:
            logger.info("从步骤 %s 开始执行", args.start_step)
            final = await workflow.run_from_step(args.start_step, args.episode_id, args.episode_title, input_path)
        else:
            logger.info("运行完整工作流...")
            final = await workflow.run(args.episode_id, args.episode_title, input_path)

        _print_results(final)

    except Exception as e:
        logger.error("工作流执行失败: %s", e, exc_info=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)


def _print_results(state: WorkflowState):
    print()
    print("=" * 60)
    print("✅ 工作流完成!")
    print("=" * 60)
    print(f"   剧集: {state.get('episode_title', '未知')}")
    print(f"   错误: {len(state.get('errors', []))} 个")
    print()
    print("--- 执行步骤 ---")

    if state.get("script_content"):
        print(f"  [✓] 1. 解析剧本 — {len(state.get('script_content', ''))} 字")
    if state.get("assets_generated"):
        print(f"  [✓] 2. 资产包 — {len(state.get('character_assets', []))} 人物, "
              f"{len(state.get('scene_assets', []))} 场景, {len(state.get('prop_assets', []))} 道具")
    if state.get("step1_completed"):
        print(f"  [✓] 3. 分镜 — {len(state.get('shot_groups', []))} 组镜头")
    if state.get("step2_completed"):
        print(f"  [✓] 4. 一致性检查 — {len(state.get('consistency_anchors', []))} 锚点")
    if state.get("step3_completed"):
        total = sum(len(p.get("shots", [])) for p in state.get("optimized_prompts", []))
        print(f"  [✓] 5. 优化提示词 — {total} 个镜头")
    if state.get("videos_generated"):
        segs = state.get("video_segments", [])
        ok = sum(1 for s in segs if s.get("status") == "completed")
        print(f"  [✓] 6. 视频生成 — {ok}/{len(segs)} 片段")
    if state.get("videos_merged"):
        print(f"  [✓] 7. 视频合并 — {state.get('final_video_path', '')}")

    errors = state.get("errors", [])
    if errors:
        print(f"\n--- 错误 ({len(errors)}) ---")
        for e in errors:
            print(f"  - {e}")

    print("\n--- 输出文件 ---")
    for key, value in state.items():
        if isinstance(value, str) and (key.endswith("_path") or key.endswith("_dir")) and value:
            print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
