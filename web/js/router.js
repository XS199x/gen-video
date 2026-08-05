/**
 * 简易 Hash 路由器。
 *
 * 路由:
 *   #setup            — API Key 配置
 *   #projects         — 项目列表
 *   #workflow/{id}    — 工作流操作中心
 */

const Router = {
    _routes: {},
    _currentView: null,
    _currentCleanup: null,

    on(hash, handler) {
        this._routes[hash] = handler;
    },

    start() {
        window.addEventListener('hashchange', () => this._dispatch());
        this._dispatch();
    },

    navigate(hash) {
        window.location.hash = hash;
    },

    _dispatch() {
        const hash = window.location.hash || '#setup';
        const [base, ...rest] = hash.substring(1).split('/');
        const path = rest.join('/');

        // 清理上一个视图
        if (this._currentCleanup) {
            try { this._currentCleanup(); } catch (e) { /* ignore */ }
            this._currentCleanup = null;
        }

        const container = document.getElementById('view-container');
        if (!container) return;

        // 更新导航高亮
        document.querySelectorAll('.app-header nav a').forEach(a => {
            a.classList.toggle('active', a.getAttribute('href') === `#${base}`);
        });

        // 分发
        const handler = this._routes[base];
        if (handler) {
            const result = handler(container, path);
            if (typeof result === 'function') {
                this._currentCleanup = result;
            }
            this._currentView = base;
        } else {
            container.innerHTML = `<div class="empty-state"><span class="empty-state-icon">🔍</span><h3>页面不存在</h3></div>`;
        }
    },
};
