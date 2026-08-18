/**
 * 工作流操作中心 — 核心页面（编辑器式布局）。
 *
 * 布局（参考 Linear/Figma 编辑器范式）:
 *   顶部：面包屑（返回 + 项目标题 + 剧集切换 + 复制）
 *   左侧：窄步骤导航 rail（StepNav）— 常驻状态/耗时/过期标记，可自由跳转
 *   主区：单栏聚焦当前选中步骤的内容
 *
 * 生成步骤（generate_videos/merge_videos）作为第 6/7 步的内容出现，
 * 不再是常驻右栏 —— 消除原布局的冗余。
 *
 * 大数据：分镜按 shot_groups 分组折叠、默认折叠点开才渲染；文本用 line-clamp 视觉截断。
 * 编辑：统一「点铅笔进编辑 → 显式保存/Esc 取消」，无自动保存。
 * 生成：generate_videos 后端异步，前端轮询 GET /project 刷新进度。
 */
(function () {
    const U = () => window.Utils;
    const C = () => window.Components;

    const STEP_DEFS = [
        { key: 'parse_docx', label: '解析剧本', icon: '📝', desc: '从 Word 文档中提取结构化剧本信息', phase: 'preview' },
        { key: 'generate_asset_package', label: '生成资产包', icon: '🎭', desc: '识别角色、场景、道具，生成统一风格描述', phase: 'preview' },
        { key: 'step1_storyboard', label: '分镜生成', icon: '🎬', desc: '生成详细的分镜脚本和镜头序列', phase: 'preview' },
        { key: 'step2_consistency', label: '一致性检查', icon: '🔗', desc: '检查角色造型和场景风格的一致性', phase: 'preview' },
        { key: 'step3_optimize_prompts', label: '优化提示词', icon: '✨', desc: '生成用于视频 API 的精确提示词', phase: 'preview' },
        { key: 'generate_videos', label: '生成视频', icon: '🎥', desc: '调用视频 API 生成视频片段（付费）', phase: 'generate' },
        { key: 'merge_videos', label: '合并视频', icon: '🎞️', desc: '将所有片段合并为完整视频', phase: 'generate' },
    ];

    window.workflowView = function workflowView(container, projectId) {
        let project = null;
        let activeStep = 'parse_docx';
        let pollTimer = null;
        let detailCleanup = null;   // 当前主区详情的事件清理

        const E = () => U().escHtml;

        // ─── 顶层渲染 ────────────────────────────────────────────
        function render() {
            container.innerHTML = `
                <div class="wf-topbar">
                    <button class="btn btn-outline btn-sm" data-role="back">← 返回</button>
                    <h2 class="wf-title" data-role="title">🎬 加载中...</h2>
                    <div class="wf-episode" data-role="episode"></div>
                    <div style="flex:1;"></div>
                    <button class="btn btn-outline btn-sm hidden" data-role="prev-ep">‹ 上一集</button>
                    <button class="btn btn-outline btn-sm hidden" data-role="next-ep">下一集 ›</button>
                    <button class="btn btn-outline btn-sm hidden" data-role="duplicate">📋 复制</button>
                </div>
                <div class="wf-layout">
                    <aside class="wf-rail" data-role="rail"></aside>
                    <section class="wf-main" data-role="main"></section>
                </div>
            `;
            container.querySelector('[data-role="back"]').addEventListener('click', () => Router.navigate('projects'));
            container.querySelector('[data-role="duplicate"]').addEventListener('click', duplicateProject);
            container.querySelector('[data-role="rail"]').addEventListener('click', onRailClick);
            container.querySelector('[data-role="prev-ep"]').addEventListener('click', () => gotoEpisode(-1));
            container.querySelector('[data-role="next-ep"]').addEventListener('click', () => gotoEpisode(1));
            loadProject(true);
        }

        async function loadProject(selectDefault = false) {
            try {
                project = await API.getProject(projectId);
            } catch (e) {
                container.innerHTML = `<div class="empty-state"><span class="empty-state-icon">❌</span><h3>项目不存在</h3><p>${E()(e.message)}</p></div>`;
                return;
            }
            const titleEl = container.querySelector('[data-role="title"]');
            if (titleEl) titleEl.textContent = `🎬 ${project.name || project.episode_title || '未命名项目'}`;
            const epEl = container.querySelector('[data-role="episode"]');
            if (epEl && project.episode_id) epEl.textContent = `第 ${project.episode_title || project.episode_id} 集`;
            container.querySelector('[data-role="duplicate"]').classList.remove('hidden');

            renderEpisodeNav();

            if (selectDefault) {
                // 默认聚焦第一个未完成步骤，否则聚焦第一步
                const sm = stepStatusMap();
                const firstIncomplete = STEP_DEFS.find(s => sm[s.key]?.status !== 'completed');
                activeStep = (firstIncomplete && sm[firstIncomplete.key]?.status !== undefined)
                    ? firstIncomplete.key : STEP_DEFS[0].key;
            }
            renderRail();
            renderMain();
        }

        function stepStatusMap() {
            const sm = {};
            (project.steps || []).forEach(s => {
                sm[s.step_name] = {
                    status: s.status, started: s.started_at, finished: s.finished_at,
                    summary: s.result_summary || '', stale: !!s.stale,
                };
            });
            return sm;
        }

        // ─── 步骤导航 rail ────────────────────────────────────────
        function renderRail() {
            const rail = container.querySelector('[data-role="rail"]');
            if (!rail) return;
            const sm = stepStatusMap();
            const uploadDone = project.input_file && project.input_file.length > 0;
            const steps = STEP_DEFS.map(s => {
                const info = sm[s.key] || { status: 'pending' };
                return {
                    key: s.key, label: s.label, icon: s.icon,
                    status: info.status || 'pending',
                    started: info.started, finished: info.finished,
                    stale: !!info.stale,
                };
            });
            rail.innerHTML = `
                <div class="wf-upload-mini ${uploadDone ? 'done' : ''}" data-role="upload-mini">
                    <span>${uploadDone ? '✓' : '📄'}</span>
                    <span>${uploadDone ? '剧本已上传' : '上传 .docx 剧本'}</span>
                    <input type="file" accept=".docx" data-role="file-input" hidden>
                </div>
                ${C().StepNav.render(steps, activeStep)}
            `;
            const mini = rail.querySelector('[data-role="upload-mini"]');
            const fileInput = rail.querySelector('[data-role="file-input"]');
            mini.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', handleFileSelect);
        }

        function onRailClick(e) {
            const item = e.target.closest('.step-nav-item');
            if (!item) return;
            selectStep(item.dataset.step);
        }

        function selectStep(key) {
            // 离开当前步骤时停止轮询，避免切走后定时器空转 + 竞态覆盖 project
            stopPolling();
            activeStep = key;
            renderRail();
            renderMain();
        }

        // ─── 主内容区 ─────────────────────────────────────────────
        function renderMain() {
            if (detailCleanup) { try { detailCleanup(); } catch (e) {} detailCleanup = null; }
            const main = container.querySelector('[data-role="main"]');
            if (!main) return;
            const def = STEP_DEFS.find(s => s.key === activeStep);
            const sm = stepStatusMap();
            const info = sm[activeStep] || { status: 'pending' };

            main.innerHTML = `
                <div class="wf-main-head">
                    <div>
                        <h3 class="wf-main-title">${def.icon} ${E()(def.label)}</h3>
                        <p class="text-muted text-sm">${E()(def.desc)}</p>
                    </div>
                    <div class="wf-main-actions" data-role="step-actions">${stepActionBtn(info.status)}</div>
                </div>
                <div class="wf-main-body" data-role="detail"></div>
            `;
            main.querySelector('[data-role="step-actions"]').addEventListener('click', onStepActionClick);

            if (def.phase === 'generate') {
                renderGenerate(main.querySelector('[data-role="detail"]'), sm);
            } else if (info.status === 'completed' || info.status === 'failed') {
                loadStepDetail(activeStep, main.querySelector('[data-role="detail"]'));
            } else if (info.status === 'running') {
                main.querySelector('[data-role="detail"]').innerHTML = runningPlaceholder();
            } else {
                main.querySelector('[data-role="detail"]').innerHTML = `
                    <div class="empty-state" style="padding:48px 20px;">
                        <span class="empty-state-icon">${def.icon}</span>
                        <h3>尚未执行</h3>
                        <p>点击右上角「执行」开始此步骤</p>
                    </div>`;
            }
        }

        function stepActionBtn(status) {
            if (status === 'completed') return `<button class="btn btn-sm btn-outline" data-action="redo">🔄 重做</button>`;
            if (status === 'failed') return `<button class="btn btn-sm btn-warning" data-action="redo">🔁 重试</button>`;
            if (status === 'running') return `<span class="text-sm text-muted"><span class="spinner spinner-dark" style="width:14px;height:14px;"></span> 执行中...</span>`;
            return `<button class="btn btn-sm btn-primary" data-action="run">▶ 执行</button>`;
        }

        function runningPlaceholder() {
            return `<div class="text-center" style="padding:48px 20px;">
                <span class="spinner spinner-dark" style="width:32px;height:32px;"></span>
                <p class="mt-4 text-muted">执行中，请稍候...</p></div>`;
        }

        function onStepActionClick(e) {
            const action = e.target.closest('[data-action]')?.dataset.action;
            if (action === 'run') runStep(activeStep);
            else if (action === 'redo') redoStep(activeStep);
        }

        // ─── 加载步骤详情 ─────────────────────────────────────────
        async function loadStepDetail(stepKey, detailEl) {
            detailEl = detailEl || container.querySelector('[data-role="detail"]');
            if (!detailEl) return;
            detailEl.innerHTML = `<span class="spinner spinner-dark" style="width:14px;height:14px;"></span> 加载中...`;
            try {
                const data = await API.getEditable(projectId, stepKey);
                const raw = data._raw || {};
                detailEl.innerHTML = renderStepContent(stepKey, raw);
                bindDetail(stepKey, detailEl);
            } catch (e) {
                detailEl.innerHTML = `<div class="alert alert-error">加载失败: ${E()(e.message)}</div>`;
            }
        }

        function renderStepContent(stepKey, data) {
            switch (stepKey) {
                case 'parse_docx': return renderParseDocx(data);
                case 'generate_asset_package': return renderAssets(data);
                case 'step1_storyboard': return renderStoryboard(data);
                case 'step2_consistency': return renderConsistency(data);
                case 'step3_optimize_prompts': return renderPrompts(data);
                default: return `<pre style="font-size:12px;">${E()(JSON.stringify(data, null, 2))}</pre>`;
            }
        }

        // 统一保存回调（供 EditableField / PromptModal 使用）
        function makeSaver(reset = true) {
            return async (path, value) => {
                await API.updateField(projectId, path, value, reset);
                // 重新拉项目以刷新 rail「已过期」与下游状态
                project = await API.getProject(projectId);
                renderRail();
            };
        }

        function bindDetail(stepKey, detailEl) {
            const cleanups = [];
            // 统一的内联编辑（EditableField 容器委托）
            cleanups.push(C().EditableField.bindContainer(detailEl, makeSaver(true)));

            // 通用容器级委托：复制、上传、图片 lightbox、提示词弹窗、分组折叠
            const onClick = (e) => {
                const actEl = e.target.closest('[data-action]');
                const act = actEl?.dataset.action;
                if (act === 'copy') {
                    U().copyFromButton(actEl, actEl.dataset.copy || '', '提示词已复制');
                } else if (act === 'edit-asset') {
                    openAssetDrawer(actEl.dataset.category, +actEl.dataset.index);
                } else if (act === 'toggle-group') {
                    const group = actEl.closest('.shot-group');
                    if (group) toggleGroup(group);
                } else if (act === 'open-prompt') {
                    openPrompt(actEl);
                } else if (e.target.matches('img[data-lightbox]')) {
                    U().openLightbox(e.target.src);
                }
            };
            detailEl.addEventListener('click', onClick);
            cleanups.push(() => detailEl.removeEventListener('click', onClick));

            // 资产卡键盘可达性：Enter / Space 打开编辑抽屉
            const onKeydown = (e) => {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                const card = e.target.closest('[data-action="edit-asset"]');
                if (!card) return;
                e.preventDefault();
                openAssetDrawer(card.dataset.category, +card.dataset.index);
            };
            detailEl.addEventListener('keydown', onKeydown);
            cleanups.push(() => detailEl.removeEventListener('keydown', onKeydown));

            const onChange = (e) => {
                const inp = e.target.closest('[data-action="upload-asset"]');
                if (inp) handleAssetUpload(inp);
            };
            detailEl.addEventListener('change', onChange);
            cleanups.push(() => detailEl.removeEventListener('change', onChange));

            if (stepKey === 'step1_storyboard') {
                // 渲染初始展开的分组（默认第一组），懒渲染其余
                detailEl.querySelectorAll('.shot-group.open').forEach(g => {
                    renderGroupBody(parseInt(g.dataset.groupIdx), g);
                });
                cleanups.push(initDragDrop(detailEl));
            }
            detailCleanup = () => cleanups.forEach(fn => { try { fn(); } catch (e) {} });
        }

        // ─── 各步骤渲染 ───────────────────────────────────────────
        function renderParseDocx(data) {
            const EF = C().EditableField;
            const chars = data.parsed_characters || [];
            const scenes = data.parsed_scenes || [];
            return `
                <div class="section-label">人物 (${chars.length})</div>
                <div class="stack">
                ${chars.map((c, i) => `
                    <div class="mini-card">
                        ${EF.render({ path: `parsed_characters.${i}.name`, value: c.name || '', type: 'input', lines: 1, placeholder: '角色名' })}
                        ${EF.render({ path: `parsed_characters.${i}.role`, value: c.role || '', type: 'input', lines: 1, placeholder: '角色定位' })}
                        ${EF.render({ path: `parsed_characters.${i}.description`, value: c.description || '', type: 'textarea', lines: 3, placeholder: '描述' })}
                    </div>`).join('')}
                </div>
                <div class="section-label">场景 (${scenes.length})</div>
                <div class="stack">
                ${scenes.map((s, i) => `
                    <div class="mini-row"><strong>${E()(s.name || `场景${i + 1}`)}</strong>
                        <span class="text-muted"> — ${E()(s.location || '')} · ${E()(s.time_of_day || '')}</span></div>
                `).join('')}
                </div>`;
        }

        function renderAssets(data) {
            const groups = [
                { label: '👤 角色', items: data.characters || [], cat: 'character_assets' },
                { label: '🏞️ 场景', items: data.scenes || [], cat: 'scene_assets' },
                { label: '🔧 道具', items: data.props || [], cat: 'prop_assets' },
            ];
            return groups.filter(g => g.items.length).map(g => `
                <div class="section-label">${g.label} (${g.items.length})</div>
                <div class="asset-gallery">
                    ${g.items.map((a, i) => C().AssetCard.render(a, i, g.cat, { projectId })).join('')}
                </div>`).join('');
        }

        // 从当前 project.state 取某个资产对象
        function getAsset(category, index) {
            return ((project.state || {})[category] || [])[index] || {};
        }

        // 侧边抽屉：编辑单个资产（名称/描述/提示词 + 图片上传）
        function openAssetDrawer(category, index) {
            const EF = C().EditableField;
            const catLabel = { character_assets: '角色', scene_assets: '场景', prop_assets: '道具' }[category] || '资产';

            const buildBody = () => {
                const a = getAsset(category, index);
                const imgSrc = a.image_path ? API.fileUrl(projectId, a.image_path) : '';
                const hasImage = imgSrc && (a.image_generated || a.image_status === 'manual_upload');
                const mediaBlock = hasImage
                    ? `<div class="drawer-media">
                           <img src="${U().escAttr(imgSrc)}" alt="${U().escAttr(a.name)}" data-lightbox>
                           <label class="drawer-media-replace">
                               更换图片
                               <input type="file" accept="image/*" class="upload-input" data-role="drawer-upload">
                           </label>
                       </div>`
                    : `<label class="upload-zone drawer-upload-zone">
                           <span class="upload-zone-icon">📤</span>
                           <span class="upload-zone-text">上传参考图</span>
                           <span class="upload-zone-hint">点击选择图片</span>
                           <input type="file" accept="image/*" class="upload-input" data-role="drawer-upload">
                       </label>`;

                return `
                    ${mediaBlock}
                    <div class="drawer-field">
                        <label class="drawer-label">名称</label>
                        ${EF.render({ path: `${category}.${index}.name`, value: a.name || '', type: 'input', lines: 1, placeholder: '名称' })}
                    </div>
                    <div class="drawer-field">
                        <label class="drawer-label">描述</label>
                        ${EF.render({ path: `${category}.${index}.description`, value: a.description || '', type: 'textarea', lines: 5, minHeight: 90, placeholder: '外观、气质、身份等描述' })}
                    </div>
                    <div class="drawer-field">
                        <label class="drawer-label drawer-label-row">
                            <span>生成提示词</span>
                            ${a.prompt ? `<button class="btn-copy" data-action="copy" data-copy="${U().escAttr(a.prompt)}" title="复制提示词"><span class="copy-ico">📋</span> 复制</button>` : ''}
                        </label>
                        ${a.prompt
                            ? EF.render({ path: `${category}.${index}.prompt`, value: a.prompt || '', type: 'textarea', lines: 6, minHeight: 110, placeholder: '用于图像生成的提示词' })
                            : '<p class="text-muted text-sm">暂无提示词（生成资产包时自动产出）</p>'}
                    </div>`;
            };

            C().Drawer.open({
                title: `✏️ 编辑${catLabel}`,
                subtitle: getAsset(category, index).name || '未命名',
                bodyHtml: buildBody(),
                onMount(bodyEl, handle) {
                    // 抽屉内的内联编辑：保存后刷新卡片 + 抽屉副标题
                    const cleanupEF = EF.bindContainer(bodyEl, async (path, value) => {
                        await makeSaver(true)(path, value);
                        refreshAssetCard(category, index);
                        const sub = handle.root.querySelector('.drawer-subtitle');
                        if (sub && path.endsWith('.name')) sub.textContent = value || '未命名';
                    });

                    // 图片 lightbox / 提示词复制都在抽屉内处理
                    const onDrawerClick = (e) => {
                        const copyBtn = e.target.closest('[data-action="copy"]');
                        if (copyBtn) { U().copyFromButton(copyBtn, copyBtn.dataset.copy || '', '提示词已复制'); return; }
                        if (e.target.matches('img[data-lightbox]')) U().openLightbox(e.target.src);
                    };
                    bodyEl.addEventListener('click', onDrawerClick);

                    const onDrawerChange = async (e) => {
                        const inp = e.target.closest('[data-role="drawer-upload"]');
                        if (!inp || !inp.files[0]) return;
                        try {
                            await API.uploadAssetImage(projectId, category, index, inp.files[0]);
                            U().showToast('图片已上传');
                            project = await API.getProject(projectId);
                            handle.setBody(buildBody());   // 重渲染抽屉体，显示新图
                            refreshAssetCard(category, index);
                        } catch (err) {
                            U().showToast('上传失败: ' + err.message, 'error');
                        }
                    };
                    bodyEl.addEventListener('change', onDrawerChange);

                    handle._cleanup = () => {
                        try { cleanupEF(); } catch (e) {}
                        bodyEl.removeEventListener('click', onDrawerClick);
                        bodyEl.removeEventListener('change', onDrawerChange);
                    };
                },
                onClose() { /* setBody 会重建监听，这里无需额外处理 */ },
            });
        }

        // 局部刷新一张资产卡（避免整页重渲染打断滚动）
        function refreshAssetCard(category, index) {
            const detailEl = container.querySelector('[data-role="detail"]');
            if (!detailEl) return;
            const cardEl = detailEl.querySelector(`.asset-card[data-category="${category}"][data-index="${index}"]`);
            if (!cardEl) return;
            const a = getAsset(category, index);
            const tmp = document.createElement('div');
            tmp.innerHTML = C().AssetCard.render(a, index, category, { projectId });
            cardEl.replaceWith(tmp.firstElementChild);
        }

        function renderStoryboard(data) {
            const groups = data.shot_groups || [];
            if (!groups.length) return '<p class="text-muted">暂无分镜数据</p>';
            const totalShots = groups.reduce((n, g) => n + (g.shots || []).length, 0);
            return `
                <div class="section-label">🎬 镜头序列 (${totalShots} 个镜头, ${groups.length} 组 · 点击组标题展开)</div>
                <div class="shot-groups" data-role="shot-groups">
                ${groups.map((g, gi) => `
                    <div class="shot-group ${gi === 0 ? 'open' : ''}" data-group-idx="${gi}">
                        <div class="shot-group-head" data-action="toggle-group">
                            <span class="shot-group-caret">▶</span>
                            <span class="shot-group-name">${E()(g.group_name || `镜头组 ${gi + 1}`)}</span>
                            <span class="shot-group-count">${(g.shots || []).length} 个镜头</span>
                        </div>
                        <div class="shot-group-body" data-group-body="${gi}"></div>
                    </div>`).join('')}
                </div>`;
        }

        // 分组懒渲染：只有展开时才渲染组内卡片
        function toggleGroup(groupEl) {
            const gi = parseInt(groupEl.dataset.groupIdx);
            groupEl.classList.toggle('open');
            if (groupEl.classList.contains('open')) renderGroupBody(gi, groupEl);
        }

        function renderGroupBody(gi, groupEl) {
            const body = groupEl.querySelector(`[data-group-body="${gi}"]`);
            if (!body || body.dataset.rendered === '1') return;
            const groups = (project.state || {}).shot_groups || [];
            const shots = (groups[gi]?.shots) || [];
            body.innerHTML = `<div class="shot-cards-grid">${shots.map((s, si) =>
                C().ShotCard.render({ ...s, groupName: groups[gi].group_name, groupIdx: gi, shotIdx: si })
            ).join('')}</div>`;
            body.dataset.rendered = '1';
        }

        function renderConsistency(data) {
            const EF = C().EditableField;
            const anchors = data.consistency_anchors || [];
            if (!anchors.length) return '<p class="text-muted">暂无一致性问题</p>';
            return `<div class="section-label">📋 检查结果 (${anchors.length} 个锚点)</div>
                <div class="stack">
                ${anchors.map((a, i) => `
                    <div class="mini-card anchor">
                        <strong>${E()(a.anchor_name || '')}</strong>
                        ${EF.render({ path: `consistency_anchors.${i}.anchor_value`, value: a.anchor_value || '', type: 'textarea', lines: 3 })}
                    </div>`).join('')}
                </div>`;
        }

        function renderPrompts(data) {
            const groups = data.optimized_prompts || [];
            if (!groups.length) return '<p class="text-muted">暂无提示词</p>';
            return groups.map((g, gi) => `
                <div class="prompt-group-editor">
                    <div class="prompt-group-editor-header">📝 ${E()(g.group_name || `镜头组 ${gi + 1}`)}
                        <span style="font-weight:400;font-size:12px;"> · ${(g.shots || []).length} 个镜头</span></div>
                    ${(g.shots || []).map((s, si) => `
                        <div class="prompt-shot-editor">
                            <div class="shot-label">
                                <span>🎯 ${E()(s.shot_name || `镜头 ${si + 1}`)}</span>
                                <button class="btn-copy" data-action="copy" data-copy="${U().escAttr(s.prompt || '')}" title="复制提示词"><span class="copy-ico">📋</span> 复制</button>
                            </div>
                            <div class="prompt-preview" data-action="open-prompt"
                                 data-path="optimized_prompts.${gi}.shots.${si}.prompt"
                                 data-full="${U().escAttr(s.prompt || '')}"
                                 data-shot="${U().escAttr(s.shot_name || `镜头 ${si + 1}`)}"
                                 data-group="${U().escAttr(g.group_name || '')}"
                                 data-dialogue="${U().escAttr(s.dialogue || '')}"
                                 data-desc="${U().escAttr(s.description || '')}"
                                 title="点击查看/编辑提示词">${E()(s.prompt || s.description || '(无提示词)')}</div>
                            ${s.dialogue ? `<div class="text-sm" style="color:var(--primary);margin-top:4px;">💬 ${E()(s.dialogue)}</div>` : ''}
                        </div>`).join('')}
                </div>`).join('');
        }

        function openPrompt(el) {
            C().PromptModal.open({
                path: el.dataset.path,
                promptText: el.dataset.full,
                shotName: el.dataset.shot,
                groupName: el.dataset.group,
                dialogue: el.dataset.dialogue,
                description: el.dataset.desc,
                onSave: async (path, value) => {
                    await makeSaver(true)(path, value);
                    el.dataset.full = value;
                    el.textContent = value || '(无提示词)';
                },
            });
        }

        // ─── 拖拽排序（不重置下游 reset=false）────────────────────
        function initDragDrop(detailEl) {
            const grid = detailEl.querySelector('[data-role="shot-groups"]');
            if (!grid) return () => {};
            let dragSrc = null;

            const onDragStart = (e) => {
                const card = e.target.closest('.shot-card');
                if (!card) return;
                dragSrc = card; card.style.opacity = '0.5';
            };
            const onDragEnd = (e) => {
                const card = e.target.closest('.shot-card');
                if (card) card.style.opacity = '1';
                dragSrc = null;
                grid.querySelectorAll('.drag-over').forEach(c => c.classList.remove('drag-over'));
            };
            const onDragOver = (e) => {
                e.preventDefault();
                const card = e.target.closest('.shot-card');
                if (card && card !== dragSrc) card.classList.add('drag-over');
            };
            const onDragLeave = (e) => {
                const card = e.target.closest('.shot-card');
                if (card) card.classList.remove('drag-over');
            };
            const onDrop = async (e) => {
                e.preventDefault();
                const target = e.target.closest('.shot-card');
                if (!target || target === dragSrc || !dragSrc) return;
                const sg = +dragSrc.dataset.group, ss = +dragSrc.dataset.shot;
                const dg = +target.dataset.group, ds = +target.dataset.shot;
                const groups = (project.state || {}).shot_groups || [];
                if (groups[sg]?.shots && groups[dg]?.shots) {
                    const srcData = groups[sg].shots[ss];
                    const dstData = groups[dg].shots[ds];
                    try {
                        // reset=false：仅调整顺序，不清空一致性/提示词等下游
                        await API.updateField(projectId, `shot_groups.${sg}.shots.${ss}`, dstData, false);
                        await API.updateField(projectId, `shot_groups.${dg}.shots.${ds}`, srcData, false);
                        U().showToast('镜头顺序已调整');
                        project = await API.getProject(projectId);
                        loadStepDetail('step1_storyboard');
                    } catch (err) {
                        U().showToast('排序失败: ' + err.message, 'error');
                    }
                }
            };
            grid.addEventListener('dragstart', onDragStart);
            grid.addEventListener('dragend', onDragEnd);
            grid.addEventListener('dragover', onDragOver);
            grid.addEventListener('dragleave', onDragLeave);
            grid.addEventListener('drop', onDrop);
            return () => {
                grid.removeEventListener('dragstart', onDragStart);
                grid.removeEventListener('dragend', onDragEnd);
                grid.removeEventListener('dragover', onDragOver);
                grid.removeEventListener('dragleave', onDragLeave);
                grid.removeEventListener('drop', onDrop);
            };
        }

        // ─── 上传 ─────────────────────────────────────────────────
        async function handleFileSelect(e) {
            const file = e.target.files[0];
            if (!file || !file.name.endsWith('.docx')) {
                U().showToast('请选择 .docx 格式文件', 'error');
                return;
            }
            try {
                await API.uploadScript(projectId, file);
                U().showToast('上传成功');
                project = await API.getProject(projectId);
                renderRail();
                const sm = stepStatusMap();
                if ((sm['parse_docx']?.status || 'pending') === 'pending') {
                    selectStep('parse_docx');
                    await runStep('parse_docx');
                }
            } catch (err) {
                U().showToast('上传失败: ' + err.message, 'error');
            }
        }

        async function handleAssetUpload(input) {
            const file = input.files[0];
            if (!file) return;
            try {
                await API.uploadAssetImage(projectId, input.dataset.category, +input.dataset.index, file);
                U().showToast('图片已上传');
                project = await API.getProject(projectId);
                loadStepDetail('generate_asset_package');
            } catch (e) {
                U().showToast('上传失败: ' + e.message, 'error');
            }
        }

        async function handleVideoUpload(input) {
            const file = input.files[0];
            if (!file) return;
            try {
                await API.uploadSegmentVideo(projectId, input.dataset.segment, file);
                U().showToast('视频已上传');
                project = await API.getProject(projectId);
                renderMain();
            } catch (e) {
                U().showToast('上传失败: ' + e.message, 'error');
            }
        }

        // ─── 执行 / 重做（含异步轮询）─────────────────────────────
        // force=true 为幂等逃生阀（全部重生成）；默认增量续跑（只补跑未完成的）。
        async function runStep(stepName, confirmed = false, force = false) {
            const isGenerate = STEP_DEFS.find(s => s.key === stepName)?.phase === 'generate';
            const label = STEP_DEFS.find(s => s.key === stepName)?.label || stepName;
            // 立即置为执行中
            const actions = container.querySelector('[data-role="step-actions"]');
            if (actions && activeStep === stepName) actions.innerHTML = stepActionBtn('running');
            const detail = container.querySelector('[data-role="detail"]');
            if (detail && activeStep === stepName && !isGenerate) detail.innerHTML = runningPlaceholder();

            let res;
            try {
                res = await API.runStep(projectId, stepName, confirmed, force);
            } catch (e) {
                U().showToast(`${stepName} 执行失败: ${e.message}`, 'error');
                // 恢复按钮态（失败/取消时不要卡在「执行中」）
                project = await API.getProject(projectId);
                renderRail();
                if (activeStep === stepName) renderMain();
                return;
            }

            // 付费墙闸门：后端要求确认（已过期需重跑 / 已有产物将被覆盖）
            if (res && res.need_confirm) {
                const est = res.estimate || {};
                const shots = est.shot_count != null ? est.shot_count : '若干';
                const cost = est.estimated_cost || '未知';
                const why = res.reason === 'stale'
                    ? '上游已修改，当前产物已过期。'
                    : '该步骤已有产物，重跑将覆盖现有结果。';
                // 区分逃生阀：force 全量重生成 vs 默认增量续跑（省钱路径）
                const mode = force
                    ? '本次为「强制全部重新生成」，将忽略已完成片段、全部重新生成（更贵）。'
                    : '本次为「增量续跑」，已完成的片段将跳过、只补跑未完成的（更省）。';
                const ok = confirm(
                    `「${label}」是付费步骤。\n${why}\n${mode}\n\n` +
                    `本次最多生成 ${shots} 个镜头，预计花费 ${cost}。\n确认继续？`
                );
                if (!ok) {
                    // 用户取消：还原按钮，不发起执行
                    project = await API.getProject(projectId);
                    renderRail();
                    if (activeStep === stepName) renderMain();
                    return;
                }
                // 确认后带 confirm=true 重发（保留原 force）
                return runStep(stepName, true, force);
            }

            if (isGenerate) {
                startPolling(stepName);   // 异步：轮询直到完成
            } else {
                project = await API.getProject(projectId);
                renderRail();
                if (activeStep === stepName) renderMain();
            }
        }

        function startPolling(stepName) {
            stopPolling();
            const tick = async () => {
                try {
                    project = await API.getProject(projectId);
                } catch (e) { /* 忽略瞬时错误 */ }
                renderRail();
                if (activeStep === stepName || STEP_DEFS.find(s => s.key === activeStep)?.phase === 'generate') {
                    renderMain();
                }
                const st = stepStatusMap()[stepName]?.status;
                if (st === 'completed' || st === 'failed') {
                    stopPolling();
                }
            };
            pollTimer = setInterval(tick, 2500);
            tick();
        }
        function stopPolling() {
            if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        }

        async function redoStep(stepName) {
            const label = STEP_DEFS.find(s => s.key === stepName)?.label || stepName;
            if (!confirm(`确定要重新执行「${label}」吗？后续步骤结果将被清除。`)) return;
            try {
                await API.redoStep(projectId, stepName);
            } catch (e) {
                U().showToast('重置失败: ' + e.message, 'error');
                return;
            }
            project = await API.getProject(projectId);
            renderRail();
            // 「重做」语义即全部重来，走 force=true 保持一致
            await runStep(stepName, false, true);
        }

        // ─── 生成阶段内容（并入主区）─────────────────────────────
        function renderGenerate(detailEl, sm) {
            const allPreviewDone = STEP_DEFS.filter(s => s.phase === 'preview')
                .every(s => sm[s.key]?.status === 'completed');
            if (!allPreviewDone) {
                detailEl.innerHTML = `
                    <div class="empty-state" style="padding:48px 20px;">
                        <span class="empty-state-icon">🔒</span>
                        <h3>请先完成剧本处理步骤</h3>
                        <p>完成前 5 个预览步骤后，这里将解锁视频生成功能</p>
                    </div>`;
                return;
            }

            const state = project.state || {};
            const segs = state.video_segments || [];
            const genStatus = sm['generate_videos']?.status || 'pending';
            const mergeStatus = sm['merge_videos']?.status || 'pending';

            if (activeStep === 'generate_videos') {
                detailEl.innerHTML = renderVideoGen(state, segs, genStatus);
            } else {
                detailEl.innerHTML = renderMerge(state, segs, mergeStatus, genStatus);
            }
            bindGenerate(detailEl);

            // 若当前查看的生成步骤仍在后台运行，恢复轮询（例如切走再切回）
            const curStatus = sm[activeStep]?.status;
            if (curStatus === 'running' && !pollTimer) startPolling(activeStep);
        }

        function renderVideoGen(state, segs, genStatus) {
            const prompts = state.optimized_prompts || [];
            const totalShots = prompts.reduce((n, g) => n + (g.shots || []).length, 0);
            const cost = (totalShots * 3).toFixed(2);
            const completed = segs.filter(s => s.status === 'completed');
            const pendingUp = segs.filter(s => s.status === 'pending_upload');
            const failed = segs.filter(s => s.status === 'failed');

            if (genStatus === 'pending') {
                return `
                    <div class="cost-breakdown">
                        <div class="cost-row"><span>总镜头数</span><span>${totalShots} 个</span></div>
                        <div class="cost-row"><span>预估单价</span><span>≈ ¥3.00 / 条</span></div>
                        <div class="cost-row total"><span>预估费用</span><span>≈ ¥${cost}</span></div>
                    </div>
                    <div class="confirm-dialog"><strong>⚠️ 即将调用视频生成 API</strong><br>
                        将生成 ${totalShots} 个视频片段。生成在后台进行，可离开本页；已生成的片段不会因失败丢失。</div>
                    <button class="btn btn-primary btn-lg btn-block" data-action="gen-videos">🎥 确认生成视频（¥${cost}）</button>`;
            }
            if (genStatus === 'running') {
                const done = completed.length;
                const pct = segs.length ? Math.round(done / segs.length * 100) : 0;
                return `
                    <div class="text-center" style="padding:16px;">
                        <span class="spinner spinner-dark" style="width:32px;height:32px;"></span>
                        <p class="mt-2">视频生成中（后台运行，实时刷新）...</p>
                        <div class="progress-bar mt-2"><div class="progress-fill" style="width:${pct}%"></div></div>
                        <p class="text-sm text-muted mt-2">${done}/${segs.length || '?'} 已完成</p>
                    </div>`;
            }
            // completed
            return `
                <div class="alert alert-success">✓ 视频生成完成 — ${completed.length} 个成功${pendingUp.length ? `，${pendingUp.length} 个待上传` : ''}${failed.length ? `，${failed.length} 个失败` : ''}</div>
                <div class="section-label">视频片段</div>
                <div class="video-seg-grid">
                ${completed.map(s => C().VideoSegment.render(s, { projectId })).join('')}
                ${pendingUp.map(s => C().VideoSegment.render(s, { projectId })).join('')}
                </div>
                <div class="btn-row mt-4" style="display:flex;gap:8px;">
                    <button class="btn btn-primary" style="flex:1;" data-action="resume-videos"
                        title="已完成片段跳过、只补跑未完成的，保留手动上传">▶ 补跑未完成${failed.length ? `（${failed.length}）` : ''}</button>
                    <button class="btn btn-warning" style="flex:1;" data-action="regen-videos"
                        title="忽略已完成、全部重新生成（更贵）">🔁 全部重生成</button>
                </div>`;
        }

        function renderMerge(state, segs, mergeStatus, genStatus) {
            if (genStatus !== 'completed') {
                return `<div class="empty-state" style="padding:48px 20px;">
                    <span class="empty-state-icon">🎥</span><h3>请先完成视频生成</h3>
                    <p>所有片段生成后即可合并为完整视频</p></div>`;
            }
            if (mergeStatus === 'completed' && state.final_video_path) {
                const url = API.fileUrl(projectId, state.final_video_path);
                return `<div class="alert alert-success">✓ 视频合并完成</div>
                    <video controls src="${U().escAttr(url)}" style="width:100%;border-radius:8px;" preload="metadata"></video>
                    <a href="${U().escAttr(url)}" download class="btn btn-primary btn-block mt-2">⬇ 下载最终视频</a>`;
            }
            if (mergeStatus === 'running') return runningPlaceholder();
            return `<div class="confirm-dialog"><strong>🎞️ 合并所有片段</strong><br>将把已生成的视频片段按顺序合并为一条完整视频。</div>
                <button class="btn btn-success btn-lg btn-block" data-action="merge-videos">🎞️ 合并最终视频</button>`;
        }

        function bindGenerate(detailEl) {
            const onClick = (e) => {
                const act = e.target.closest('[data-action]')?.dataset.action;
                if (act === 'gen-videos') runStep('generate_videos');
                else if (act === 'merge-videos') runStep('merge_videos');
                else if (act === 'resume-videos') runStep('generate_videos', false, false);  // 增量续跑
                else if (act === 'regen-videos') runStep('generate_videos', false, true);     // 全部重生成
                else if (act === 'retry-videos') runStep('generate_videos', false, false);    // 兼容旧入口：补跑
                else if (act === 'copy') U().copyFromButton(e.target.closest('[data-action]'), e.target.closest('[data-action]').dataset.copy || '', '提示词已复制');
            };
            detailEl.addEventListener('click', onClick);
            const onChange = (e) => {
                const inp = e.target.closest('[data-action="upload-segment"]');
                if (inp) handleVideoUpload(inp);
            };
            detailEl.addEventListener('change', onChange);
            detailCleanup = () => {
                detailEl.removeEventListener('click', onClick);
                detailEl.removeEventListener('change', onChange);
            };
        }

        // ─── 剧集导航（多集：同 episode_id 视为一部剧，暂按项目列表相邻切换）──
        let _allProjects = null;
        async function renderEpisodeNav() {
            const prevBtn = container.querySelector('[data-role="prev-ep"]');
            const nextBtn = container.querySelector('[data-role="next-ep"]');
            if (!prevBtn) return;
            try {
                _allProjects = await API.listProjects();
            } catch (e) { return; }
            // 同名剧（去掉"第x集"后的基名）分为一组，按 episode_id 排序
            const idx = _allProjects.findIndex(p => p.id === projectId);
            if (idx > 0) prevBtn.classList.remove('hidden');
            if (idx >= 0 && idx < _allProjects.length - 1) nextBtn.classList.remove('hidden');
        }
        function gotoEpisode(delta) {
            if (!_allProjects) return;
            const idx = _allProjects.findIndex(p => p.id === projectId);
            const target = _allProjects[idx + delta];
            if (target) Router.navigate(`workflow/${target.id}`);
        }

        async function duplicateProject() {
            const name = (project.name || project.episode_title || '') + ' (副本)';
            try {
                const r = await API.duplicateProject(projectId, name);
                U().showToast('项目已复制');
                Router.navigate(`workflow/${r.new_id}`);
            } catch (e) {
                U().showToast('复制失败: ' + e.message, 'error');
            }
        }

        render();

        // cleanup
        return () => {
            stopPolling();
            if (detailCleanup) { try { detailCleanup(); } catch (e) {} }
        };
    };
})();
