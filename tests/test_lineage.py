"""数据血缘的单元测试 —— 覆盖字段映射、下游传播、付费边界。"""
from src import lineage


def _check(label, got, expected):
    ok = got == expected
    print(f"[{'OK ' if ok else 'FAIL'}] {label}\n       -> {got!r}  (expect {expected!r})")
    return ok


def main():
    all_ok = True

    # ─── field_to_step：字段路径 → 步骤 ─────────────────────────
    all_ok &= _check("field_to_step('optimized_prompts.0.shots.2.prompt')",
                     lineage.field_to_step("optimized_prompts.0.shots.2.prompt"),
                     "step3_optimize_prompts")
    all_ok &= _check("field_to_step('character_assets.0.description')",
                     lineage.field_to_step("character_assets.0.description"),
                     "generate_asset_package")
    all_ok &= _check("field_to_step('shot_groups')",
                     lineage.field_to_step("shot_groups"),
                     "step1_storyboard")
    all_ok &= _check("field_to_step('video_segments.1.video_path')",
                     lineage.field_to_step("video_segments.1.video_path"),
                     "generate_videos")
    all_ok &= _check("field_to_step('script_content')",
                     lineage.field_to_step("script_content"),
                     "parse_docx")
    # 未知字段 / 空 → None
    all_ok &= _check("field_to_step('unknown_field')",
                     lineage.field_to_step("unknown_field"), None)
    all_ok &= _check("field_to_step('')",
                     lineage.field_to_step(""), None)
    # 边界：不能被前缀歧义误匹配（scene_table 不应命中 scene_assets）
    all_ok &= _check("field_to_step('scene_table.0')",
                     lineage.field_to_step("scene_table.0"),
                     "step1_storyboard")

    # ─── downstream_steps：含自身+后续 ──────────────────────────
    all_ok &= _check("downstream_steps('step3_optimize_prompts')",
                     lineage.downstream_steps("step3_optimize_prompts"),
                     ["step3_optimize_prompts", "generate_videos", "merge_videos"])
    all_ok &= _check("downstream_steps('generate_videos')",
                     lineage.downstream_steps("generate_videos"),
                     ["generate_videos", "merge_videos"])
    all_ok &= _check("downstream_steps('merge_videos')",
                     lineage.downstream_steps("merge_videos"),
                     ["merge_videos"])
    all_ok &= _check("downstream_steps('parse_docx', include_self=False)",
                     lineage.downstream_steps("parse_docx", include_self=False),
                     ["generate_asset_package", "step1_storyboard", "step2_consistency",
                      "step3_optimize_prompts", "generate_videos", "merge_videos"])
    all_ok &= _check("downstream_steps('nope')",
                     lineage.downstream_steps("nope"), [])

    # ─── is_paid_step：付费边界 ─────────────────────────────────
    all_ok &= _check("is_paid_step('step3_optimize_prompts')  # 免费边界",
                     lineage.is_paid_step("step3_optimize_prompts"), False)
    all_ok &= _check("is_paid_step('generate_videos')  # 付费起点",
                     lineage.is_paid_step("generate_videos"), True)
    all_ok &= _check("is_paid_step('merge_videos')",
                     lineage.is_paid_step("merge_videos"), True)
    all_ok &= _check("is_paid_step('parse_docx')",
                     lineage.is_paid_step("parse_docx"), False)

    # ─── 常量自洽 ───────────────────────────────────────────────
    all_ok &= _check("PREVIEW_STEPS + GENERATE_STEPS == STEP_ORDER",
                     lineage.PREVIEW_STEPS + lineage.GENERATE_STEPS,
                     lineage.STEP_ORDER)
    all_ok &= _check("STEP_OUTPUT_FIELDS 覆盖全部步骤",
                     sorted(lineage.STEP_OUTPUT_FIELDS.keys()),
                     sorted(lineage.STEP_ORDER))
    all_ok &= _check("STEP_LABELS 覆盖全部步骤",
                     sorted(lineage.STEP_LABELS.keys()),
                     sorted(lineage.STEP_ORDER))

    print("\n=== ALL PASS ===" if all_ok else "\n=== HAS FAILURES ===")
    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
