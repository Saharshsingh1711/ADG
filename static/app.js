/**
 * ADG — Autonomous Database Guardian | Clean Client JS
 * WebSocket communication, schema table inspector, and Human-in-the-Loop review.
 */

class DatabaseGuardian {
    constructor() {
        this.ws = null;
        this.reconnectTimer = null;
        this.activeApprovalPending = false;
        this.history = [];

        this.initDOMElements();
        this.bindEvents();
        this.initWebSocket();
        this.fetchDatabaseStats();
        this.fetchAuditCount();

        setInterval(() => this.fetchDatabaseStats(), 15000);
    }

    initDOMElements() {
        this.sidebar = document.getElementById('sidebar');
        this.sidebarToggle = document.getElementById('sidebarToggle');
        this.sidebarBackdrop = document.getElementById('sidebarBackdrop');

        this.hudDbName = document.getElementById('hudDbName');
        this.hudRecordsCount = document.getElementById('hudRecordsCount');
        this.hudModelName = document.getElementById('hudModelName');
        this.auditBadgeCount = document.getElementById('auditBadgeCount');

        this.tabBtns = document.querySelectorAll('[data-sidebar-tab]');
        this.tabPanelTables = document.getElementById('tabPanelTables');
        this.tabPanelHistory = document.getElementById('tabPanelHistory');
        this.tabPanelAudit = document.getElementById('tabPanelAudit');
        this.tablesTreeContainer = document.getElementById('tablesTreeContainer');
        this.historyListContainer = document.getElementById('historyListContainer');
        this.miniAuditContainer = document.getElementById('miniAuditContainer');
        this.btnRefreshStats = document.getElementById('btnRefreshStats');

        this.metricSafeQueries = document.getElementById('metricSafeQueries');
        this.metricBlockedMutations = document.getElementById('metricBlockedMutations');
        this.connStatusText = document.getElementById('connStatusText');
        this.connDot = document.getElementById('connDot');
        this.sessionBadge = document.getElementById('sessionBadge');

        this.messagesContainer = document.getElementById('messagesContainer');
        this.heroWelcome = document.getElementById('heroWelcome');
        this.chatStream = document.getElementById('chatStream');
        this.queryForm = document.getElementById('queryForm');
        this.queryInput = document.getElementById('queryInput');
        this.btnSend = document.getElementById('btnSend');
        this.btnClearChat = document.getElementById('btnClearChat');

        this.btnExploreSchema = document.getElementById('btnExploreSchema');
        this.btnViewAudit = document.getElementById('btnViewAudit');
        this.schemaModalBackdrop = document.getElementById('schemaModalBackdrop');
        this.auditModalBackdrop = document.getElementById('auditModalBackdrop');
        this.btnCloseSchemaModal = document.getElementById('btnCloseSchemaModal');
        this.btnCloseAuditModal = document.getElementById('btnCloseAuditModal');
        this.schemaCodeContainer = document.getElementById('schemaCodeContainer');
        this.auditTableContainer = document.getElementById('auditTableContainer');
        this.btnCopySchema = document.getElementById('btnCopySchema');
        this.btnRefreshAuditModal = document.getElementById('btnRefreshAuditModal');
        this.toastContainer = document.getElementById('toastContainer');
    }

