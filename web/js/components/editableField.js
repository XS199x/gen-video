/**
 * EditableField — 统一的内联编辑字段组件。
 *
 * 交互统一为：查看态 → 点铅笔进入编辑 → 显式「保存 / 取消(Esc)」。
 * 不再使用易误触的自动保存。
 *
 * render(opts) -> htmlString
 *   opts = {
 *     path:  数据路径（保存时回传），
 *     value: 当前值,
 *     type:  'input' | 'textarea'（默认 textarea）,
 *     label: 可选，查看态前缀（如角色名）,
 *     placeholder,
 *     lines: line-clamp 行数（视觉截断，默认 3，0 表示不截断）,
 *     minHeight: 编辑框最小高度 px（textarea）,
 *   }
 *
 * 事件由容器统一委托，见 bindContainer()。
 */
(function () {
    const E = window.Utils.escHtml;
    const A = window.Utils.escAttr;

    function render(opts) {
        const {
            path, value = '', type = 'textarea', label = '',
            placeholder = '', lines = 3, minHeight = 60,
        } = opts;
        const clampStyle = lines > 0
            ? `display:-webkit-box;-webkit-line-clamp:${lines};-webkit-box-orient:vertical;overflow:hidden;`
            : '';
        const editor = type === 'input'
            ? `<input class="editable-input" data-editor value="${A(value)}" placeholder="${A(placeholder)}">`
            : `<textarea class="editable-textarea" data-editor style="min-height:${minHeight}px;" placeholder="${A(placeholder)}">${E(value)}</textarea>`;

        return `
        <div class="editable-field" data-path="${A(path)}">
            <div class="view-mode" data-role="view">
                <div class="ef-value" style="${clampStyle}">${label ? `<strong>${E(label)}</strong> ` : ''}${E(value) || '<span class="text-muted">（空，点击编辑）</span>'}</div>
                <button class="ef-edit-btn" data-role="edit" title="编辑">✏️</button>
            </div>
            <div class="edit-mode" data-role="editor-box">
                ${editor}
                <div class="editable-actions">
                    <button class="btn btn-sm btn-outline" data-role="cancel">取消</button>
                    <button class="btn btn-sm btn-primary" data-role="save">保存</button>
                </div>
            </div>
        </div>`;
    }

    /**
     * 在容器上做一次事件委托，处理容器内所有 EditableField。
     * @param {HTMLElement} root
     * @param {(path:string, value:string)=>Promise} onSave  保存回调
     * @returns {Function} cleanup
     */
    function bindContainer(root, onSave) {
        function fieldOf(el) { return el.closest('.editable-field'); }

        async function doSave(field) {
            const editor = field.querySelector('[data-editor]');
            if (!editor) return;
            const path = field.dataset.path;
            const value = editor.value;
            const saveBtn = field.querySelector('[data-role="save"]');
            if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '保存中...'; }
            try {
                await onSave(path, value);
                field.classList.remove('editing');
                // 更新查看态显示
                const valEl = field.querySelector('.ef-value');
                if (valEl) {
                    valEl.innerHTML = value
                        ? window.Utils.escHtml(value)
                        : '<span class="text-muted">（空，点击编辑）</span>';
                }
            } catch (e) {
                window.Utils.showToast('保存失败: ' + e.message, 'error');
            } finally {
                if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '保存'; }
            }
        }

        function onClick(e) {
            const role = e.target.closest('[data-role]')?.dataset.role;
            const field = fieldOf(e.target);
            if (!field) return;

            if (role === 'edit' || (role === 'view' && !e.target.closest('button'))) {
                field.classList.add('editing');
                const ed = field.querySelector('[data-editor]');
                if (ed) ed.focus();
            } else if (role === 'save') {
                doSave(field);
            } else if (role === 'cancel') {
                field.classList.remove('editing');
            }
        }

        function onKeydown(e) {
            const field = fieldOf(e.target);
            if (!field || !field.classList.contains('editing')) return;
            if (e.key === 'Escape') {
                field.classList.remove('editing');
            } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                doSave(field);
            }
        }

        root.addEventListener('click', onClick);
        root.addEventListener('keydown', onKeydown);
        return () => {
            root.removeEventListener('click', onClick);
            root.removeEventListener('keydown', onKeydown);
        };
    }

    window.Components = window.Components || {};
    window.Components.EditableField = { render, bindContainer };
})();
