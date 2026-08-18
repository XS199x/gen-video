# 设计3：幂等可重入单元

## Context（为什么做这个改动）

前两个设计解决了「路径契约」（设计1）和「数据血缘 + 脏标记 + 付费墙」（设计2）。设计2 让编辑上游不再物理清空下游、付费步骤重跑前弹成本确认。但**「确认之后真正执行」的那一步仍是全量重跑**，这是当前最烧钱、最易丢数据的痛点：

- **付费重复消耗**：[generate_videos.py](file:///c:/Users/Administrator/Desktop/gen-video/src/nodes/generate_videos.py#L52) 每次执行都 `_build_segments(prompts)` 从零重建全部 segment，然后**无差别重新提交给 Kling**。生成 8 个镜头、第 5 个失败，重跑会把已成功的 1-4 号也重新花钱生成一遍。
- **覆盖用户手动成果**：视频/图片 API 不可用时会落 `pending_upload` 占位，用户手动上传了视频/图片；全量重跑会把这些手动成果一并覆盖丢弃（见 [_make_placeholder_segments](file:///c:/Users/Administrator/Desktop/gen-video/src/nodes/generate_videos.py#L114)、[generate_asset_package.py](file:///c:/Users/Administrator/Desktop/gen-video/src/nodes/generate_asset_package.py#L160-L190)）。
- **失败恢复是「全量重来」而非「断点续跑」**：一个片段失败就得整批重发，长任务的鲁棒性差。

**目标**：把「付费产物的最小生产单元」（视频 segment、资产 image）做成**幂等可重入**——重跑时已完成且产物真实存在的单元跳过，只补跑未完成的；保留用户手动上传的成果；并提供 `force` 逃生阀支持显式全量重生成。

## 决策（已与用户确认）

1. **保留判定 = 产物存在即跳过**：`status=='completed'` 且 `video_path`/`image_path` 指向的文件在磁盘上真实存在，才算「已完成、可跳过」。既信任状态位，又用文件存在性兜底，防止状态与磁盘不一致时误跳过。
2. **只补跑未完成的**：`completed`（且产物在）跳过；`failed`/`pending`/`processing` 重发；`pending_upload`（用户占位待上传）**保留不动**，不覆盖手动成果。
3. **force 逃生阀**：默认增量续跑；`force=true` 时忽略幂等、全部重跑（用户换风格等场景）。付费步骤走 `force` 时仍先过设计2 的付费墙确认。

## 方案

### 核心思路
在三个「批量生产型」节点里，把「从零构建 + 全量执行」改为「**载入已有单元 → 按保留判定分流（跳过/补跑/保留）→ 只对需补跑的调用付费 API → 合并结果**」。判定逻辑抽成可复用工具，避免三处各写一份漂移。

### 1. 新建 `src/reentrancy.py`（幂等可重入的单一权威）
参照 [lineage.py](file:///c:/Users/Administrator/Desktop/gen-video/src/lineage.py) 的「单一权威」范式，集中判定逻辑：

```python
def artifact_exists(rel_path, output_dir) -> bool:
    """产物文件是否真实存在（rel_path 是路径契约的相对 posix 路径）。"""
    # 空路径 → False；用 output_dir 还原绝对路径后 os.path.exists

def is_unit_done(unit, path_key, output_dir) -> bool:
    """单元是否「已完成、可跳过」：status=='completed' 且 artifact_exists。"""

def is_unit_preserved(unit) -> bool:
    """单元是否应保留不动：status=='pending_upload'（用户手动占位）。"""

def partition_units(units, path_key, output_dir, force=False):
    """把单元分成 (skip, regen, preserve) 三组。
       force=True 时除 preserve 外全部进 regen（逃生阀）。
       返回可直接用于日志和执行的三元组。"""
```
- `path_key`：视频用 `"video_path"`，资产用 `"image_path"`。
- 附单测 `tests/test_reentrancy.py`（沿用 `test_lineage.py` 的纯函数断言风格）：覆盖 completed+文件在→skip、completed+文件缺→regen、failed→regen、pending_upload→preserve、force→全 regen（preserve 除外）、空列表等边界。

### 2. 改 `generate_videos_node` 支持续跑（[generate_videos.py](file:///c:/Users/Administrator/Desktop/gen-video/src/nodes/generate_videos.py#L52-L78)）
- 用 `state.get("video_segments")` 里已有的单元与 `_build_segments(prompts)` 新建的**按 `segment_id` 对齐 merge**：已有单元优先保留其状态/产物，新增镜头补进来。
- `reentrancy.partition_units(segments, "video_path", output_dir, force)` 分流：
  - `skip`：直接留用，不进 API。
  - `regen`：清掉旧 `task_id`/`error` 后，仅把这批传给 `_generate_via_kling/runway/mock`。
  - `preserve`：原样保留。
- 执行完 `regen` 后，把三组按 `segment_id` 合并回完整 `segments` 列表再入 state（保持顺序）。
- `force` 从 `state.get("_force_regenerate", False)` 读取（见 §4 传参通路）。
- 日志明确打印 `跳过 N / 补跑 M / 保留 K`，让省钱效果可见。

### 3. 改 `generate_asset_package_node` 支持续跑（[generate_asset_package.py](file:///c:/Users/Administrator/Desktop/gen-video/src/nodes/generate_asset_package.py#L150-L190)）
- **难点**：该节点每次都先调 LLM 重新生成资产**描述**（characters/scenes/props 文本），再逐张出图。续跑要区分「文本重算」和「图片重生成」两层。
- 方案（保守、低风险）：LLM 文本生成保持不变（预览步骤、有 LLMCache 兜底、不付费）；**只在「图片生成」这一付费/耗时环节做幂等**——出图前对 `all_assets` 用 `partition_units(..., "image_path", output_dir, force)` 分流，`skip` 的资产不再调 `image_generator.generate_batch`，只对 `regen` 的出图。
- 注意对齐：LLM 每次可能生成略不同的资产名 → 用 `name+category` 作为对齐键，把上一轮 state 里已有图的资产 `image_path`/`image_status` 回填到本轮同名资产上，再做存在性判定。名字变了的视为新资产（regen）。

### 4. force 参数传参通路（server → workflow → node）
不改 node 函数签名（避免动 langgraph 包装），用 **state 临时控制字段**承载：
- [run_step 端点](file:///c:/Users/Administrator/Desktop/gen-video/server.py#L246-L247)：签名加 `force: bool = False`；付费墙判定后、执行前，把 `force` 透传给 `_execute_step`。
- [_execute_step](file:///c:/Users/Administrator/Desktop/gen-video/server.py#L312)：加载 state 后设 `state["_force_regenerate"] = force`，节点读取后即用。
- `state.py`：`_force_regenerate` 是运行时临时字段，**不加入 `create_initial_state`、不参与产物语义**；节点入口读完可 `pop`，避免持久化污染 state（`state_to_dict` 落库时若残留仅是布尔值，无害，但仍在节点内 pop 更干净）。
- `merge_videos` 本身是幂等的（读已完成 segment 合并），不需要 force，跳过。

### 5. 前端：force 入口 + runStep 透传（低改动）
- [api.js runStep](file:///c:/Users/Administrator/Desktop/gen-video/web/js/api.js#L49)：签名加 `force = false`，拼进 query（`?confirm=true&force=true`）。
- [workflow.js runStep](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L647)：付费确认弹窗里增加「强制全部重新生成」提示语；`redoStep`（[workflow.js:722](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L722)）语义本就是「清空重来」，让它走 `force=true` 保持一致。
- 视频生成面板 completed 态（[renderVideoGen](file:///c:/Users/Administrator/Desktop/gen-video/src/nodes/generate_videos.py) 对应前端 [workflow.js:797-805](file:///c:/Users/Administrator/Desktop/gen-video/web/js/views/workflow.js#L797-L805)）：把 header 的「🔄 重做」区分为「▶ 补跑未完成」（增量，force=false）和「🔁 全部重生成」（force=true），让省钱路径成为默认。
- `index.html` 版本 bump `?v=10 → ?v=11`（15 处）。

### 6. 不做的事（划定边界）
- 不引入外部任务队列/持久化框架（那是设计4：长任务持久化）。
- 不改 LLM 文本缓存机制（cache.py 已够用）。
- 不动预览步骤（parse/step1-3）的执行——它们不付费、无产物级幂等需求。

## 涉及文件
- 新增：`src/reentrancy.py`、`tests/test_reentrancy.py`
- 改：`src/nodes/generate_videos.py`、`src/nodes/generate_asset_package.py`、`server.py`（run_step/_execute_step 加 force）、`web/js/api.js`、`web/js/views/workflow.js`、`web/index.html`
- 可能微调：`src/state.py`（注释说明 `_force_regenerate` 为运行时临时字段，不入 initial state）

## 验证
1. **单测**：`python -m tests.test_reentrancy` 全过；回归 `python -m tests.test_lineage`、`python -m tests.test_paths`。
2. **续跑幂等（mock provider，不花钱）**：构造 4 个 segment（2 completed+文件在、1 failed、1 pending_upload），跑 generate_videos → 断言 completed 未被重发（文件 mtime 不变）、failed 被补跑、pending_upload 保留。写成 `scripts/verify_design3.py`（沿用 [verify_design2.py](file:///c:/Users/Administrator/Desktop/gen-video/scripts/verify_design2.py) 的临时项目 + 用完即删范式）。
3. **force 逃生阀**：同数据集带 `force=true` → 断言除 pending_upload 外全部重跑。
4. **资产续跑**：已有图的资产（image_path 文件在）→ 出图分流 skip，不再调 generate_batch；名字变化的新资产进 regen。
5. **付费墙协同**：stale 的 generate_videos 带 `confirm=true&force=false` → 增量续跑；`force=true` → 全量重跑；确认成功后 stale 清 0（复用设计2 的清脏逻辑）。
6. **浏览器（视工具稳定性）**：完成后可选，验证「补跑未完成 / 全部重生成」两个按钮的交互。
