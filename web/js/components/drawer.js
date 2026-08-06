/**
 * Drawer — 右侧滑出面板（用于聚焦编辑，不打断列表布局）。
 *
 * open({ title, subtitle, bodyHtml, onMount, onClose }) -> handle
 *   title:    抬头标题
 *   subtitle: 抬头副标题（可选）
 *   bodyHtml: 面板主体 HTML 字符串
 *   onMount(bodyEl, handle): 面板挂载后回调，用于绑定事件（返回值忽略）
 *   onClose(): 关闭时回调（可选）
 *
 * handle: { close(), setBody(html), bodyEl, root }
 *
 * 特性：遮罩点击关闭、Esc 关闭、进出滑动动画、关闭时统一移除监听避免泄漏。
 * 同一时刻只保留一个 Drawer（打开新的会先关旧的）。
 */
(function () {
    let current = null;

    function open(opts) {
        if (current) current.close();

        const overlay = document.createElement('div');
        overlay.className = 'drawer-overlay';
        overlay.innerHTML = `
            <div class="drawer-panel" role="dialog" aria-modal="true">
                <div class="drawer-head">
                    <div class="drawer-head-text">
                        <div class="drawer-title">${opts.title || ''}</div>
                        ${opts.subtitle ? `<div class="drawer-subtitle">${opts.subtitle}</div>` : ''}
                    </div>
                    <button class="drawer-close" data-role="drawer-close" aria-label="关闭">✕</button>
                </div>
                <div class="drawer-body" data-role="drawer-body">${opts.bodyHtml || ''}</div>
            </div>`;
        document.body.appendChild(overlay);

        const panel = overlay.querySelector('.drawer-panel');
        const bodyEl = overlay.querySelector('[data-role="drawer-body"]');

        let closed = false;
        function close() {
            if (closed) return;
            closed = true;
            document.removeEventListener('keydown', onKey);
            if (typeof handle._cleanup === 'function') { try { handle._cleanup(); } catch (e) {} }
            overlay.classList.remove('open');
            // 等滑出动画结束再移除节点
            setTimeout(() => { overlay.remove(); }, 220);
            if (current === handle) current = null;
            if (typeof opts.onClose === 'function') { try { opts.onClose(); } catch (e) {} }
        }

        function onKey(e) { if (e.key === 'Escape') close(); }
        function onOverlayClick(e) { if (e.target === overlay) close(); }

        overlay.addEventListener('click', onOverlayClick);
        overlay.querySelector('[data-role="drawer-close"]').addEventListener('click', close);
        document.addEventListener('keydown', onKey);

        const handle = {
            close,
            root: overlay,
            bodyEl,
            setBody(html) { bodyEl.innerHTML = html; },
        };
        current = handle;

        // 触发进入动画（下一帧加 open 类）
        requestAnimationFrame(() => { requestAnimationFrame(() => overlay.classList.add('open')); });

        if (typeof opts.onMount === 'function') {
            try { opts.onMount(bodyEl, handle); } catch (e) {}
        }
        return handle;
    }

    window.Components = window.Components || {};
    window.Components.Drawer = { open };
})();
