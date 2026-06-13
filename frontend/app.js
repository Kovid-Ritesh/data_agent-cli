/**
 * DataAgent — Frontend Application
 *
 * Handles file uploads, chat interactions, and rendering of the
 * ReAct loop steps (thinking → code → output → answer).
 *
 * Error Handling Strategies (Frontend Layer):
 * ──────────────────────────────────────────
 * 13. NETWORK ERROR RECOVERY
 *     - Automatic retry on network failures (fetch with retry wrapper).
 *     - Timeout protection for API calls.
 *     - User-friendly error messages with suggested actions.
 *
 * 14. OPTIMISTIC UI WITH ROLLBACK
 *     - Shows loading states immediately, rolls back on failure.
 *     - Disables inputs during operations to prevent double-submission.
 *
 * 15. INPUT SANITIZATION
 *     - Escapes HTML in all user-generated content to prevent XSS.
 *     - Validates file types client-side before upload.
 */

// ── Configuration ────────────────────────────────────────────────────────────
const API_BASE = window.location.origin;
const SUPPORTED_EXTENSIONS = ['.csv', '.tsv', '.json', '.xlsx', '.xls', '.parquet', '.sqlite'];
const MAX_FILE_SIZE_MB = 50;
const API_TIMEOUT_MS = 600_000; // 10 minutes for long queries

// ── State ────────────────────────────────────────────────────────────────────
let sessionId = null;
let isQuerying = false;

// ── DOM References ───────────────────────────────────────────────────────────
const uploadPanel = document.getElementById('upload-panel');
const chatPanel = document.getElementById('chat-panel');
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('file-input');
const addFileInput = document.getElementById('add-file-input');
const uploadProgress = document.getElementById('upload-progress');
const progressFill = document.getElementById('progress-fill');
const progressText = document.getElementById('progress-text');
const fileList = document.getElementById('file-list');
const messages = document.getElementById('messages');
const queryInput = document.getElementById('query-input');
const btnSend = document.getElementById('btn-send');
const btnClearChat = document.getElementById('btn-clear-chat');
const btnNewSession = document.getElementById('btn-new-session');
const btnAddFiles = document.getElementById('btn-add-files');
const connectionStatus = document.getElementById('connection-status');
const toastContainer = document.getElementById('toast-container');

// ── Strategy 13: Fetch with retry and timeout ────────────────────────────────
async function fetchWithRetry(url, options = {}, retries = 2) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeout || API_TIMEOUT_MS);

    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            const response = await fetch(url, {
                ...options,
                signal: controller.signal,
            });

            clearTimeout(timeout);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                const errorMsg = errorData.detail || errorData.error || `HTTP ${response.status}`;

                // Don't retry on client errors (4xx)
                if (response.status >= 400 && response.status < 500) {
                    throw new Error(errorMsg);
                }

                // Retry on server errors (5xx)
                if (attempt < retries) {
                    await sleep(1000 * (attempt + 1));
                    continue;
                }
                throw new Error(errorMsg);
            }

            return response;
        } catch (err) {
            clearTimeout(timeout);

            if (err.name === 'AbortError') {
                throw new Error('Request timed out. The server may be overloaded.');
            }

            if (attempt < retries && !err.message.includes('HTTP 4')) {
                await sleep(1000 * (attempt + 1));
                continue;
            }
            throw err;
        }
    }
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

// ── Strategy 15: HTML Sanitization ───────────────────────────────────────────
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ── Toast Notifications ──────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;

    const icons = {
        success: '✓',
        error: '✗',
        info: 'ℹ',
    };

    toast.innerHTML = `<span>${icons[type] || 'ℹ'}</span><span>${escapeHtml(message)}</span>`;
    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast--out');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

// ── Status Indicator ─────────────────────────────────────────────────────────
function setStatus(state, text) {
    const dot = connectionStatus.querySelector('.status-dot');
    const label = connectionStatus.querySelector('.status-text');

    dot.className = `status-dot status-dot--${state}`;
    label.textContent = text;
}

// ── File Upload ──────────────────────────────────────────────────────────────

// Drag & drop events
dropzone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzone.classList.add('dropzone--active');
});

dropzone.addEventListener('dragleave', () => {
    dropzone.classList.remove('dropzone--active');
});

dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('dropzone--active');
    handleFiles(e.dataTransfer.files);
});

dropzone.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => handleFiles(fileInput.files));

// Add more files button
btnAddFiles.addEventListener('click', () => addFileInput.click());
addFileInput.addEventListener('change', () => handleFiles(addFileInput.files));

