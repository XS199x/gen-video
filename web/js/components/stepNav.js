/**
 * StepNav — 左侧垂直步骤导航 rail。
 *
 * 参考编辑器式布局（Linear/Figma）：一次聚焦一个步骤，
 * 常驻显示各步状态 / 耗时 / 过期标记，可自由跳转。
 *
 * render(steps, activeKey) -> htmlString
 *   steps: [{ key, label, icon, status, started, finished, stale }]
 *
 * 点击事件由父容器委托：li[data-step]
 */
(function () {
    const E = window.Utils.escHtml;

    const STATUS_ICON = { pending: '○', running: '⏳', completed: '✓', failed: '✗' };

    function render(steps, activeKey) {
        return `
        <nav class="step-nav" aria-label="工作流步骤">
            <ol class="step-nav-list">
                ${steps.map((s, i) => {
                    const dur = window.Utils.formatDuration(s.started, s.finished);
                    return `
                    <li class="step-nav-item ${s.status} ${s.key === activeKey ? 'active' : ''}"
                        data-step="${s.key}" tabindex="0" role="button">
                        <span class="step-nav-badge">${STATUS_ICON[s.status] || '○'}</span>
                        <span class="step-nav-body">
                            <span class="step-nav-label">${s.icon} ${E(s.label)}</span>
                            <span class="step-nav-sub">
                                ${statusText(s.status)}${dur ? ` · ⏱ ${dur}` : ''}
                                ${s.stale ? '<span class="tag-edited">⚠️ 已过期，需重跑</span>' : ''}
                            </span>
                        </span>
                        ${i < steps.length - 1 ? '<span class="step-nav-line"></span>' : ''}
                    </li>`;
                }).join('')}
            </ol>
        </nav>`;
    }

    function statusText(status) {
        return ({ pending: '待执行', running: '执行中', completed: '已完成', failed: '失败' })[status] || '待执行';
    }

    window.Components = window.Components || {};
    window.Components.StepNav = { render };
})();
