/**
 * ShotCard — 分镜镜头卡片。
 *
 * render(shot) -> htmlString
 *   shot: { shot_id, groupName, groupIdx, shotIdx, content, dialogue, shot_type, framing, visual_style }
 *   内部复用 window.Components.EditableField 渲染可编辑字段。
 *
 * 事件（编辑、拖拽）由父容器统一委托，卡片本身只产出结构。
 */
(function () {
    const E = window.Utils.escHtml;
    const A = window.Utils.escAttr;

    function render(shot) {
        const EF = window.Components.EditableField;
        const base = `shot_groups.${shot.groupIdx}.shots.${shot.shotIdx}`;
        return `
        <div class="shot-card" draggable="true" data-group="${shot.groupIdx}" data-shot="${shot.shotIdx}"
             id="shotCard-${shot.groupIdx}-${shot.shotIdx}">
            <div class="shot-card-header">
                <span class="drag-handle" title="拖拽调整顺序">⠿</span>
                <span class="shot-card-id">${E(shot.shot_id || '')}</span>
                <span class="shot-card-group">${E(shot.groupName || '')}</span>
            </div>
            <div class="shot-card-section">
                ${EF.render({ path: `${base}.content`, value: shot.content || shot.description || '', type: 'textarea', lines: 4, minHeight: 60, placeholder: '镜头画面描述' })}
            </div>
            ${shot.dialogue !== undefined ? `
            <div class="shot-card-section shot-card-dialogue-wrap">
                <span class="shot-card-tag">💬 台词</span>
                ${EF.render({ path: `${base}.dialogue`, value: shot.dialogue || '', type: 'textarea', lines: 2, minHeight: 44, placeholder: '（无台词）' })}
            </div>` : ''}
            <div class="shot-card-meta">
                ${shot.shot_type ? `<span>🎥 ${E(shot.shot_type)}</span>` : ''}
                ${shot.framing ? `<span>📐 ${E(shot.framing)}</span>` : ''}
                ${shot.visual_style ? `<span title="${A(shot.visual_style)}">🎨 ${E(shot.visual_style)}</span>` : ''}
            </div>
        </div>`;
    }

    window.Components = window.Components || {};
    window.Components.ShotCard = { render };
})();