async function handleFiles(filesList) {
    if (!filesList || filesList.length === 0) return;

    // ── Strategy 15: Client-side validation ──────────────────────────────
    const validFiles = [];
    for (const file of filesList) {
        const ext = '.' + file.name.split('.').pop().toLowerCase();

        if (!SUPPORTED_EXTENSIONS.includes(ext)) {
            showToast(`Unsupported file type: ${file.name}`, 'error');
            continue;
        }

        if (file.size > MAX_FILE_SIZE_MB * 1024 * 1024) {
            showToast(`File too large: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)}MB)`, 'error');
            continue;
        }

        validFiles.push(file);
    }

    if (validFiles.length === 0) return;

    // ── Strategy 14: Optimistic UI ───────────────────────────────────────
    uploadProgress.hidden = false;
    progressFill.style.width = '10%';
    progressText.textContent = `Uploading ${validFiles.length} file(s)...`;
    setStatus('loading', 'Uploading...');

    const formData = new FormData();
    validFiles.forEach(f => formData.append('files', f));
    if (sessionId) {
        formData.append('session_id', sessionId);
    }

    try {
        progressFill.style.width = '40%';

        const response = await fetchWithRetry(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData,
            timeout: 60_000,
        });

        progressFill.style.width = '80%';
        const data = await response.json();

        sessionId = data.session_id;
        progressFill.style.width = '100%';
        progressText.textContent = 'Files loaded successfully!';

        // Update file list
        renderFileList(data.files);

        // Switch to chat view
        setTimeout(() => {
            uploadPanel.hidden = true;
            chatPanel.hidden = false;
            btnClearChat.disabled = false;
            setStatus('online', `${data.files.length} file(s) loaded`);
            queryInput.focus();
            showToast(`Loaded ${data.files.length} file(s) successfully`, 'success');
        }, 600);

    } catch (err) {
        // ── Strategy 14: Rollback on failure ──────────────────────────────
        progressFill.style.width = '0%';
        progressText.textContent = 'Upload failed';
        setStatus('offline', 'Upload failed');
        showToast(`Upload failed: ${err.message}`, 'error', 6000);

        setTimeout(() => {
            uploadProgress.hidden = true;
        }, 2000);
    }
}

function renderFileList(files) {
    fileList.innerHTML = '';
    files.forEach(file => {
        const li = document.createElement('li');
        li.className = 'sidebar__file';

        const ext = file.name.split('.').pop().toUpperCase();
        li.innerHTML = `
            <div class="sidebar__file-icon">${escapeHtml(ext)}</div>
            <div class="sidebar__file-info">
                <div class="sidebar__file-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
                <div class="sidebar__file-meta">${file.rows.toLocaleString()} rows · ${file.columns} cols · ${file.size_kb} KB</div>
            </div>
        `;
        fileList.appendChild(li);
    });
}

// ── Query Handling ───────────────────────────────────────────────────────────

queryInput.addEventListener('input', () => {
    // Auto-resize textarea
    queryInput.style.height = 'auto';
    queryInput.style.height = Math.min(queryInput.scrollHeight, 150) + 'px';

    // Enable/disable send button
    btnSend.disabled = !queryInput.value.trim() || isQuerying;
});

queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (!isQuerying && queryInput.value.trim()) {
            sendQuery();
        }
    }
});

btnSend.addEventListener('click', sendQuery);

// Suggestion chips
document.addEventListener('click', (e) => {
    if (e.target.classList.contains('suggestion-chip')) {
        const query = e.target.getAttribute('data-query');
        queryInput.value = query;
        queryInput.dispatchEvent(new Event('input'));
        sendQuery();
    }
});

async function sendQuery() {
    const query = queryInput.value.trim();
    if (!query || isQuerying || !sessionId) return;

    // ── Strategy 14: Optimistic UI ───────────────────────────────────────
    isQuerying = true;
    queryInput.value = '';
    queryInput.style.height = 'auto';
    btnSend.disabled = true;
    queryInput.disabled = true;

    // Add user message
    addUserMessage(query);

    // Add loading indicator
    const loadingEl = addLoadingIndicator();

    setStatus('loading', 'Analyzing...');

    try {
        const response = await fetchWithRetry(`${API_BASE}/api/query`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, query }),
        });

        const data = await response.json();

        // Remove loading indicator
        loadingEl.remove();

        // Render all steps
        renderSteps(data.steps);

        if (!data.success && data.error) {
            showToast(`Query issue: ${data.error}`, 'error', 6000);
        }

        setStatus('online', 'Ready');

    } catch (err) {
        loadingEl.remove();
        addErrorStep(`Failed to complete query: ${err.message}`);
        setStatus('online', 'Ready');
        showToast(`Query failed: ${err.message}`, 'error', 6000);
    } finally {
        isQuerying = false;
        queryInput.disabled = false;
        queryInput.focus();
        btnSend.disabled = true;
    }
}

