/**
 * API 客户端 — 封装所有后端 API 调用。
 */
const API = {
    // ─── 配置 ────────────────────────────────────────────────

    async configStatus() {
        return this._get('/api/config/status');
    },

    async testKey(provider, key) {
        return this._post('/api/config/test-key', { provider, key });
    },

    async saveKey(provider, key) {
        return this._post('/api/config/save-key', { provider, key });
    },

    // ─── 项目 ────────────────────────────────────────────────

    async listProjects() {
        return this._get('/api/projects');
    },

    async createProject(data) {
        return this._post('/api/projects', data);
    },

    async getProject(id) {
        return this._get(`/api/projects/${id}`);
    },

    async deleteProject(id) {
        return this._del(`/api/projects/${id}`);
    },

    async uploadScript(projectId, file) {
        const fd = new FormData();
        fd.append('file', file);
        const resp = await fetch(`/api/projects/${projectId}/upload`, { method: 'POST', body: fd });
        if (!resp.ok) throw new Error((await resp.json()).detail || 'Upload failed');
        return resp.json();
    },

    // ─── 步骤 ────────────────────────────────────────────────

    // 执行步骤。付费步骤在「已过期/将覆盖」时后端返回 409 + { need_confirm, estimate }，
    // 这里不抛错而是原样返回该 body，交由调用方弹确认框；确认后带 confirm=true 重发。
    // force=true 为幂等逃生阀（忽略跳过、全部重生成）；默认 force=false 增量续跑。
    async runStep(projectId, stepName, confirm = false, force = false) {
        const params = [];
        if (confirm) params.push('confirm=true');
        if (force) params.push('force=true');
        const qs = params.length ? `?${params.join('&')}` : '';
        const resp = await fetch(`/api/projects/${projectId}/steps/${stepName}/run${qs}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const body = await resp.json().catch(() => ({}));
        if (resp.status === 409 && body && body.need_confirm) {
            return body;  // { need_confirm: true, step, reason, estimate }
        }
        if (!resp.ok) {
            throw new Error(body.detail || `HTTP ${resp.status}`);
        }
        return body;
    },

    async redoStep(projectId, stepName) {
        return this._post(`/api/projects/${projectId}/steps/${stepName}/redo`);
    },

    async getStepResult(projectId, stepName) {
        return this._get(`/api/projects/${projectId}/steps/${stepName}/result`);
    },

    async getEditable(projectId, stepName) {
        return this._get(`/api/projects/${projectId}/steps/${stepName}/editable`);
    },

    async updateField(projectId, path, value, reset = true) {
        return this._put(`/api/projects/${projectId}/state/field`, { path, value, reset });
    },

    // ─── 项目操作 ────────────────────────────────────────────

    async duplicateProject(projectId, name) {
        return this._post(`/api/projects/${projectId}/duplicate`, { name: name || '' });
    },

    // ─── 手动上传 ────────────────────────────────────────────

    async uploadAssetImage(projectId, category, index, file) {
        const fd = new FormData();
        fd.append('category', category);
        fd.append('index', String(index));
        fd.append('file', file);
        const resp = await fetch(`/api/projects/${projectId}/assets/upload-image`, { method: 'POST', body: fd });
        if (!resp.ok) throw new Error((await resp.json()).detail || 'Upload failed');
        return resp.json();
    },

    async uploadSegmentVideo(projectId, segmentId, file) {
        const fd = new FormData();
        fd.append('segment_id', segmentId);
        fd.append('file', file);
        const resp = await fetch(`/api/projects/${projectId}/videos/upload-segment`, { method: 'POST', body: fd });
        if (!resp.ok) throw new Error((await resp.json()).detail || 'Upload failed');
        return resp.json();
    },

    // ─── 成本 ────────────────────────────────────────────────

    async estimateCost(projectId) {
        return this._get(`/api/projects/${projectId}/estimate`);
    },

    // ─── 文件 ────────────────────────────────────────────────

    // 把产物路径拼成 HTTP URL。
    // 契约（见后端 src/paths.py）：后端存入 state 的路径已规范化为
    // 「相对项目根的 posix 相对路径」（如 资产/char_0.png）。此处主路径即纯拼接。
    // 下方 indexOf/replace 是对历史脏数据（旧项目未迁移）的防御性兼容 —— 双保险，
    // 即便某处遗漏规范化也不至于裂图。
    fileUrl(projectId, filePath) {
        if (!filePath) return '';
        // 统一正斜杠、去掉 ./ 前缀（对干净相对路径为幂等）
        let norm = String(filePath).replace(/\\/g, '/').replace(/^\.\//, '');
        // 兼容历史脏数据：若仍含 outputs/{projectId}/ 前缀则剥离
        const pattern = `outputs/${projectId}/`;
        const idx = norm.indexOf(pattern);
        const relative = idx >= 0 ? norm.substring(idx + pattern.length) : norm;
        // 按路径段编码，保留 '/' 分隔符（中文目录名需编码）
        const encoded = relative.split('/').map(encodeURIComponent).join('/');
        return `/api/projects/${projectId}/files/${encoded}`;
    },

    // ─── 内部方法 ────────────────────────────────────────────

    async _get(url) {
        const resp = await fetch(url);
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    async _post(url, data) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    async _del(url) {
        const resp = await fetch(url, { method: 'DELETE' });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },

    async _put(url, data) {
        const resp = await fetch(url, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            const err = await resp.json().catch(() => ({ detail: resp.statusText }));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }
        return resp.json();
    },
};