    bindEvents() {
        // Sidebar Toggle
        this.sidebarToggle.addEventListener('click', () => {
            this.sidebar.classList.toggle('closed');
        });

        // Tabs
        this.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => {
                const target = btn.getAttribute('data-sidebar-tab');
                this.tabBtns.forEach(b => b.classList.toggle('active', b === btn));
                this.tabPanelTables.classList.toggle('active', target === 'tables');
                this.tabPanelHistory.classList.toggle('active', target === 'history');
                this.tabPanelAudit.classList.toggle('active', target === 'audit');
            });
        });

        // Refresh Stats
        this.btnRefreshStats.addEventListener('click', () => {
            this.fetchDatabaseStats();
            this.showToast('Stats updated');
        });

        // Submit Form
        this.queryForm.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleQuerySubmit();
        });

        // Textarea Keydown
        this.queryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleQuerySubmit();
            }
        });

        this.queryInput.addEventListener('input', () => {
            this.queryInput.style.height = 'auto';
            this.queryInput.style.height = Math.min(this.queryInput.scrollHeight, 120) + 'px';
        });

        // Clear Chat
        this.btnClearChat.addEventListener('click', () => {
            this.chatStream.innerHTML = '';
            if (this.heroWelcome) this.heroWelcome.style.display = 'flex';
            this.showToast('Conversation cleared');
        });

        // Suggestion Pill Clicks
        document.querySelectorAll('.suggestion-pill').forEach(pill => {
            pill.addEventListener('click', () => {
                const prompt = pill.getAttribute('data-prompt');
                if (prompt) {
                    this.queryInput.value = prompt;
                    this.handleQuerySubmit();
                }
            });
        });

        // Modals
        this.btnExploreSchema.addEventListener('click', () => this.openSchemaModal());
        this.btnCloseSchemaModal.addEventListener('click', () => this.closeSchemaModal());
        this.schemaModalBackdrop.addEventListener('click', (e) => {
            if (e.target === this.schemaModalBackdrop) this.closeSchemaModal();
        });
        this.btnCopySchema.addEventListener('click', () => {
            navigator.clipboard.writeText(this.schemaCodeContainer.textContent).then(() => {
                this.showToast('Schema copied to clipboard');
            });
        });

        this.btnViewAudit.addEventListener('click', () => this.openAuditModal());
        this.btnCloseAuditModal.addEventListener('click', () => this.closeAuditModal());
        this.auditModalBackdrop.addEventListener('click', (e) => {
            if (e.target === this.auditModalBackdrop) this.closeAuditModal();
        });
        this.btnRefreshAuditModal.addEventListener('click', () => {
            this.loadFullAuditTrail();
            this.showToast('Audit log updated');
        });

        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeSchemaModal();
                this.closeAuditModal();
            }
            if (this.activeApprovalPending) {
                if (e.key.toLowerCase() === 'y' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
                    this.sendApprovalDecision('approved');
                } else if (e.key.toLowerCase() === 'n' && !['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) {
                    this.sendApprovalDecision('denied');
                }
            }
        });
    }

    // ── WebSocket ────────────────────────────────────────────────────────────

    initWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        this.connStatusText.textContent = 'Connecting...';
        this.connDot.style.backgroundColor = 'var(--warning)';

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.connStatusText.textContent = 'Connected';
            this.connDot.style.backgroundColor = 'var(--success)';
            if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleIncomingMessage(data);
            } catch (err) {
                console.error('WS Parse Error:', err);
            }
        };

        this.ws.onclose = () => {
            this.connStatusText.textContent = 'Reconnecting...';
            this.connDot.style.backgroundColor = 'var(--danger)';
            this.reconnectTimer = setTimeout(() => this.initWebSocket(), 3000);
        };

        this.ws.onerror = () => {
            this.connStatusText.textContent = 'Error';
            this.connDot.style.backgroundColor = 'var(--danger)';
        };
    }

    handleIncomingMessage(msg) {
        switch (msg.type) {
            case 'connected':
                this.sessionBadge.textContent = `SESSION: ${msg.session_id}`;
                this.hudModelName.textContent = msg.model || 'Groq / gpt-oss-120b';
                break;

            case 'thinking':
                this.showThinkingIndicator();
                break;

            case 'approval_required':
                this.removeThinkingIndicator();
                this.renderApprovalPrompt(msg.sql, msg.risk);
                break;

            case 'result':
                this.removeThinkingIndicator();
                this.renderGuardianResult(msg.answer, msg.sql, msg.risk, msg.execution_time);
                this.recordHistory(msg.sql || 'Direct Query', msg.risk || 'READ_ONLY');
                this.fetchDatabaseStats();
                this.fetchAuditCount();
                break;

            case 'error':
                this.removeThinkingIndicator();
                this.renderGuardianError(msg.message);
                break;
        }
    }

    handleQuerySubmit() {
        const text = this.queryInput.value.trim();
        if (!text || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        if (this.heroWelcome) {
            this.heroWelcome.style.display = 'none';
        }

        this.renderUserMessage(text);
        this.ws.send(JSON.stringify({ type: 'query', text }));

        this.queryInput.value = '';
        this.queryInput.style.height = 'auto';
    }

    sendApprovalDecision(decision) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        this.activeApprovalPending = false;

        const card = document.querySelector('.approval-card.active');
        if (card) {
            card.classList.remove('active');
            const actions = card.querySelector('.approval-actions');
            if (actions) {
                actions.innerHTML = `<span style="font-size: 11px; font-weight: 600; color: ${decision === 'approved' ? 'var(--success)' : 'var(--danger)'}">
                    ${decision === 'approved' ? '✓ Approved by operator' : '✕ Denied by operator'}
                </span>`;
            }
        }

        this.ws.send(JSON.stringify({ type: 'approve', decision }));
        this.showToast(decision === 'approved' ? 'Query authorized' : 'Query rejected');
    }

    // ── Message Renderers ────────────────────────────────────────────────────

    renderUserMessage(text) {
        const row = document.createElement('div');
        row.className = 'message-row message-user';
        row.innerHTML = `
            <div class="user-text-bubble">${this.escapeHtml(text)}</div>
        `;
        this.chatStream.appendChild(row);
        this.scrollToBottom();
    }

    renderGuardianResult(answerMarkdown, sql, risk, execTime) {
        const row = document.createElement('div');
        row.className = 'message-row message-guardian';

        let sqlHtml = '';
        if (sql) {
            sqlHtml = `
                <div class="query-box">
                    <div class="query-box-header">
                        <span class="query-box-title">SQL Query (${risk || 'READ_ONLY'})</span>
                        <button class="btn-copy" onclick="navigator.clipboard.writeText(\`${this.escapeForTemplate(sql)}\`); window.__guardian.showToast('Copied SQL');">Copy</button>
                    </div>
                    <div class="query-code">
                        <pre><code class="language-sql">${this.escapeHtml(sql)}</code></pre>
                    </div>
                </div>
            `;
        }

        const parsedMarkdown = marked.parse(answerMarkdown || '');

        row.innerHTML = `
            <div class="response-card">
                <div class="response-header">
                    <div class="response-title">
                        <span>🛡️</span>
                        <span>Guardian</span>
                    </div>
                    <span class="response-time">${execTime ? `${execTime}s` : ''}</span>
                </div>
                ${sqlHtml}
                <div class="response-body">
                    ${parsedMarkdown}
                </div>
            </div>
        `;

        this.chatStream.appendChild(row);

        row.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
        });

        this.scrollToBottom();
    }

    renderApprovalPrompt(sql, risk) {
        this.activeApprovalPending = true;
        const row = document.createElement('div');
        row.className = 'message-row message-guardian';

        row.innerHTML = `
            <div class="response-card" style="border-color: var(--danger-border)">
                <div class="response-header">
                    <div class="response-title" style="color: var(--danger)">
                        <span>⚠️</span>
                        <span>Approval Required</span>
                    </div>
                    <span class="pill-tag write">DESTRUCTIVE</span>
                </div>
                <div class="approval-card active">
                    <div class="approval-header">
                        <div>
                            <div class="approval-title">This query will modify the database</div>
                            <div class="approval-desc">Review the planned SQL statement below and authorize execution.</div>
                        </div>
                    </div>
                    <div class="approval-sql">
                        <code>${this.escapeHtml(sql)}</code>
                    </div>
                    <div class="approval-actions">
                        <button class="btn-deny" onclick="window.__guardian.sendApprovalDecision('denied')">Deny (N)</button>
                        <button class="btn-approve" onclick="window.__guardian.sendApprovalDecision('approved')">Approve (Y)</button>
                    </div>
                </div>
            </div>
        `;

        this.chatStream.appendChild(row);
        this.scrollToBottom();
    }

    renderGuardianError(errorMsg) {
        const row = document.createElement('div');
        row.className = 'message-row message-guardian';
        row.innerHTML = `
            <div class="response-card" style="border-color: var(--danger-border)">
                <div class="response-header">
                    <div class="response-title" style="color: var(--danger)">
                        <span>❌</span>
                        <span>Error</span>
                    </div>
                </div>
                <div class="response-body" style="color: var(--danger)">
                    <p>${this.escapeHtml(errorMsg)}</p>
                </div>
            </div>
        `;
        this.chatStream.appendChild(row);
        this.scrollToBottom();
    }

    showThinkingIndicator() {
        this.removeThinkingIndicator();
        const row = document.createElement('div');
        row.className = 'message-row message-guardian';
        row.id = 'thinkingWrapper';
        row.innerHTML = `
            <div class="thinking-box">
                <div class="spinner"></div>
                <span class="thinking-label">Planning SQL & analyzing schema...</span>
            </div>
        `;
        this.chatStream.appendChild(row);
        this.scrollToBottom();
    }

    removeThinkingIndicator() {
        const el = document.getElementById('thinkingWrapper');
        if (el) el.remove();
    }

    scrollToBottom() {
        setTimeout(() => {
            this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
        }, 50);
    }

    // ── Stats & Tables ───────────────────────────────────────────────────────

    async fetchDatabaseStats() {
        try {
            const res = await fetch('/api/stats');
            const data = await res.json();
            if (data.tables) {
                this.renderTables(data.tables);
                this.hudRecordsCount.textContent = data.total_records || '0';
                this.hudDbName.textContent = data.db_path || 'analytics.db';
                if (data.model) this.hudModelName.textContent = data.model;

                if (data.audit_stats) {
                    this.metricSafeQueries.textContent = (data.audit_stats.total - data.audit_stats.destructive) || '0';
                    this.metricBlockedMutations.textContent = data.audit_stats.destructive || '0';
                }
            }
        } catch (err) {
            console.error('Failed to fetch stats:', err);
        }
    }

    renderTables(tables) {
        this.tablesTreeContainer.innerHTML = '';
        tables.forEach(t => {
            const item = document.createElement('div');
            item.className = 'table-item';

            const colsHtml = t.columns.map(c => `
                <div class="column-row">
                    <span class="column-name ${c.pk ? 'pk' : ''}">${c.pk ? '🔑 ' : ''}${c.name}</span>
                    <span class="column-type">${c.type}</span>
                </div>
            `).join('');

            item.innerHTML = `
                <div class="table-item-header">
                    <div class="table-title-group">
                        <span class="table-name">${t.name}</span>
                    </div>
                    <span class="table-badge">${t.row_count} rows</span>
                </div>
                <div class="table-columns-body">
                    ${colsHtml}
                    <button class="table-peek-btn" onclick="window.__guardian.prefillPrompt('SELECT * FROM ${t.name} LIMIT 10;')">
                        View Sample
                    </button>
                </div>
            `;

            item.querySelector('.table-item-header').addEventListener('click', () => {
                item.classList.toggle('open');
            });

            this.tablesTreeContainer.appendChild(item);
        });
    }

    prefillPrompt(text) {
        this.queryInput.value = text;
        this.queryInput.focus();
    }

    recordHistory(sql, risk) {
        this.history.unshift({ sql, risk, date: new Date().toLocaleTimeString() });
        document.getElementById('historyCount').textContent = this.history.length;

        const empty = this.historyListContainer.querySelector('.empty-state');
        if (empty) empty.remove();

        const card = document.createElement('div');
        card.className = 'history-item';
        card.innerHTML = `
            <div class="history-query-text">${this.escapeHtml(sql)}</div>
            <div class="history-meta-text">
                <span>${risk}</span>
                <span>${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
        `;

        card.addEventListener('click', () => {
            this.prefillPrompt(sql);
        });

        this.historyListContainer.prepend(card);
    }

    async fetchAuditCount() {
        try {
            const res = await fetch('/api/audit');
            const data = await res.json();
            if (data.entries) {
                this.auditBadgeCount.textContent = data.entries.length;
                this.renderMiniAudit(data.entries.slice(0, 5));
            }
        } catch (err) {
            console.error('Failed to fetch audit count:', err);
        }
    }

    renderMiniAudit(entries) {
        this.miniAuditContainer.innerHTML = '';
        if (entries.length === 0) {
            this.miniAuditContainer.innerHTML = `<div class="empty-state"><p class="empty-text">No security events logged.</p></div>`;
            return;
        }

        entries.forEach(e => {
            const item = document.createElement('div');
            item.className = 'history-item';
            item.innerHTML = `
                <div class="history-query-text" style="color: ${e.approved ? 'var(--text-main)' : 'var(--danger)'}">
                    ${e.approved ? '✓' : '✕'} ${this.escapeHtml(e.query_text)}
                </div>
                <div class="history-meta-text">
                    <span>${e.risk_level}</span>
                    <span>${e.executed_at.split(' ')[1] || ''}</span>
                </div>
            `;
            this.miniAuditContainer.appendChild(item);
        });
    }

    // ── Modals ───────────────────────────────────────────────────────────────

    async openSchemaModal() {
        this.schemaModalBackdrop.classList.add('open');
        this.schemaCodeContainer.textContent = '-- Loading schema...';

        try {
            const res = await fetch('/api/schema');
            const data = await res.json();
            this.schemaCodeContainer.textContent = data.ddl || '-- No schema available.';
            hljs.highlightElement(this.schemaCodeContainer);
        } catch (err) {
            this.schemaCodeContainer.textContent = `-- Error: ${err.message}`;
        }
    }

    closeSchemaModal() {
        this.schemaModalBackdrop.classList.remove('open');
    }

    async openAuditModal() {
        this.auditModalBackdrop.classList.add('open');
        await this.loadFullAuditTrail();
    }

    closeAuditModal() {
        this.auditModalBackdrop.classList.remove('open');
    }

    async loadFullAuditTrail() {
        this.auditTableContainer.innerHTML = '<div class="loading-shimmer"></div>';

        try {
            const res = await fetch('/api/audit');
            const data = await res.json();

            if (!data.entries || data.entries.length === 0) {
                this.auditTableContainer.innerHTML = `<div class="empty-state"><p class="empty-text">Audit trail is empty.</p></div>`;
                return;
            }

            const rowsHtml = data.entries.map(e => `
                <tr>
                    <td>#${e.id}</td>
                    <td>
                        <span class="tag-badge ${e.approved ? 'approved' : 'blocked'}">
                            ${e.approved ? 'Approved' : 'Blocked'}
                        </span>
                    </td>
                    <td>${e.risk_level}</td>
                    <td style="max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        <code>${this.escapeHtml(e.query_text)}</code>
                    </td>
                    <td>${e.rows_affected !== null ? e.rows_affected : '0'}</td>
                    <td style="color: var(--text-dim)">${e.executed_at}</td>
                </tr>
            `).join('');

            this.auditTableContainer.innerHTML = `
                <table class="audit-table">
                    <thead>
                        <tr>
                            <th>ID</th>
                            <th>Status</th>
                            <th>Risk</th>
                            <th>SQL Query</th>
                            <th>Rows</th>
                            <th>Timestamp</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rowsHtml}
                    </tbody>
                </table>
            `;
        } catch (err) {
            this.auditTableContainer.innerHTML = `<p style="color: var(--danger)">Error: ${err.message}</p>`;
        }
    }

    showToast(message) {
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = message;
        this.toastContainer.appendChild(toast);

        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(10px)';
            toast.style.transition = 'all 0.2s ease';
            setTimeout(() => toast.remove(), 200);
        }, 2500);
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    escapeForTemplate(str) {
        if (!str) return '';
        return str.replace(/`/g, '\\`').replace(/\$/g, '\\$');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.__guardian = new DatabaseGuardian();
});