// ── Message Rendering ────────────────────────────────────────────────────────

function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'message message--user';
    div.innerHTML = `
        <div class="message__icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
            </svg>
        </div>
        <div class="message__body">
            <div class="message__text">${escapeHtml(text)}</div>
        </div>
    `;
    messages.appendChild(div);
    scrollToBottom();
}

function addLoadingIndicator() {
    const div = document.createElement('div');
    div.className = 'message message--system';
    div.innerHTML = `
        <div class="message__icon">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
            </svg>
        </div>
        <div class="message__body">
            <div class="loading-indicator">
                <div class="loading-dots"><span></span><span></span><span></span></div>
                <span class="loading-text">Thinking and analyzing your data...</span>
            </div>
        </div>
    `;
    messages.appendChild(div);
    scrollToBottom();
    return div;
}

function renderSteps(steps) {
    steps.forEach(step => {
        const div = document.createElement('div');
        div.className = 'message message--system';

        let panelClass, headerIcon, headerText, bodyContent;

        switch (step.type) {
            case 'thinking':
                panelClass = 'thinking';
                headerIcon = '💭';
                headerText = 'Reasoning';
                bodyContent = escapeHtml(step.content);
                break;

            case 'code':
                panelClass = 'code';
                headerIcon = '⚡';
                headerText = 'Executing Code';
                bodyContent = `<pre><code>${escapeHtml(step.content)}</code></pre>`;
                break;

            case 'output':
                panelClass = 'output';
                headerIcon = '📋';
                headerText = 'Output';
                bodyContent = escapeHtml(step.content);
                break;

            case 'error':
                panelClass = 'error';
                headerIcon = '⚠️';
                headerText = 'Error';
                bodyContent = escapeHtml(step.content);
                break;

            case 'answer':
                panelClass = 'answer';
                headerIcon = '✅';
                headerText = 'Answer';
                bodyContent = formatAnswer(step.content);
                break;

            default:
                panelClass = 'output';
                headerIcon = '📝';
                headerText = step.type;
                bodyContent = escapeHtml(step.content);
        }

        div.innerHTML = `
            <div class="message__icon">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/>
                </svg>
            </div>
            <div class="message__body">
                <div class="step-panel step-panel--${panelClass}">
                    <div class="step-panel__header">
                        <span>${headerIcon}</span>
                        <span>${headerText}</span>
                    </div>
                    <div class="step-panel__body">${bodyContent}</div>
                </div>
            </div>
        `;

        messages.appendChild(div);
        scrollToBottom();
    });
}

function addErrorStep(message) {
    renderSteps([{ type: 'error', content: message }]);
}

function formatAnswer(text) {
    // Basic markdown-like formatting for answers
    let html = escapeHtml(text);

    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

    // Inline code `code`
    html = html.replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;font-family:var(--font-mono);font-size:0.85em;">$1</code>');

    // Line breaks
    html = html.replace(/\n/g, '<br>');

    // Bullet points
    html = html.replace(/^- (.*)/gm, '• $1');

    return html;
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        messages.scrollTop = messages.scrollHeight;
    });
}

// ── Session Management ───────────────────────────────────────────────────────

btnClearChat.addEventListener('click', async () => {
    if (!sessionId) return;

    try {
        await fetchWithRetry(`${API_BASE}/api/clear/${sessionId}`, {
            method: 'POST',
            timeout: 10_000,
        });

        // Keep only the system welcome message
        const firstMsg = messages.querySelector('.message--system');
        messages.innerHTML = '';
        if (firstMsg) messages.appendChild(firstMsg);

        showToast('Conversation history cleared', 'success');
    } catch (err) {
        showToast(`Failed to clear history: ${err.message}`, 'error');
    }
});

btnNewSession.addEventListener('click', () => {
    if (sessionId) {
        // Fire and forget cleanup
        fetchWithRetry(`${API_BASE}/api/session/${sessionId}`, {
            method: 'DELETE',
            timeout: 5_000,
        }).catch(() => {});
    }

    sessionId = null;
    isQuerying = false;

    uploadPanel.hidden = false;
    chatPanel.hidden = true;
    btnClearChat.disabled = true;
    uploadProgress.hidden = true;
    fileList.innerHTML = '';
    messages.innerHTML = '';

    setStatus('offline', 'No files loaded');
    showToast('Session reset. Upload new files to begin.', 'info');
});

// ── Initialize ───────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    queryInput.focus();
});
