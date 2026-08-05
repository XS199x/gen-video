/**
 * 应用入口 — 注册路由并启动。
 */

(function () {
    Router.on('setup', (container) => {
        setupView(container);
    });

    Router.on('projects', (container) => {
        projectsView(container);
    });

    Router.on('workflow', (container, path) => {
        if (!path) {
            Router.navigate('projects');
            return;
        }
        return workflowView(container, path);
    });

    // 默认跳转到 setup
    if (!window.location.hash) {
        // 先检查是否已配置 API Key
        API.configStatus().then(status => {
            if (status.deepseek) {
                Router.navigate('projects');
            } else {
                Router.navigate('setup');
            }
        }).catch(() => {
            Router.navigate('setup');
        });
    }

    Router.start();
})();
