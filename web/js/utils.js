/**
 * 公共工具函数 — 被各视图与组件共享。
 *
 * 全部挂在 window.Utils 命名空间下（无构建工具，靠 <script> 顺序加载）。
 */
(function () {
    // ─── HTML 转义 ────────────────────────────────────────────────
    function escHtml(s) {
        if (s === null || s === undefined) return '';
        const el = document.createElement('span');
        el.textContent = String(s);
        return el.innerHTML;
    }

    // ─── 属性值转义（用于 data-* / value）───────────────────────────
    function escAttr(s) {
        return escHtml(s).replace(/"/g, '&quot;');
    }

    // ─── Debounce ─────────────────────────────────────────────────
    function debounce(fn, ms) {
        let timer;
        return function (...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    }

    // ─── 耗时格式化 ────────────────────────────────────────────────
    function formatDuration(started, finished) {
        if (!started || !finished) return '';
        const s = new Date(started), f = new Date(finished);
        const sec = Math.round((f - s) / 1000);
        if (sec < 60) return `${sec}秒`;
        return `${Math.floor(sec / 60)}分${sec % 60}秒`;
    }

    // ─── 日期格式化 ────────────────────────────────────────────────
    function pad(n) { return String(n).padStart(2, '0'); }
    function formatDate(iso) {
        if (!iso) return '-';
        const d = new Date(iso);
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    // ─── Toast ────────────────────────────────────────────────────
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

    // ─── Lightbox ─────────────────────────────────────────────────
    function openLightbox(src) {
        const overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.innerHTML = `<img src="${escAttr(src)}" alt="">`;
        const close = () => { overlay.remove(); document.removeEventListener('keydown', onEsc); };
        const onEsc = (e) => { if (e.key === 'Escape') close(); };
        overlay.addEventListener('click', close);
        document.addEventListener('keydown', onEsc);
        document.body.appendChild(overlay);
    }

    // ─── 复制到剪贴板 ──────────────────────────────────────────────
    // 兼容非安全上下文 / 旧浏览器：优先 navigator.clipboard，回退 execCommand。
    function writeClipboard(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise((resolve, reject) => {
            try {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                const ok = document.execCommand('copy');
                ta.remove();
                ok ? resolve() : reject(new Error('execCommand copy failed'));
            } catch (e) { reject(e); }
        });
    }

    function copyText(text, okMsg = '已复制') {
        return writeClipboard(text)
            .then(() => { showToast(okMsg); return true; })
            .catch(() => { showToast('复制失败，请手动选中文本复制', 'error'); return false; });
    }

    /**
     * 从按钮触发复制，并在按钮上给出即时视觉反馈（✓ 已复制 + 绿色），
     * 无需切走视线看 toast —— 更友好的复制体验。
     * @param {HTMLElement} btn  被点击的复制按钮
     * @param {string} text      要复制的文本
     * @param {string} okMsg     可选，toast 文案（默认「已复制」）
     */
    function copyFromButton(btn, text, okMsg = '已复制') {
        return writeClipboard(text).then(() => {
            showToast(okMsg);
            if (!btn || btn.dataset.copying === '1') return true;
            const original = btn.innerHTML;
            btn.dataset.copying = '1';
            btn.classList.add('copied');
            btn.innerHTML = '<span class="copy-ico">✓</span> 已复制';
            setTimeout(() => {
                btn.classList.remove('copied');
                btn.innerHTML = original;
                delete btn.dataset.copying;
            }, 1600);
            return true;
        }).catch(() => {
            showToast('复制失败，请手动选中文本复制', 'error');
            return false;
        });
    }

    window.Utils = {
        escHtml, escAttr, debounce, formatDuration, formatDate,
        showToast, openLightbox, copyText, copyFromButton,
    };

    // 兼容旧全局调用（逐步迁移期间保留）
    window.showToast = showToast;
})();
