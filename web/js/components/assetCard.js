/**
 * AssetCard — 角色 / 场景 / 道具 资产卡片（展示态，点击进入侧边抽屉编辑）。
 *
 * render(asset, index, category, ctx) -> htmlString
 *   asset:    { name, description, prompt, image_path, image_generated, image_status }
 *   category: 'character_assets' | 'scene_assets' | 'prop_assets'
 *   ctx:      { projectId }
 *
 * 卡片本身不含表单：整卡可点击，父容器委托 data-action="edit-asset" 打开抽屉。
 * 图片区固定为小缩略图，未生成时显示占位图标 —— 内容（名称/描述）占主位。
 */
(function () {
    const E = window.Utils.escHtml;
    const A = window.Utils.escAttr;

    // 图片状态 → 徽标文案 / 样式
    function statusBadge(imgStatus) {
        switch (imgStatus) {
            case 'generated': return { text: '已生成', cls: 'ok' };
            case 'manual_upload': return { text: '已上传', cls: 'ok' };
            case 'failed': return { text: '生成失败', cls: 'err' };
            case 'api_unavailable': return { text: '待上传', cls: 'warn' };
            default: return { text: '待上传', cls: 'warn' };
        }
    }

    function render(asset, index, category, ctx) {
        const projectId = ctx.projectId;
        const imgSrc = asset.image_path ? API.fileUrl(projectId, asset.image_path) : '';
        const hasImage = imgSrc && (asset.image_generated || asset.image_status === 'manual_upload');
        const imgStatus = asset.image_status || (asset.image_generated ? 'generated' : 'pending_upload');
        const badge = statusBadge(imgStatus);

        const thumb = hasImage
            ? `<img src="${A(imgSrc)}" alt="${A(asset.name)}" loading="lazy">`
            : `<span class="asset-thumb-ph">🖼️</span>`;

        const desc = asset.description || '';

        return `
        <div class="asset-card" data-action="edit-asset" data-category="${A(category)}" data-index="${index}"
             role="button" tabindex="0" title="点击编辑">
            <div class="asset-thumb ${hasImage ? '' : 'empty'}">${thumb}
                <span class="asset-thumb-badge ${badge.cls}">${badge.text}</span>
            </div>
            <div class="asset-card-info">
                <div class="asset-card-name">${E(asset.name) || '<span class="text-muted">未命名</span>'}</div>
                <div class="asset-card-desc">${desc ? E(desc) : '<span class="text-muted">暂无描述</span>'}</div>
            </div>
            <span class="asset-card-edit">✏️ 编辑</span>
        </div>`;
    }

    window.Components = window.Components || {};
    window.Components.AssetCard = { render };
})();
