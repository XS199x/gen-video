/**
 * PromptModal — 提示词查看 / 编辑 / 复制 弹窗。
 *
 * open(opts) 打开弹窗。
 *   opts = {
 *     path, promptText, shotName, groupName, dialogue, description,
 *     onSave: async (path, value) => {}   // 保存回调
 *   }
 * 自动管理 Esc / 点遮罩关闭，并在关闭时清理键盘监听（修复原实现的监听泄漏）。
 */
(function () {
    const E = window.Utils.escHtml;

    function open(opts) {
        const { path, promptText = '', shotName = '提示词', groupName = '', dialogue = '', description = '', onSave } = opts;

        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay wide';
        overlay.innerHTML = `
            <div class="modal">
                <div class="prompt-modal-head">
                    <div>
                        <h3 style="margin:0;">✏️ 提示词</h3>
                        <div class="prompt-meta-row">
                            <strong>${E(shotName)}</strong>
                            ${groupName ? `<span>· ${E(groupName)}</span>` : ''}
                            ${dialogue ? `<span style="color:var(--primary);">· 💬 ${E(dialogue)}</span>` : ''}
                            ${description ? `<span style="color:var(--text-muted);">· ${E(description)}</span>` : ''}
                        </div>
                    </div>
                    <button class="btn btn-outline btn-sm" data-role="close" style="font-size:18px;padding:4px 10px;">✕</button>
                </div>
                <div class="modal-body">
                    <div data-role="view-area">
                        <pre class="prompt-display" data-role="display">${E(promptText || '(无提示词)')}</pre>
                    </div>
                    <div data-role="edit-area" class="hidden">
                        <textarea class="prompt-display-edit" data-role="textarea">${E(promptText)}</textarea>
                    </div>
                </div>
                <div class="modal-actions" style="display:flex;align-items:center;gap:8px;">
                    <button class="btn-copy-lg" data-role="copy">📋 复制提示词</button>
                    <span style="flex:1;"></span>
                    <button class="btn btn-outline btn-sm" data-role="edit">✏️ 编辑</button>
                    <button class="btn btn-outline btn-sm hidden" data-role="cancel">取消编辑</button>
                    <button class="btn btn-primary btn-sm hidden" data-role="save">💾 保存</button>
                </div>
            </div>`;

        document.body.appendChild(overlay);

        const q = (r) => overlay.querySelector(`[data-role="${r}"]`);
        const viewArea = q('view-area'), editArea = q('edit-area');
        const display = q('display'), textarea = q('textarea');
        const editBtn = q('edit'), cancelBtn = q('cancel'), saveBtn = q('save'), copyBtn = q('copy');

        function close() {
            overlay.remove();
            document.removeEventListener('keydown', onEsc);
        }
        function onEsc(e) { if (e.key === 'Escape') close(); }

        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
        document.addEventListener('keydown', onEsc);
        q('close').addEventListener('click', close);

        copyBtn.addEventListener('click', () => {
            const text = editArea.classList.contains('hidden') ? display.textContent : textarea.value;
            window.Utils.copyText(text, '提示词已复制').then((ok) => {
                if (!ok) return;
                copyBtn.innerHTML = '✓ 已复制';
                copyBtn.style.background = '#065f46';
                setTimeout(() => { copyBtn.innerHTML = '📋 复制提示词'; copyBtn.style.background = ''; }, 2000);
            });
        });

        editBtn.addEventListener('click', () => {
            viewArea.classList.add('hidden'); editArea.classList.remove('hidden');
            editBtn.classList.add('hidden'); cancelBtn.classList.remove('hidden'); saveBtn.classList.remove('hidden');
            textarea.focus();
        });

        cancelBtn.addEventListener('click', () => {
            viewArea.classList.remove('hidden'); editArea.classList.add('hidden');
            editBtn.classList.remove('hidden'); cancelBtn.classList.add('hidden'); saveBtn.classList.add('hidden');
        });

        saveBtn.addEventListener('click', async () => {
            const newValue = textarea.value;
            saveBtn.disabled = true; saveBtn.textContent = '⏳ 保存中...';
            try {
                await onSave(path, newValue);
                display.textContent = newValue || '(无提示词)';
                viewArea.classList.remove('hidden'); editArea.classList.add('hidden');
                editBtn.classList.remove('hidden'); cancelBtn.classList.add('hidden'); saveBtn.classList.add('hidden');
                window.Utils.showToast('已保存');
            } catch (e) {
                window.Utils.showToast('保存失败: ' + e.message, 'error');
            } finally {
                saveBtn.disabled = false; saveBtn.textContent = '💾 保存';
            }
        });
    }

    window.Components = window.Components || {};
    window.Components.PromptModal = { open };
})();
