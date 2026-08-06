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

    async runStep(projectId, stepName) {
        return this._post(`/api/projects/${projectId}/steps/${stepName}/run`);
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

    fileUrl(projectId, filePath) {
        if (!filePath) return '';
        // 后端存的是 OS 原始路径，可能混用反斜杠 / 正斜杠、带 ./ 前缀
        // （如 './outputs\\{id}\\资产/人物/x.png'）。先统一为正斜杠再剥离前缀。
        let norm = String(filePath).replace(/\\/g, '/').replace(/^\.\//, '');
        // 剥离 outputs/{projectId}/ 前缀，得到相对项目输出目录的路径
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
