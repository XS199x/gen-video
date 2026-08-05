/**
 * 工作流操作中心 — 核心页面。
 *
 * 两阶段布局:
 *   左侧：预览步骤（可展开、预览、编辑）
 *   右侧：视频生成面板
 *
 * 特性：
 *   - 每步完成后可展开查看详情
 *   - 文本/提示词支持内联编辑，自动/手动保存
 *   - 图片/视频缺失时支持手动上传
 *   - 图片 lightbox、分镜拖拽排序、Ctrl+S 保存、Toast 通知
 */

// ─── 全局上传处理（被内联 onclick 调用）───────────────────────────────

window._assetUpload = async function (event, projectId, category, index) {
    const file = event.target.files[0];
    if (!file) return;
    try {
        await API.uploadAssetImage(projectId, category, index, file);
        showToast('图片已上传');
        // 刷新资产详情
        const panel = document.querySelector('.step-item.expanded[data-step="generate_asset_package"]');
        if (panel) {
            panel.querySelector('.step-detail').innerHTML = '<span class="spinner spinner-dark" style="width:14px;height:14px;"></span> 加载中...';
            // Trigger reload via project refresh
            const wfInst = window._currentWorkflow;
            if (wfInst) wfInst.reloadProject();
        }
    } catch (e) {
        showToast('上传失败: ' + e.message, 'error');
    }
};

window._videoUpload = async function (event, projectId, segmentId) {
    const file = event.target.files[0];
    if (!file) return;
    try {
        await API.uploadSegmentVideo(projectId, segmentId, file);
        showToast('视频已上传');
        const wfInst = window._currentWorkflow;
        if (wfInst) wfInst.reloadProject();
    } catch (e) {
        showToast('上传失败: ' + e.message, 'error');
    }
};

window._copyPrompt = function (text) {
    navigator.clipboard.writeText(text).then(() => showToast('提示词已复制')).catch(() => showToast('复制失败', 'error'));
};

const STEP_DEFS = [
    { key: 'parse_docx', label: '解析剧本', icon: '📝', desc: '从 Word 文档中提取结构化剧本信息', phase: 'preview' },
    { key: 'generate_asset_package', label: '生成资产包', icon: '🎭', desc: '识别角色、场景、道具，生成统一风格描述', phase: 'preview' },
    { key: 'step1_storyboard', label: '分镜生成', icon: '🎬', desc: '生成详细的分镜脚本和镜头序列', phase: 'preview' },
    { key: 'step2_consistency', label: '一致性检查', icon: '🔗', desc: '检查角色造型和场景风格的一致性', phase: 'preview' },
    { key: 'step3_optimize_prompts', label: '优化提示词', icon: '✨', desc: '生成用于视频 API 的精确提示词（可编辑）', phase: 'preview' },
    { key: 'generate_videos', label: '生成视频', icon: '🎥', desc: '调用视频 API 生成视频片段（付费）', phase: 'generate' },
    { key: 'merge_videos', label: '合并视频', icon: '🎞️', desc: '将所有片段合并为完整视频', phase: 'generate' },
];

// ─── Toast ────────────────────────────────────────────────────────

function showToast(msg, type = 'success') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => { toast.remove(); }, 3000);
}

// ─── Debounce ──────────────────────────────────────────────────────

function debounce(fn, ms) {
    let timer;
    return function (...args) {
        clearTimeout(timer);
        timer = setTimeout(() => fn.apply(this, args), ms);
    };
}

// ─── Esc HTML ──────────────────────────────────────────────────────

function escHtml(s) {
    if (!s) return '';
    const el = document.createElement('span');
    el.textContent = String(s);
    return el.innerHTML;
}

// ═══════════════════════════════════════════════════════════════════
// 主视图
// ═══════════════════════════════════════════════════════════════════

