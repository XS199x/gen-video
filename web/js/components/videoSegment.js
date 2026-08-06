/**
 * VideoSegment — 单个视频片段卡片（已生成 / 待手动上传）。
 *
 * render(seg, ctx) -> htmlString
 *   seg: { segment_id, shot_id, status, video_path, prompt }
 *   ctx: { projectId }
 *
 * 上传事件由父容器委托：input[data-action="upload-segment"][data-segment]
 */
(function () {
    const E = window.Utils.escHtml;
    const A = window.Utils.escAttr;

    function render(seg, ctx) {
        const projectId = ctx.projectId;
        const id = seg.shot_id || seg.segment_id;

        if (seg.status === 'pending_upload') {
            return `
            <div class="video-segment pending">
                <div class="video-segment-head">
                    <span style="font-weight:600;">${E(id)}</span>
                    <span class="badge" style="background:#fef3c7;color:#92400e;">⏳ 待上传</span>
                </div>
                <label class="upload-zone" style="height:70px;">
                    <span class="upload-zone-icon">📤</span>
                    <span class="upload-zone-text">上传视频文件</span>
                    <input type="file" accept="video/*" class="upload-input"
                           data-action="upload-segment" data-segment="${A(seg.segment_id)}">
                </label>
                ${seg.prompt ? `
                <div class="video-segment-prompt">${E(seg.prompt)}</div>
                <button class="btn-copy" data-action="copy" data-copy="${A(seg.prompt)}" style="margin-top:6px;" title="复制提示词"><span class="copy-ico">📋</span> 复制提示词</button>` : ''}
            </div>`;
        }

        return `
        <div class="video-segment">
            <div class="video-segment-head"><span style="font-weight:600;">${E(id)}</span></div>
            ${seg.video_path ? `<video controls src="${A(API.fileUrl(projectId, seg.video_path))}" preload="metadata"></video>` : ''}
        </div>`;
    }

    window.Components = window.Components || {};
    window.Components.VideoSegment = { render };
})();
