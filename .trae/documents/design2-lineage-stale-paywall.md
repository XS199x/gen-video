# 设计2：数据血缘 + 脏标记 + 付费墙闸门

## Context（为什么做这个改动）

当前系统在用户编辑上游产物后，用一套**隐式且暴力**的机制处理下游：

- `update_state_field`（[project_manager.py:446](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py#L446)）编辑上游字段后，**立即把所有下游步骤 `status='pending'` 且 `result_summary=''`**（物理清空下游状态）。用户改一个字，就丢掉已生成的视频/成片，无法「先看看再决定要不要重跑」。
- 血缘关系散落在**两处硬编码 map**——`_field_path_to_step`（[project_manager.py:515](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py#L515)）和 `clear_state_from_step`（[server.py:438](file:///c:/Users/Administrator/Desktop/gen-video/server.py#L438)），加上步骤常量在 **3 处重复定义**（`STEP_NAMES`/`STEP_ORDER`/前端 `STEP_DEFS`），易漂移。
- 脏标记是**字符串约定**：往 `result_summary` 拼 `[已编辑]`，前端靠 `.includes('[已编辑]')` 判断（[workflow.js:119](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L119)、[stepNav.js:31](file:///c:/Users/Administrator/Desktop/gen-video/web/js/components/stepNav.js#L31)），脆弱耦合。
- 付费步骤（`generate_videos`/`merge_videos`）在下游变脏时**无任何闸门**，用户可能盲目重跑烧钱，或拿到过期成片而不自知。

**目标**（本轮已与用户确认的三点决策）：
1. **标记为脏但保留**——编辑上游不再物理清空下游，改打结构化 `stale` 标记，产物和路径全部保留，直到用户显式重跑才覆盖。
2. **步骤级血缘**——用单一权威血缘表取代现有两处重复 map，编辑属于步骤 N 的字段 → N 及其所有下游步骤标脏。
3. **脏则拦截 + 提示重算成本**——付费步骤为 stale 时，`run` 端点返回「需确认」状态 + 成本预估（复用 `estimate_cost`），前端弹确认，用户确认后才真正执行并清脏。

**预期结果**：数据层有一份可信的「哪些步骤已过期」真相，前端能清晰展示 stale 徽标，付费重跑前有成本确认闸门，且不再手滑丢结果。

---

## 实现方案

### 1. 单一血缘权威：`src/lineage.py`（新建）

把「步骤顺序 / 标签 / 免费付费切分 / 字段→步骤映射」收口到一个模块，供后端各处 import，消除重复常量与两处 map 漂移。

```python
# 步骤线性血缘（唯一权威，取代 STEP_NAMES / STEP_ORDER）
STEP_ORDER = ["parse_docx", "generate_asset_package", "step1_storyboard",
              "step2_consistency", "step3_optimize_prompts", "generate_videos", "merge_videos"]
STEP_LABELS = { ... }                 # 取代 STEP_LABELS / NODE_NAMES
PREVIEW_STEPS = STEP_ORDER[:5]        # 免费
GENERATE_STEPS = STEP_ORDER[5:]       # 付费（generate_videos / merge_videos）

# 字段前缀 → 步骤（取代 _field_path_to_step 的内联 map）
FIELD_TO_STEP = {
    "script_content": "parse_docx", "parsed_characters": "parse_docx", ...
    "character_assets": "generate_asset_package", ...
    "optimized_prompts": "step3_optimize_prompts", "video_segments": "generate_videos", ...
}

# 步骤 → 该步产出的 state 字段（取代 clear_state_from_step 的 clear_map）
STEP_OUTPUT_FIELDS = {
    "parse_docx": ["script_content", "structured_script", "parsed_characters", ...],
    "generate_asset_package": ["assets_generated", "character_assets", ...],
    ...
}

def field_to_step(field_path: str) -> str | None:   # 前缀匹配
def downstream_steps(step_name: str) -> list[str]:   # 含自身之后的所有步骤
def is_paid_step(step_name: str) -> bool:            # step in GENERATE_STEPS
```

`project_manager.py` 和 `server.py` 改为从 `src.lineage` import 这些常量与函数，删除各自的内联副本。`workflow.py` 的 `STEP_ORDER`/`NODE_NAMES` 也改为复用（保留 `NODE_FUNCS` 因它是节点函数映射，属 workflow 职责）。

### 2. 结构化脏标记：`project_steps` 表增列 `stale`

给步骤状态表加一个显式布尔列，取代 `result_summary` 里的 `[已编辑]` 字符串约定。

- **建表**：[project_manager.py:92](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py#L92) `CREATE TABLE project_steps` 增 `stale INTEGER NOT NULL DEFAULT 0`。
- **幂等迁移**：`_init_db` 里加 `ALTER TABLE project_steps ADD COLUMN stale ...`，用 `PRAGMA table_info` 检查列是否已存在，避免重复建列报错（现有 DB 有 2 个项目需平滑升级）。
- **新方法** `set_step_stale(project_id, step_name, stale: bool)`：单步置脏/清脏。
- `get_step_status` / `list_projects`（[project_manager.py:166](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py#L166)）返回的 step dict 自然带上 `stale` 列。

### 3. 编辑上游：标脏不清空（核心行为反转）

改写 `update_state_field`（[project_manager.py:446](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py#L446)）的 `reset_downstream=True` 分支：

- **旧**：把下游步骤 `status='pending'` + `result_summary=''`（物理清空）。
- **新**：调用 `lineage.field_to_step(field_path)` 定位当前步骤 → 对「当前步骤及其所有下游步骤」调 `set_step_stale(..., True)`，**保留 status 与产物**。仅当前被编辑步骤自身也标脏（表示「内容已改，与已生成结果不一致」）。
- `reset_downstream=False`（拖拽排序等纯顺序调整）维持不标脏。
- `redo_step`（[server.py:350](file:///c:/Users/Administrator/Desktop/gen-video/server.py#L350)）保持物理清空语义不变（这是用户**显式重跑**，理应清空），但补一步：重跑成功后对该步及下游 `set_step_stale(False)` 清脏。同理 `_execute_step` 成功完成（[server.py:322](file:///c:/Users/Administrator/Desktop/gen-video/server.py#L322)）时清自身 stale。

### 4. 付费墙闸门：stale 付费步骤拦截 + 成本预估

改写 `run_step` 端点（[server.py:245](file:///c:/Users/Administrator/Desktop/gen-video/server.py#L245)）：

- 新增可选查询参数 `confirm: bool = False`。
- 当 `lineage.is_paid_step(step_name)` 且（该步 stale **或** 已有产物将被覆盖）且 `confirm=False` 时，**不执行**，返回 `409` + body：
  ```json
  { "need_confirm": true, "step": "generate_videos", "reason": "stale",
    "estimate": { "shot_count": 8, "estimated_cost": "¥24.00", ... } }
  ```
  `estimate` 直接复用 `pm.estimate_cost(project_id)`（[project_manager.py:700](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py#L700)）。
- `confirm=True` 时正常走后台执行；执行成功清脏（见 §3）。
- 免费步骤（PREVIEW_STEPS）不受闸门影响，行为不变。

### 5. 前端：结构化 stale 徽标 + 付费确认弹窗

- **stale 来源改结构化**：[workflow.js:119](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L119) 的 `edited: summary.includes('[已编辑]')` 改为读 `info.stale`（`stepStatusMap` [workflow.js:102](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L102) 增 `stale: s.stale`）。徽标文案从「✏️ 已修改」升级为「⚠️ 已过期，需重跑」（stale 语义比「已编辑」更准）。[stepNav.js:31](file:///c:/Users/Administrator/Desktop/gen-video/web/js/components/stepNav.js#L31) 对应更新。
- **付费确认弹窗**：`runStep`（[workflow.js:644](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L644)）捕获 `409 need_confirm`，用现有 Modal 组件弹出成本预估（「本次将生成 8 个镜头，预计花费 ¥24.00，确认继续？」），确认后带 `?confirm=true` 重发。复用 [api.js](file:///c:/Users/Administrator/Desktop/gen-video/web/js/api.js) 的 `runStep`，签名加可选 `confirm` 参数。
- **版本 bump**：[index.html](file:///c:/Users/Administrator/Desktop/gen-video/web/index.html) `?v=9` → `?v=10`（15 处）。

### 6. 一次性迁移脚本：`scripts/migrate_lineage_stale.py`（新建）

- 建 `stale` 列后（由 `_init_db` 幂等处理），把历史 `result_summary` 里含 `[已编辑]` 的步骤回填为 `stale=1`，并清掉字符串后缀，完成从「字符串约定」到「结构化列」的数据迁移。
- 遵循上轮迁移脚本范式（[scripts/migrate_normalize_paths.py](file:///c:/Users/Administrator/Desktop/gen-video/scripts/migrate_normalize_paths.py)）：`--dry` 预览 + 执行后校验。

---

## 涉及文件

| 动作 | 文件 |
|---|---|
| 新建 | [src/lineage.py](file:///c:/Users/Administrator/Desktop/gen-video/src/lineage.py) — 血缘单一权威 |
| 新建 | [tests/test_lineage.py](file:///c:/Users/Administrator/Desktop/gen-video/tests/test_lineage.py) — 血缘/传播单测 |
| 新建 | [scripts/migrate_lineage_stale.py](file:///c:/Users/Administrator/Desktop/gen-video/scripts/migrate_lineage_stale.py) — 历史脏标记迁移 |
| 改 | [src/project_manager.py](file:///c:/Users/Administrator/Desktop/gen-video/src/project_manager.py) — 增 stale 列/迁移/set_step_stale；改 update_state_field 标脏不清空；import lineage 删重复常量 |
| 改 | [server.py](file:///c:/Users/Administrator/Desktop/gen-video/server.py) — run_step 付费墙闸门；redo/execute 清脏；clear_state_from_step 复用 lineage |
| 改 | [src/workflow.py](file:///c:/Users/Administrator/Desktop/gen-video/src/workflow.py) — 复用 lineage 常量 |
| 改 | [web/js/views/workflow.js](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js) — stale 结构化 + 付费确认弹窗 |
| 改 | [web/js/components/stepNav.js](file:///c:/Users/Administrator/Desktop/gen-video/web/js/components/stepNav.js) — 徽标文案 |
| 改 | [web/js/api.js](file:///c:/Users/Administrator/Desktop/gen-video/web/js/api.js) — runStep 加 confirm 参数 |
| 改 | [web/index.html](file:///c:/Users/Administrator/Desktop/gen-video/web/index.html) — v9→v10 |

---

## 验证

1. **单测**：`python -m tests.test_lineage`（cwd=项目根）——校验 `field_to_step` 前缀映射、`downstream_steps` 含自身+后续、`is_paid_step` 边界（step3 免费/generate_videos 付费）。目标 `=== ALL PASS ===`。
2. **迁移**：`python -m scripts.migrate_lineage_stale --dry` 预览 → 执行 → 查 DB 确认 `stale` 列回填正确、`[已编辑]` 字符串已清。
3. **标脏不清空**（后端级，用 TestClient 或直接调 pm）：对已完成 step3 的项目编辑 `optimized_prompts.0.shots.0.prompt` → 断言 `generate_videos`/`merge_videos` 的 `stale=1` 且 `video_segments` 产物**仍在**（未被清空）。
4. **付费墙**：对 stale 的 `generate_videos` 调 `POST .../steps/generate_videos/run`（不带 confirm）→ 断言返回 409 + `need_confirm` + `estimate.estimated_cost`；带 `?confirm=true` 重发 → 正常进入 running 并在完成后 `stale=0`。
5. **前端**（浏览器，工具恢复可用时）：编辑上游 → rail 出现「⚠️ 已过期」徽标（下游产物仍可见）；点付费步骤生成 → 弹成本确认框；确认后徽标消失。若浏览器工具不稳，用 DOM 断言替代截图。

> 注：探查发现 `python-multipart` 未安装会导致 TestClient 无法加载整个 app。若验证步骤 3/4 需要 TestClient，可先 `pip install python-multipart`；否则用直接调用 `pm` 方法 + 独立小脚本的等价验证（参考上轮设计1的验证方式）。