function workflowView(container, projectId) {
    let project = null;
    let autoSaveTimers = {};

    function render() {
        container.innerHTML = `
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;flex-wrap:wrap;">
                <button class="btn btn-outline btn-sm" id="btnBack">← 返回</button>
                <h2 id="wfTitle" style="margin:0;">🎬 加载中...</h2>
                <div style="flex:1;"></div>
                <button class="btn btn-outline btn-sm hidden" id="btnDuplicate">📋 复制项目</button>
            </div>
            <div class="two-col">
                <div id="previewPanel"></div>
                <div class="panel-generate" id="generatePanel"></div>
            </div>
        `;

        document.getElementById('btnBack').addEventListener('click', () => Router.navigate('projects'));
        document.getElementById('btnDuplicate').addEventListener('click', duplicateProject);
        document.addEventListener('keydown', handleKeyboard);
        loadProject();
    }

    async function loadProject() {
        try {
            project = await API.getProject(projectId);
        } catch (e) {
            container.innerHTML = `<div class="empty-state"><span class="empty-state-icon">❌</span><h3>项目不存在</h3><p>${escHtml(e.message)}</p></div>`;
            return;
        }

        document.getElementById('wfTitle').textContent =
            `🎬 ${escHtml(project.name || project.episode_title || '未命名项目')}`;
        document.getElementById('btnDuplicate').classList.remove('hidden');

        renderPreviewPanel();
        renderGeneratePanel();
    }

    function handleKeyboard(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            saveAllEdits();
            showToast('已保存所有修改');
        }
    }

    function saveAllEdits() {
        const editors = document.querySelectorAll('.editable-field.editing');
        editors.forEach(el => {
            const saveBtn = el.querySelector('.btn-save-edit');
            if (saveBtn) saveBtn.click();
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // 预览面板
    // ═══════════════════════════════════════════════════════════════

    function renderPreviewPanel() {
        const panel = document.getElementById('previewPanel');
        if (!panel) return;

        const uploadDone = project.input_file && project.input_file.length > 0;
        const steps = project.steps || [];
        const stepMap = {};
        steps.forEach(s => { stepMap[s.step_name] = { status: s.status, started: s.started_at, finished: s.finished_at }; });

        panel.innerHTML = `
            <!-- 上传 -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">📄 上传剧本</span>
                    ${uploadDone ? '<span class="badge badge-completed">✓ 已上传</span>' : '<span class="badge badge-pending">待上传</span>'}
                </div>
                <div class="file-upload ${uploadDone ? 'has-file' : ''}" id="fileUpload">
                    <span class="file-upload-icon">${uploadDone ? '✓' : '📄'}</span>
                    <span class="file-upload-text">${uploadDone ? '剧本已上传（点击重新上传）' : '点击选择 .docx 剧本文件'}</span>
                    <input type="file" id="fileInput" accept=".docx" style="display:none">
                </div>
                <div id="uploadStatus" class="text-sm text-muted mt-2"></div>
            </div>

            <!-- 步骤列表 -->
            ${STEP_DEFS.filter(s => s.phase === 'preview').map((s, i) => {
                const info = stepMap[s.key] || { status: 'pending' };
                const isExpanded = info.status === 'completed' || info.status === 'failed';
                return `
                <div class="step-item ${info.status} ${isExpanded ? 'expanded' : ''}" data-step="${s.key}" id="step-${s.key}">
                    <div class="step-indicator">${statusIcon(info.status)}</div>
                    <div class="step-body">
                        <div class="step-header-clickable" style="display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;">
                            <div style="flex:1;">
                                <div class="step-name">${s.icon} ${s.label}</div>
                                <div class="step-desc">
                                    ${s.desc}
                                    ${info.finished ? ` · ⏱ ${formatDuration(info.started, info.finished)}` : ''}
                                </div>
                            </div>
                            <span class="expand-icon" style="font-size:18px;color:var(--text-muted);transition:transform .2s;">▼</span>
                        </div>
                        <div class="step-result" id="summary-${s.key}"></div>
                        <div class="step-detail" id="detail-${s.key}">
                            <span class="spinner spinner-dark" style="width:14px;height:14px;"></span> 加载中...
                        </div>
                    </div>
                    <div class="step-actions">
                        ${info.status === 'completed'
                            ? `<button class="btn btn-sm btn-outline" data-action="redo" data-step="${s.key}">🔄 重做</button>`
                            : info.status === 'failed'
                            ? `<button class="btn btn-sm btn-warning" data-action="redo" data-step="${s.key}">🔁 重试</button>`
                            : `<button class="btn btn-sm btn-primary" data-action="run" data-step="${s.key}">▶ 执行</button>`}
                    </div>
                </div>`;
            }).join('')}
        `;

        bindPreviewEvents(stepMap);
        // 加载已完成步骤的详情
        Object.entries(stepMap).forEach(([key, info]) => {
            if (info.status === 'completed' || info.status === 'failed') {
                loadStepDetail(key);
            }
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // 加载步骤详情
    // ═══════════════════════════════════════════════════════════════

    async function loadStepDetail(stepKey) {
        const detailEl = document.getElementById(`detail-${stepKey}`);
        if (!detailEl) return;

        try {
            const data = await API.getEditable(projectId, stepKey);
            const raw = data._raw || {};
            detailEl.innerHTML = renderStepContent(stepKey, raw, projectId);
            bindStepContentEvents(stepKey, raw);
        } catch (e) {
            detailEl.innerHTML = `<div class="alert alert-error">加载失败: ${escHtml(e.message)}</div>`;
        }
    }

    function renderStepContent(stepKey, data, pid) {
        switch (stepKey) {
            case 'parse_docx':
                return renderParseDocxContent(data);
            case 'generate_asset_package':
                return renderAssetContent(data, pid);
            case 'step1_storyboard':
                return renderStoryboardContent(data);
            case 'step2_consistency':
                return renderConsistencyContent(data);
            case 'step3_optimize_prompts':
                return renderPromptsContent(data);
            default:
                return `<pre style="font-size:12px;color:var(--text-secondary);overflow-x:auto;">${escHtml(JSON.stringify(data, null, 2))}</pre>`;
        }
    }

    function bindStepContentEvents(stepKey, data) {
        const detailEl = document.getElementById(`detail-${stepKey}`);
        if (!detailEl) return;

        // Click on view-mode to enter edit mode (single click, not double)
        detailEl.querySelectorAll('.view-mode').forEach(el => {
            el.addEventListener('click', function (e) {
                // Don't intercept clicks on nested buttons
                if (e.target.closest('button')) return;
                const field = this.closest('.editable-field');
                if (!field) return;
                // Prompt modal fields open a popup instead of inline editing
                if (field.dataset.promptModal === 'true') {
                    openPromptModal(field);
                    return;
                }
                enterEditMode(field);
            });
        });

        // Copy buttons (prompt copy)
        detailEl.querySelectorAll('.btn-copy-prompt').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                e.preventDefault();
                const text = btn.dataset.prompt || '';
                navigator.clipboard.writeText(text).then(
                    () => { showToast('提示词已复制'); }
                ).catch(() => showToast('复制失败，请手动选中文本复制', 'error'));
            });
        });

        // Generic text copy buttons
        detailEl.querySelectorAll('.btn-copy-text').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const text = btn.dataset.copy || '';
                navigator.clipboard.writeText(text).then(
                    () => { btn.textContent = '✓ 已复制'; setTimeout(() => btn.textContent = '📋 复制', 1500); }
                ).catch(() => showToast('复制失败，请手动选中文本复制', 'error'));
            });
        });

        // 编辑按钮
        detailEl.querySelectorAll('.btn-edit-field').forEach(btn => {
            btn.addEventListener('click', () => {
                const field = btn.closest('.editable-field');
                if (field) enterEditMode(field);
            });
        });

        // 保存按钮
        detailEl.querySelectorAll('.btn-save-edit').forEach(btn => {
            btn.addEventListener('click', () => saveEdit(btn.closest('.editable-field')));
        });

        // 取消按钮
        detailEl.querySelectorAll('.btn-cancel-edit').forEach(btn => {
            btn.addEventListener('click', () => {
                const field = btn.closest('.editable-field');
                if (field) cancelEdit(field);
            });
        });

        // Auto-save on input (debounced 2s)
        detailEl.querySelectorAll('.editable-textarea, .editable-input').forEach(input => {
            const debouncedSave = debounce(() => {
                const field = input.closest('.editable-field');
                if (field && field.classList.contains('editing')) {
                    saveEdit(field);
                }
            }, 2000);
            input.addEventListener('input', debouncedSave);
        });

        // Lightbox for images
        detailEl.querySelectorAll('img[data-lightbox]').forEach(img => {
            img.addEventListener('click', () => openLightbox(img.src));
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // 各步骤渲染
    // ═══════════════════════════════════════════════════════════════

    function renderParseDocxContent(data) {
        const chars = data.parsed_characters || [];
        const scenes = data.parsed_scenes || [];
        return `
            <div class="section-label">人物 (${chars.length})</div>
            ${chars.map((c, i) => `
                <div class="editable-field" data-path="parsed_characters.${i}">
                    <div class="view-mode" style="display:flex;gap:8px;align-items:center;padding:8px;margin:4px 0;background:#fafafa;border-radius:6px;">
                        <div style="flex:1;"><strong>${escHtml(c.name || '未命名')}</strong> — ${escHtml(c.role || '')}</div>
                        <div style="font-size:12px;color:var(--text-secondary);">${escHtml((c.description || '').substring(0, 60))}</div>
                        <button class="btn btn-sm btn-outline btn-edit-field">✏️</button>
                    </div>
                    <div class="edit-mode" style="background:#fffbeb;padding:10px;border-radius:6px;margin:4px 0;">
                        <input class="editable-input mb-2" data-field="name" value="${escHtml(c.name || '')}" placeholder="角色名">
                        <input class="editable-input mb-2" data-field="role" value="${escHtml(c.role || '')}" placeholder="角色定位">
                        <textarea class="editable-textarea" data-field="description" style="min-height:40px;" placeholder="描述">${escHtml(c.description || '')}</textarea>
                        <div class="editable-actions">
                            <button class="btn btn-sm btn-outline btn-cancel-edit">取消</button>
                            <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
                        </div>
                    </div>
                </div>
            `).join('')}
            <div class="section-label">场景 (${scenes.length})</div>
            ${scenes.map((s, i) => `
                <div style="padding:6px 8px;margin:2px 0;background:#fafafa;border-radius:6px;font-size:13px;">
                    <strong>${escHtml(s.name || `场景${i+1}`)}</strong>
                    <span class="text-muted"> — ${escHtml(s.location || '')} · ${escHtml(s.time_of_day || '')}</span>
                </div>
            `).join('')}
        `;
    }

    function renderAssetContent(data, pid) {
        const characters = data.characters || [];
        const scenes = data.scenes || [];
        const props = data.props || [];

        return `
            ${characters.length ? `
            <div class="section-label">👤 角色 (${characters.length})</div>
            <div class="asset-gallery">
                ${characters.map((a, i) => renderAssetCard(a, i, 'character_assets', pid)).join('')}
            </div>` : ''}
            ${scenes.length ? `
            <div class="section-label">🏞️ 场景 (${scenes.length})</div>
            <div class="asset-gallery">
                ${scenes.map((a, i) => renderAssetCard(a, i, 'scene_assets', pid)).join('')}
            </div>` : ''}
            ${props.length ? `
            <div class="section-label">🔧 道具 (${props.length})</div>
            <div class="asset-gallery">
                ${props.map((a, i) => renderAssetCard(a, i, 'prop_assets', pid)).join('')}
            </div>` : ''}
        `;
    }

    function renderAssetCard(asset, index, category, pid) {
        const imgSrc = asset.image_path ? API.fileUrl(pid, asset.image_path) : '';
        const hasImage = imgSrc && (asset.image_generated || asset.image_status === 'manual_upload');
        const imgStatus = asset.image_status || (asset.image_generated ? 'generated' : 'pending_upload');

        return `
        <div class="asset-gallery-card" id="assetCard-${category}-${index}">
            ${hasImage ? `<img src="${imgSrc}" alt="${escHtml(asset.name)}" data-lightbox loading="lazy" onerror="this.parentElement.querySelector('.upload-zone').style.display='flex';this.style.display='none';">`
                : `<div class="upload-zone" data-category="${category}" data-index="${index}">
                    <span class="upload-zone-icon">📤</span>
                    <span class="upload-zone-text">${imgStatus === 'api_unavailable' ? 'API 不可用' : imgStatus === 'failed' ? '生成失败' : '点击上传图片'}</span>
                    <span class="upload-zone-hint">拖入或点击选择图片</span>
                    <input type="file" accept="image/*" class="upload-input" onchange="window._assetUpload(event, '${pid}', '${category}', ${index})">
                </div>`}
            <div class="asset-gallery-card-body">
                <div class="editable-field" data-path="${category}.${index}.name">
                    <div class="view-mode"><h4>${escHtml(asset.name || '未命名')}</h4></div>
                    <div class="edit-mode">
                        <input class="editable-input" data-field="name" value="${escHtml(asset.name || '')}">
                        <div class="editable-actions">
                            <button class="btn btn-sm btn-outline btn-cancel-edit">取消</button>
                            <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
                        </div>
                    </div>
                </div>
                <div class="editable-field" data-path="${category}.${index}.description">
                    <div class="view-mode"><p class="desc">${escHtml((asset.description || '').substring(0, 80))}</p></div>
                    <div class="edit-mode">
                        <textarea class="editable-textarea" data-field="description" style="min-height:40px;">${escHtml(asset.description || '')}</textarea>
                        <div class="editable-actions">
                            <button class="btn btn-sm btn-outline btn-cancel-edit">取消</button>
                            <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
                        </div>
                    </div>
                </div>
                <p class="prompt">${escHtml((asset.prompt || '').substring(0, 60))}</p>
                <button class="btn btn-sm btn-outline btn-edit-field" style="margin-top:4px;font-size:11px;">✏️ 编辑</button>
            </div>
        </div>`;
    }

    function renderStoryboardContent(data) {
        const groups = data.shot_groups || [];
        if (!groups.length) return '<p class="text-muted">暂无分镜数据</p>';

        const allShots = [];
        groups.forEach((g, gi) => {
            (g.shots || []).forEach((s, si) => {
                allShots.push({ ...s, groupName: g.group_name, groupIdx: gi, shotIdx: si });
            });
        });

        return `
            <div class="section-label">🎬 镜头序列 (${allShots.length} 个镜头, ${groups.length} 组)</div>
            <div class="shot-cards-grid" id="shotCardsGrid">
                ${allShots.map(s => renderShotCard(s)).join('')}
            </div>
        `;
    }

    function renderShotCard(shot) {
        return `
        <div class="shot-card" draggable="true" data-group="${shot.groupIdx}" data-shot="${shot.shotIdx}"
             id="shotCard-${shot.groupIdx}-${shot.shotIdx}">
            <div class="shot-card-header">
                <span class="drag-handle">⠿</span>
                <span class="shot-card-id">${escHtml(shot.shot_id || '')}</span>
                <span class="shot-card-group">${escHtml(shot.groupName || '')}</span>
            </div>
            <div class="editable-field" data-path="shot_groups.${shot.groupIdx}.shots.${shot.shotIdx}.content">
                <div class="view-mode shot-card-content">${escHtml((shot.content || shot.description || '').substring(0, 150))}</div>
                <div class="edit-mode">
                    <textarea class="editable-textarea" data-field="content" style="min-height:60px;">${escHtml(shot.content || '')}</textarea>
                    <div class="editable-actions">
                        <button class="btn btn-sm btn-outline btn-cancel-edit">取消</button>
                        <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
                    </div>
                </div>
            </div>
            ${shot.dialogue ? `<div class="editable-field" data-path="shot_groups.${shot.groupIdx}.shots.${shot.shotIdx}.dialogue">
                <div class="view-mode shot-card-dialogue">💬 ${escHtml(shot.dialogue.substring(0, 100))}</div>
                <div class="edit-mode">
                    <textarea class="editable-textarea" data-field="dialogue" style="min-height:40px;">${escHtml(shot.dialogue || '')}</textarea>
                    <div class="editable-actions">
                        <button class="btn btn-sm btn-outline btn-cancel-edit">取消</button>
                        <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
                    </div>
                </div>
            </div>` : ''}
            <div class="shot-card-meta">
                ${shot.shot_type ? `<span>🎥 ${escHtml(shot.shot_type)}</span>` : ''}
                ${shot.framing ? `<span>📐 ${escHtml(shot.framing)}</span>` : ''}
                ${shot.visual_style ? `<span>🎨 ${escHtml(shot.visual_style.substring(0, 30))}</span>` : ''}
            </div>
        </div>`;
    }

    function renderConsistencyContent(data) {
        const anchors = data.consistency_anchors || [];
        if (!anchors.length) return '<p class="text-muted">暂无一致性问题</p>';
        return `
            <div class="section-label">📋 检查结果 (${anchors.length} 个锚点)</div>
            ${anchors.map((a, i) => `
                <div class="editable-field" data-path="consistency_anchors.${i}" style="padding:8px;margin:4px 0;background:#fafafa;border-radius:6px;border-left:3px solid var(--warning);">
                    <div class="view-mode">
                        <strong>${escHtml(a.anchor_name || '')}</strong>
                        <p class="text-sm text-muted" style="margin-top:4px;">${escHtml((a.anchor_value || '').substring(0, 200))}</p>
                        <button class="btn btn-sm btn-outline btn-edit-field" style="margin-top:4px;">✏️</button>
                    </div>
                    <div class="edit-mode" style="background:#fffbeb;padding:10px;border-radius:6px;">
                        <textarea class="editable-textarea" data-field="anchor_value" style="min-height:60px;">${escHtml(a.anchor_value || '')}</textarea>
                        <div class="editable-actions">
                            <button class="btn btn-sm btn-outline btn-cancel-edit">取消</button>
                            <button class="btn btn-sm btn-primary btn-save-edit">保存</button>
                        </div>
                    </div>
                </div>
            `).join('')}
        `;
    }

    function renderPromptsContent(data) {
        const groups = data.optimized_prompts || [];
        if (!groups.length) return '<p class="text-muted">暂无提示词</p>';
        return groups.map((g, gi) => `
            <div class="prompt-group-editor">
                <div class="prompt-group-editor-header">
                    📝 ${escHtml(g.group_name || `镜头组 ${gi + 1}`)}
                    <span style="font-weight:400;font-size:12px;"> · ${(g.shots || []).length} 个镜头</span>
                </div>
                ${(g.shots || []).map((s, si) => `
                    <div class="prompt-shot-editor">
                        <div class="shot-label">
                            <span>🎯 ${escHtml(s.shot_name || `镜头 ${si + 1}`)}</span>
                            <div style="display:flex;gap:4px;align-items:center;">
                                <span class="tag-edited" style="display:none;" id="editedTag-${gi}-${si}">✏️ 已修改</span>
                                <button class="btn btn-sm btn-outline btn-copy-prompt" data-prompt="${escHtml(s.prompt || '')}" style="font-size:11px;">📋 复制</button>
                            </div>
                        </div>
                        <div class="editable-field"
                             data-path="optimized_prompts.${gi}.shots.${si}.prompt"
                             data-prompt-modal="true"
                             data-gi="${gi}" data-si="${si}"
                             data-full-prompt="${escHtml(s.prompt || '')}"
                             data-shot-name="${escHtml(s.shot_name || `镜头 ${si + 1}`)}"
                             data-group-name="${escHtml(g.group_name || '')}"
                             data-dialogue="${escHtml(s.dialogue || '')}"
                             data-description="${escHtml(s.description || '')}">
                            <div class="view-mode" style="font-size:13px;color:var(--text);padding:10px 12px;background:var(--card-bg);border:1px solid var(--border);border-radius:6px;cursor:pointer;white-space:pre-wrap;word-break:break-word;max-height:100px;overflow-y:auto;line-height:1.5;" title="点击查看/编辑提示词">
                                ${escHtml((s.prompt || s.description || '(无提示词)').substring(0, 200))}${(s.prompt || '').length > 200 ? '...' : ''}
                            </div>
                        </div>
                        ${s.description ? `<div class="text-sm text-muted" style="margin-top:4px;">📝 ${escHtml(s.description.substring(0, 80))}</div>` : ''}
                        ${s.dialogue ? `<div class="text-sm" style="color:var(--primary);margin-top:4px;">💬 ${escHtml(s.dialogue.substring(0, 60))}</div>` : ''}
                    </div>
                `).join('')}
            </div>
        `).join('');
    }

    // ═══════════════════════════════════════════════════════════════
    // 编辑模式
    // ═══════════════════════════════════════════════════════════════

    function enterEditMode(field) {
        field.classList.add('editing');
        const textarea = field.querySelector('textarea, input');
        if (textarea) textarea.focus();
    }

    async function saveEdit(field) {
        const dataPath = field.dataset.path;
        const inputs = field.querySelectorAll('[data-field]');
        let finalPath = dataPath;

        if (inputs.length === 0) {
            // Simple field: target is the path itself
            // For simple textarea that doesn't have data-field, we need to figure out the value
            const textarea = field.querySelector('textarea, input');
            if (!textarea) return;

            const value = textarea.value;
            await API.updateField(projectId, dataPath, value);
            showToast('已保存');
            field.classList.remove('editing');
            reloadAfterEdit(dataPath);
            return;
        }

        // Multiple sub-fields (e.g., name + description)
        for (const input of inputs) {
            const subField = input.dataset.field;
            const fullPath = `${dataPath}.${subField}`;
            const value = input.value;
            await API.updateField(projectId, fullPath, value);
        }
        showToast('已保存');
        field.classList.remove('editing');
        reloadAfterEdit(dataPath);
    }

    function cancelEdit(field) {
        field.classList.remove('editing');
    }

    async function reloadAfterEdit(fieldPath) {
        // Mark the step as having been edited
        const stepName = fieldPathToStep(fieldPath);
        if (stepName) {
            const summaryEl = document.getElementById(`summary-${stepName}`);
            if (summaryEl && !summaryEl.querySelector('.tag-edited')) {
                const tag = document.createElement('span');
                tag.className = 'tag-edited';
                tag.textContent = '✏️ 已修改';
                summaryEl.appendChild(tag);
            }
            // Reload the step detail to show updated values
            loadStepDetail(stepName);
        }
    }

    function fieldPathToStep(fieldPath) {
        const map = {
            'parsed_characters': 'parse_docx',
            'character_assets': 'generate_asset_package',
            'scene_assets': 'generate_asset_package',
            'prop_assets': 'generate_asset_package',
            'shot_groups': 'step1_storyboard',
            'consistency_anchors': 'step2_consistency',
            'optimized_prompts': 'step3_optimize_prompts',
        };
        for (const [prefix, step] of Object.entries(map)) {
            if (fieldPath.startsWith(prefix)) return step;
        }
        return null;
    }

    // ═══════════════════════════════════════════════════════════════
    // Lightbox
    // ═══════════════════════════════════════════════════════════════

    function openLightbox(src) {
        const overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.innerHTML = `<img src="${src}" alt="">`;
        overlay.addEventListener('click', () => overlay.remove());
        document.addEventListener('keydown', function closeOnEsc(e) {
            if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', closeOnEsc); }
        });
        document.body.appendChild(overlay);
    }

    // ═══════════════════════════════════════════════════════════════
    // Prompt Modal — 弹窗查看/编辑/复制提示词
    // ═══════════════════════════════════════════════════════════════

    function openPromptModal(field) {
        const dataPath = field.dataset.path;
        const gi = field.dataset.gi;
        const si = field.dataset.si;
        const shotName = field.dataset.shotName || '提示词';
        const groupName = field.dataset.groupName || '';
        const dialogue = field.dataset.dialogue || '';
        const description = field.dataset.description || '';
        // Get full prompt text from data attribute (not truncated view-mode text)
        const viewMode = field.querySelector('.view-mode');
        const promptText = field.dataset.fullPrompt || (viewMode ? viewMode.textContent.trim() : '');

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay wide';
        overlay.innerHTML = `
            <div class="modal">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
                    <div>
                        <h3 style="margin:0;">✏️ 提示词</h3>
                        <div class="prompt-meta-row" style="margin-top:6px;margin-bottom:0;">
                            <strong>${escHtml(shotName)}</strong>
                            ${groupName ? `<span>· ${escHtml(groupName)}</span>` : ''}
                            ${dialogue ? `<span style="color:var(--primary);">· 💬 ${escHtml(dialogue)}</span>` : ''}
                            ${description ? `<span style="color:var(--text-muted);">· ${escHtml(description)}</span>` : ''}
                        </div>
                    </div>
                    <button class="btn btn-outline btn-sm" id="modalClose" style="font-size:18px;padding:4px 10px;">✕</button>
                </div>
                <div class="modal-body">
                    <div id="promptViewArea">
                        <pre class="prompt-display" id="promptDisplay">${escHtml(promptText || '(无提示词)')}</pre>
                    </div>
                    <div id="promptEditArea" class="hidden">
                        <textarea class="prompt-display-edit" id="promptTextarea">${escHtml(promptText)}</textarea>
                    </div>
                </div>
                <div class="modal-actions" style="display:flex;align-items:center;gap:8px;">
                    <button class="btn-copy-lg" id="modalCopyBtn">📋 复制提示词</button>
                    <span style="flex:1;"></span>
                    <button class="btn btn-outline btn-sm hidden" id="modalEditBtn" style="font-size:13px;">✏️ 编辑</button>
                    <button class="btn btn-outline btn-sm hidden" id="modalCancelBtn">取消编辑</button>
                    <button class="btn btn-primary btn-sm hidden" id="modalSaveBtn">💾 保存</button>
                </div>
            </div>
        `;

        document.body.appendChild(overlay);

        const closeModal = () => overlay.remove();
        overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });
        document.addEventListener('keydown', function escHandler(e) {
            if (e.key === 'Escape') { closeModal(); document.removeEventListener('keydown', escHandler); }
        });

        // Elements
        const closeBtn = overlay.querySelector('#modalClose');
        const copyBtn = overlay.querySelector('#modalCopyBtn');
        const editBtn = overlay.querySelector('#modalEditBtn');
        const cancelBtn = overlay.querySelector('#modalCancelBtn');
        const saveBtn = overlay.querySelector('#modalSaveBtn');
        const viewArea = overlay.querySelector('#promptViewArea');
        const editArea = overlay.querySelector('#promptEditArea');
        const display = overlay.querySelector('#promptDisplay');
        const textarea = overlay.querySelector('#promptTextarea');

        closeBtn.addEventListener('click', closeModal);

        // Copy
        copyBtn.addEventListener('click', () => {
            const text = textarea.classList.contains('hidden') ? display.textContent : textarea.value;
            navigator.clipboard.writeText(text).then(() => {
                copyBtn.innerHTML = '✓ 已复制';
                copyBtn.style.background = '#065f46';
                setTimeout(() => {
                    copyBtn.innerHTML = '📋 复制提示词';
                    copyBtn.style.background = '';
                }, 2000);
            }).catch(() => showToast('复制失败', 'error'));
        });

        // Edit mode
        editBtn.classList.remove('hidden');
        editBtn.addEventListener('click', () => {
            viewArea.classList.add('hidden');
            editArea.classList.remove('hidden');
            editBtn.classList.add('hidden');
            cancelBtn.classList.remove('hidden');
            saveBtn.classList.remove('hidden');
            textarea.focus();
        });

        // Cancel edit
        cancelBtn.addEventListener('click', () => {
            viewArea.classList.remove('hidden');
            editArea.classList.add('hidden');
            editBtn.classList.remove('hidden');
            cancelBtn.classList.add('hidden');
            saveBtn.classList.add('hidden');
        });

        // Save
        saveBtn.addEventListener('click', async () => {
            const newValue = textarea.value;
            saveBtn.disabled = true;
            saveBtn.textContent = '⏳ 保存中...';
            try {
                await API.updateField(projectId, dataPath, newValue);
                // Update the view display
                display.textContent = newValue || '(无提示词)';
                // Update data attribute so future modal opens get updated text
                field.dataset.fullPrompt = newValue;
                // Update the original view-mode in the page
                if (viewMode) {
                    viewMode.textContent = (newValue || '(无提示词)').substring(0, 200) + (newValue.length > 200 ? '...' : '');
                }
                viewArea.classList.remove('hidden');
                editArea.classList.add('hidden');
                editBtn.classList.remove('hidden');
                cancelBtn.classList.add('hidden');
                saveBtn.classList.add('hidden');
                saveBtn.textContent = '💾 保存';
                showToast('已保存');
                // Reload step detail to keep everything in sync
                reloadAfterEdit(dataPath);
            } catch (e) {
                showToast('保存失败: ' + e.message, 'error');
                saveBtn.textContent = '💾 保存';
            }
            saveBtn.disabled = false;
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // 拖拽排序
    // ═══════════════════════════════════════════════════════════════

    function initDragDrop() {
        const grid = document.getElementById('shotCardsGrid');
        if (!grid) return;

        let dragSrc = null;

        grid.addEventListener('dragstart', e => {
            const card = e.target.closest('.shot-card');
            if (!card) return;
            dragSrc = card;
            card.style.opacity = '0.5';
        });

        grid.addEventListener('dragend', e => {
            const card = e.target.closest('.shot-card');
            if (card) card.style.opacity = '1';
            dragSrc = null;
            grid.querySelectorAll('.drag-over').forEach(c => c.classList.remove('drag-over'));
        });

        grid.addEventListener('dragover', e => {
            e.preventDefault();
            const card = e.target.closest('.shot-card');
            if (card && card !== dragSrc) {
                card.classList.add('drag-over');
            }
        });

        grid.addEventListener('dragleave', e => {
            const card = e.target.closest('.shot-card');
            if (card) card.classList.remove('drag-over');
        });

        grid.addEventListener('drop', async e => {
            e.preventDefault();
            const target = e.target.closest('.shot-card');
            if (!target || target === dragSrc || !dragSrc) return;

            const srcGroup = parseInt(dragSrc.dataset.group);
            const srcShot = parseInt(dragSrc.dataset.shot);
            const dstGroup = parseInt(target.dataset.group);
            const dstShot = parseInt(target.dataset.shot);

            // Swap in the state data
            const state = project.state || {};
            const groups = state.shot_groups || [];
            if (groups[srcGroup] && groups[srcGroup].shots && groups[dstGroup] && groups[dstGroup].shots) {
                const srcData = groups[srcGroup].shots[srcShot];
                const dstData = groups[dstGroup].shots[dstShot];

                // Save both
                try {
                    await API.updateField(projectId, `shot_groups.${srcGroup}.shots.${srcShot}`, dstData);
                    await API.updateField(projectId, `shot_groups.${dstGroup}.shots.${dstShot}`, srcData);
                    showToast('镜头顺序已调整');
                    // Reload project data
                    project = await API.getProject(projectId);
                    loadStepDetail('step1_storyboard');
                } catch (e) {
                    showToast('排序失败: ' + e.message, 'error');
                }
            }
        });
    }

    // ═══════════════════════════════════════════════════════════════
    // 预览面板事件
    // ═══════════════════════════════════════════════════════════════

    function bindPreviewEvents(stepMap) {
        // File upload
        const fileUpload = document.getElementById('fileUpload');
        const fileInput = document.getElementById('fileInput');
        if (fileUpload && fileInput) {
            fileUpload.addEventListener('click', () => fileInput.click());
            fileInput.addEventListener('change', handleFileSelect);
        }

        // Step buttons (run/redo)
        document.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                e.stopPropagation();
                const action = btn.dataset.action;
                const step = btn.dataset.step;
                if (action === 'run') await runStep(step);
                else if (action === 'redo') await redoStep(step);
            });
        });

        // Click step to expand/collapse — only from header area
        document.querySelectorAll('.step-item').forEach(item => {
            item.addEventListener('click', (e) => {
                // Only toggle on clicks in the header area (step-indicator + step-body, but NOT step-detail)
                const inDetail = e.target.closest('.step-detail');
                const inActions = e.target.closest('.step-actions');
                const isButton = e.target.closest('button');
                const isUploadZone = e.target.closest('.upload-zone');
                const isEditable = e.target.closest('.editable-field');
                if (inDetail || isButton || isUploadZone || isEditable) return;
                if (inActions) return; // Don't toggle when clicking action buttons area

                item.classList.toggle('expanded');
                const step = item.dataset.step;
                const detailEl = document.getElementById(`detail-${step}`);
                if (item.classList.contains('expanded') && detailEl && detailEl.textContent.includes('加载中')) {
                    loadStepDetail(step);
                }
                if (step === 'step1_storyboard') {
                    setTimeout(initDragDrop, 100);
                }
            });
        });
    }

    async function handleFileSelect(e) {
        const file = e.target.files[0];
        if (!file || !file.name.endsWith('.docx')) {
            document.getElementById('uploadStatus').innerHTML =
                '<span style="color:var(--danger);">请选择 .docx 格式文件</span>';
            return;
        }

        const statusEl = document.getElementById('uploadStatus');
        const uploadEl = document.getElementById('fileUpload');

        statusEl.innerHTML = '<span class="spinner spinner-dark" style="width:14px;height:14px;"></span> 上传中...';
        try {
            await API.uploadScript(projectId, file);
            uploadEl.classList.add('has-file');
            uploadEl.querySelector('.file-upload-icon').textContent = '✓';
            uploadEl.querySelector('.file-upload-text').textContent = file.name;
            statusEl.innerHTML = '<span style="color:var(--success);">✓ 上传成功</span>';

            project = await API.getProject(projectId);
            renderPreviewPanel();

            // Auto run step 1
            const steps = project.steps || [];
            const stepMap = {};
            steps.forEach(s => { stepMap[s.step_name] = s.status; });
            if (stepMap['parse_docx'] === 'pending') {
                await runStep('parse_docx');
            }

        } catch (e) {
            statusEl.innerHTML = `<span style="color:var(--danger);">上传失败: ${escHtml(e.message)}</span>`;
        }
    }

    async function runStep(stepName) {
        const stepEl = document.getElementById(`step-${stepName}`);
        if (stepEl) {
            stepEl.classList.remove('pending', 'failed');
            stepEl.classList.add('running');
            stepEl.querySelector('.step-indicator').textContent = '⏳';
            const actions = stepEl.querySelector('.step-actions');
            if (actions) actions.innerHTML = '<span class="text-sm text-muted">执行中...</span>';
        }

        try {
            await API.runStep(projectId, stepName);
        } catch (e) {
            showToast(`${stepName} 执行失败: ${e.message}`, 'error');
        }

        project = await API.getProject(projectId);
        renderPreviewPanel();
        renderGeneratePanel();

        // Auto-expand and scroll
        const newStepEl = document.getElementById(`step-${stepName}`);
        if (newStepEl) {
            newStepEl.classList.add('expanded');
            setTimeout(() => newStepEl.scrollIntoView({ behavior: 'smooth', block: 'center' }), 100);
            loadStepDetail(stepName);
            if (stepName === 'step1_storyboard') setTimeout(initDragDrop, 200);
        }
    }

    async function redoStep(stepName) {
        if (!confirm(`确定要重新执行「${STEP_DEFS.find(s => s.key === stepName)?.label || stepName}」吗？后续步骤结果将被清除。`)) return;

        try {
            await API.redoStep(projectId, stepName);
        } catch (e) {
            alert('重置失败: ' + e.message);
            return;
        }

        project = await API.getProject(projectId);
        renderPreviewPanel();
        renderGeneratePanel();
        await runStep(stepName);
    }

    // ═══════════════════════════════════════════════════════════════
    // 生成面板
    // ═══════════════════════════════════════════════════════════════

    function renderGeneratePanel() {
        const panel = document.getElementById('generatePanel');
        if (!panel) return;

        const steps = project.steps || [];
        const stepMap = {};
        steps.forEach(s => { stepMap[s.step_name] = s.status; });

        const allPreviewDone = STEP_DEFS.filter(s => s.phase === 'preview')
            .every(s => stepMap[s.key] === 'completed');

        if (!allPreviewDone) {
            panel.innerHTML = `
                <div class="card panel-locked">
                    <span class="panel-locked-icon">🔒</span>
                    <p class="panel-locked-text">请先完成左侧剧本处理步骤</p>
                    <p class="text-sm text-muted mt-2">完成所有预览步骤后，这里将解锁视频生成功能</p>
                </div>
            `;
            return;
        }

        const genStatus = stepMap['generate_videos'] || 'pending';
        const mergeStatus = stepMap['merge_videos'] || 'pending';
        const state = project.state || {};
        const segs = state.video_segments || [];
        const prompts = state.optimized_prompts || [];
        const totalShots = prompts.reduce((sum, g) => sum + (g.shots || []).length, 0);
        const estimateCost = totalShots * 3;

        panel.innerHTML = `
            <div class="card">
                <h3 class="card-title mb-4">🎥 视频生成</h3>

                ${genStatus === 'pending' ? `
                <div class="cost-breakdown">
                    <div class="cost-row"><span>总镜头数</span><span>${totalShots} 个</span></div>
                    <div class="cost-row"><span>预估单价</span><span>≈ ¥3.00 / 条</span></div>
                    <div class="cost-row total"><span>预估费用</span><span>≈ ¥${estimateCost.toFixed(2)}</span></div>
                </div>
                <div class="confirm-dialog">
                    <strong>⚠️ 即将调用视频生成 API</strong><br>
                    将生成 ${totalShots} 个视频片段。已生成的片段不会因失败丢失。
                </div>
                <button class="btn btn-primary btn-lg btn-block" id="btnGenerateVideos">
                    🎥 确认生成视频（¥${estimateCost.toFixed(2)}）
                </button>
                ` : ''}

                ${genStatus === 'running' ? `
                <div class="text-center" style="padding:20px;">
                    <span class="spinner spinner-dark" style="width:32px;height:32px;"></span>
                    <p class="mt-2">视频生成中...</p>
                    <div class="progress-bar mt-2"><div class="progress-fill" style="width:${genProgress(segs)}%"></div></div>
                    <p class="text-sm text-muted mt-2">${segs.filter(s => s.status === 'completed').length}/${segs.length} 已完成</p>
                </div>
                ` : ''}

                ${genStatus === 'completed' ? `
                ${(() => {
                    const completed = segs.filter(s => s.status === 'completed');
                    const pendingUp = segs.filter(s => s.status === 'pending_upload');
                    const failed = segs.filter(s => s.status === 'failed' && s.status !== 'pending_upload');
                    return `
                    <div class="alert alert-success">✓ 视频生成完成 — ${completed.length} 个片段成功${pendingUp.length ? `，${pendingUp.length} 个待手动上传` : ''}${failed.length ? `，${failed.length} 个失败` : ''}</div>
                    <div class="section-label">视频片段</div>
                    ${completed.slice(0, 8).map(s => `
                    <div class="video-segment">
                        <div class="text-sm" style="font-weight:600;">${escHtml(s.shot_id || s.segment_id)}</div>
                        ${s.video_path ? `<video controls src="${API.fileUrl(projectId, s.video_path)}" preload="metadata" style="width:100%;max-height:200px;border-radius:4px;"></video>` : ''}
                    </div>
                    `).join('')}
                    ${pendingUp.map(s => `
                    <div class="video-segment" style="border:2px dashed var(--warning);background:#fffbeb;">
                        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
                            <span style="font-weight:600;">${escHtml(s.shot_id || s.segment_id)}</span>
                            <span class="badge" style="background:#fef3c7;color:#92400e;">⏳ 待上传</span>
                        </div>
                        <div class="upload-zone" style="height:70px;margin-bottom:6px;">
                            <span class="upload-zone-icon">📤</span>
                            <span class="upload-zone-text">上传视频文件</span>
                            <input type="file" accept="video/*" class="upload-input" onchange="window._videoUpload(event, '${projectId}', '${s.segment_id}')">
                        </div>
                        <div style="font-size:12px;color:var(--text-secondary);background:#1a1a2e;color:#a7f3d0;padding:10px;border-radius:4px;word-break:break-all;max-height:120px;overflow-y:auto;margin-bottom:6px;line-height:1.5;white-space:pre-wrap;">${escHtml((s.prompt || '').substring(0, 300))}${(s.prompt || '').length > 300 ? '...' : ''}</div>
                        <button class="btn btn-sm btn-copy-prompt-panel" data-prompt="${escHtml(s.prompt || '')}" style="font-size:12px;background:var(--success);color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-weight:600;">📋 复制提示词</button>
                    </div>
                    `).join('')}
                    `;
                })()}

                ${mergeStatus === 'pending' ? `
                <button class="btn btn-success btn-lg btn-block mt-4" id="btnMergeVideos">
                    🎞️ 合并最终视频
                </button>
                ` : ''}

                ${mergeStatus === 'completed' ? `
                <div class="alert alert-success mt-4">✓ 视频合并完成</div>
                ${state.final_video_path ? `
                <video controls src="${API.fileUrl(projectId, state.final_video_path)}" style="width:100%;border-radius:8px;" preload="metadata"></video>
                <a href="${API.fileUrl(projectId, state.final_video_path)}" download class="btn btn-primary btn-block mt-2">⬇ 下载最终视频</a>` : ''}
                ` : ''}

                ${genStatus === 'failed' ? `
                <div class="alert alert-error">生成失败: ${escHtml((segs.find(s => s.status === 'failed') || {}).error || '未知错误')}</div>
                <button class="btn btn-warning btn-block" id="btnRetryVideos">🔁 重试视频生成</button>
                ` : ''}
                ` : ''}
            </div>
        `;

        bindGenerateEvents(genStatus, mergeStatus);
    }

    function genProgress(segs) {
        if (!segs || !segs.length) return 0;
        return Math.round(segs.filter(s => s.status === 'completed').length / segs.length * 100);
    }

    function bindGenerateEvents(genStatus, mergeStatus) {
        const btnGen = document.getElementById('btnGenerateVideos');
        const btnMerge = document.getElementById('btnMergeVideos');
        const btnRetry = document.getElementById('btnRetryVideos');

        if (btnGen) {
            btnGen.addEventListener('click', async () => {
                btnGen.disabled = true;
                btnGen.textContent = '⏳ 提交中...';
                await runStep('generate_videos');
            });
        }
        if (btnMerge) {
            btnMerge.addEventListener('click', async () => {
                btnMerge.disabled = true;
                btnMerge.textContent = '⏳ 合并中...';
                await runStep('merge_videos');
            });
        }
        if (btnRetry) {
            btnRetry.addEventListener('click', async () => {
                await redoStep('generate_videos');
            });
        }

        // Copy prompt buttons (panel)
        panel.querySelectorAll('.btn-copy-prompt-panel').forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt || '';
                navigator.clipboard.writeText(prompt).then(() => {
                    btn.textContent = '✓ 已复制';
                    btn.style.background = '#065f46';
                    setTimeout(() => { btn.textContent = '📋 复制提示词'; btn.style.background = ''; }, 2000);
                }).catch(() => showToast('复制失败', 'error'));
            });
        });
        panel.querySelectorAll('.btn-copy-prompt').forEach(btn => {
            btn.addEventListener('click', () => {
                const prompt = btn.dataset.prompt || '';
                navigator.clipboard.writeText(prompt).then(() => showToast('提示词已复制')).catch(() => showToast('复制失败', 'error'));
            });
        });
    }

    async function duplicateProject() {
        const name = (project.name || project.episode_title || '') + ' (副本)';
        try {
            const r = await API.duplicateProject(projectId, name);
            showToast('项目已复制');
            Router.navigate(`workflow/${r.new_id}`);
        } catch (e) {
            showToast('复制失败: ' + e.message, 'error');
        }
    }

    function statusIcon(status) {
        const map = { pending: '○', running: '⏳', completed: '✓', failed: '✗' };
        return map[status] || '○';
    }

    function formatDuration(started, finished) {
        if (!started || !finished) return '';
        const s = new Date(started), f = new Date(finished);
        const sec = Math.round((f - s) / 1000);
        if (sec < 60) return `${sec}秒`;
        return `${Math.floor(sec/60)}分${sec%60}秒`;
    }

    render();

    // Expose for inline handlers
    window._currentWorkflow = { reloadProject: loadProject, projectId };

    return () => {
        document.removeEventListener('keydown', handleKeyboard);
        Object.values(autoSaveTimers).forEach(t => clearTimeout(t));
    };
}
