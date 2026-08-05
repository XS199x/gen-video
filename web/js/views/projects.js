/**
 * 项目列表页。
 */
function projectsView(container) {
    let projects = [];

    async function render() {
        container.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
                <div>
                    <h2 style="margin-bottom:4px;">📂 我的项目</h2>
                    <p class="text-muted">管理你的短剧生成项目</p>
                </div>
                <button class="btn btn-primary" id="btnNewProject">＋ 新建项目</button>
            </div>
            <div id="projectList"></div>
            <div id="newProjectForm" class="card hidden" style="max-width:480px;margin:0 auto;">
                <h3 class="card-title mb-4">新建项目</h3>
                <div class="form-group">
                    <label class="form-label">项目名称</label>
                    <input class="form-input" id="inputProjectName" placeholder="例如：都市传说 第01集">
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label class="form-label">剧集编号</label>
                        <input class="form-input" id="inputEpisodeId" value="01" placeholder="01">
                    </div>
                    <div class="form-group">
                        <label class="form-label">剧集标题</label>
                        <input class="form-input" id="inputEpisodeTitle" value="第01集" placeholder="第01集">
                    </div>
                </div>
                <div style="display:flex;gap:8px;justify-content:flex-end;">
                    <button class="btn btn-outline" id="btnCancelNew">取消</button>
                    <button class="btn btn-primary" id="btnCreate">创建</button>
                </div>
            </div>
        `;

        await loadProjects();
        bindEvents();
    }

    async function loadProjects() {
        try {
            projects = await API.listProjects();
        } catch (e) {
            projects = [];
        }
        renderList();
    }

    function renderList() {
        const list = document.getElementById('projectList');
        if (!list) return;

        if (projects.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <span class="empty-state-icon">🎬</span>
                    <h3>还没有项目</h3>
                    <p>点击「新建项目」开始你的第一个短剧生成</p>
                </div>
            `;
            return;
        }

        list.innerHTML = `<div class="project-grid">${projects.map(p => {
            const completedSteps = (p.steps || []).filter(s => s.status === 'completed').length;
            const total = (p.steps || []).length || 7;
            const pct = total > 0 ? Math.round(completedSteps / total * 100) : 0;
            return `
                <div class="project-card" data-id="${p.id}">
                    <h3>${escHtml(p.name || p.episode_title || '未命名项目')}</h3>
                    <div class="meta">
                        <div>剧集: ${escHtml(p.episode_id)} - ${escHtml(p.episode_title)}</div>
                        <div>创建: ${formatDate(p.created_at)}</div>
                        <div>状态: ${statusLabel(p.status)}</div>
                    </div>
                    <div class="progress">
                        <div style="display:flex;justify-content:space-between;font-size:12px;color:var(--text-secondary);margin-bottom:4px;">
                            <span>进度</span><span>${completedSteps}/${total} 步</span>
                        </div>
                        <div class="progress-bar"><div class="progress-fill" style="width:${pct}%"></div></div>
                    </div>
                </div>
            `;
        }).join('')}</div>`;
    }

    function bindEvents() {
        const btnNew = document.getElementById('btnNewProject');
        const btnCancel = document.getElementById('btnCancelNew');
        const btnCreate = document.getElementById('btnCreate');
        const form = document.getElementById('newProjectForm');
        const list = document.getElementById('projectList');

        if (btnNew) {
            btnNew.addEventListener('click', () => {
                form.classList.toggle('hidden');
                btnNew.style.display = form.classList.contains('hidden') ? '' : 'none';
            });
        }

        if (btnCancel) {
            btnCancel.addEventListener('click', () => {
                form.classList.add('hidden');
                if (btnNew) btnNew.style.display = '';
            });
        }

        if (btnCreate) {
            btnCreate.addEventListener('click', async () => {
                const name = document.getElementById('inputProjectName').value.trim();
                const episodeId = document.getElementById('inputEpisodeId').value.trim() || '01';
                const episodeTitle = document.getElementById('inputEpisodeTitle').value.trim() || '';

                if (!name && !episodeTitle) {
                    alert('请填写项目名称或剧集标题');
                    return;
                }

                btnCreate.disabled = true;
                btnCreate.textContent = '创建中...';
                try {
                    const p = await API.createProject({
                        name, episode_id: episodeId, episode_title: episodeTitle,
                    });
                    form.classList.add('hidden');
                    if (btnNew) btnNew.style.display = '';
                    Router.navigate(`workflow/${p.id}`);
                } catch (e) {
                    alert('创建失败: ' + e.message);
                }
                btnCreate.disabled = false;
                btnCreate.textContent = '创建';
            });
        }

        if (list) {
            list.addEventListener('click', (e) => {
                const card = e.target.closest('.project-card');
                if (card) {
                    const id = card.dataset.id;
                    if (id) Router.navigate(`workflow/${id}`);
                }
            });
        }
    }

    function statusLabel(s) {
        const map = { created: '🆕 新建', editing: '✏️ 编辑中', generating: '🎥 生成中', completed: '✅ 完成' };
        return map[s] || s;
    }

    function formatDate(iso) {
        if (!iso) return '-';
        const d = new Date(iso);
        return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }

    function pad(n) { return String(n).padStart(2, '0'); }
    function escHtml(s) {
        const el = document.createElement('span');
        el.textContent = s;
        return el.innerHTML;
    }

    render();
}
