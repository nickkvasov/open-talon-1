/* ───────────────────────────────────────────────────────────────── *
 *  Open Talon Gateway — Web UI JavaScript
 *  - WebSocket streaming for real-time responses
 *  - Session persistence via localStorage
 *  - Auth mode switching (none / api_key / openbao)
 * ───────────────────────────────────────────────────────────────── */
'use strict';

const API_BASE  = `${location.origin}`;
const WS_BASE   = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
const LS_KEY    = 'open_talon_session_id';

// ── State ────────────────────────────────────────────────────────
let sessionId   = null;   // UUID string
let ws          = null;   // WebSocket instance
let isStreaming = false;
let msgCount    = 0;

// ── DOM refs ─────────────────────────────────────────────────────
const $messages      = document.getElementById('messages');
const $input         = document.getElementById('message-input');
const $btnSend       = document.getElementById('btn-send');
const $btnNew        = document.getElementById('btn-new-session');
const $btnClear      = document.getElementById('btn-clear-history');
const $sessionIdDisp = document.getElementById('session-id-display');
const $msgCount      = document.getElementById('session-msg-count');
const $statusDot     = document.getElementById('status-dot');
const $statusLabel   = document.getElementById('status-label');
const $hint          = document.getElementById('composer-hint');
const $authMode      = document.getElementById('auth-mode-select');
const $authToken     = document.getElementById('auth-token-input');
const $sidebar       = document.getElementById('sidebar');
const $sidebarOpen   = document.getElementById('sidebar-open');
const $sidebarClose  = document.getElementById('sidebar-close');

// ── Init ──────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', async () => {
  sessionId = localStorage.getItem(LS_KEY);
  if (!sessionId) {
    sessionId = crypto.randomUUID();
    localStorage.setItem(LS_KEY, sessionId);
  }
  updateSessionDisplay();
  await loadHistory();
  connectWs();
  bindEvents();
});

// ── Session display ───────────────────────────────────────────────
function updateSessionDisplay() {
  const short = sessionId ? sessionId.slice(0, 8) + '…' : '—';
  $sessionIdDisp.textContent = short;
  $sessionIdDisp.title = sessionId ?? '';
  $msgCount.textContent = msgCount;
}

// ── History ───────────────────────────────────────────────────────
async function loadHistory() {
  if (!sessionId) return;
  try {
    const res = await apiFetch(`/v1/history/${sessionId}`);
    if (!res.ok) return;
    const messages = await res.json();
    if (messages.length) {
      document.getElementById('welcome-msg')?.remove();
      for (const msg of messages) {
        appendBubble(msg.role === 'user' ? 'user' : 'bot', msg.content, false);
      }
      msgCount = messages.length;
      updateSessionDisplay();
      scrollBottom();
    }
  } catch { /* offline — ignore */ }
}

// ── WebSocket ─────────────────────────────────────────────────────
function connectWs() {
  if (ws) { ws.close(); ws = null; }
  if (!sessionId) return;

  setStatus('connecting');

  const url = `${WS_BASE}/v1/ws/chat/${sessionId}`;
  ws = new WebSocket(url);

  ws.addEventListener('open', () => {
    setStatus('ok', 'Connected');
    $btnSend.disabled = false;
  });

  ws.addEventListener('close', () => {
    setStatus('err', 'Disconnected — reconnecting…');
    $btnSend.disabled = true;
    setTimeout(connectWs, 3000);
  });

  ws.addEventListener('error', () => {
    setStatus('err', 'Connection error');
  });

  ws.addEventListener('message', handleWsMessage);
}

let _streamBubble  = null;   // the current bot bubble element being streamed into
let _streamContent = '';

function handleWsMessage(evt) {
  let data;
  try { data = JSON.parse(evt.data); } catch { return; }

  if (data.type === 'token') {
    if (!_streamBubble) {
      removeTypingIndicator();
      _streamBubble = appendBubble('bot', '', false);
      _streamContent = '';
    }
    _streamContent += data.content;
    _streamBubble.textContent = _streamContent;
    scrollBottom();

  } else if (data.type === 'done') {
    if (_streamBubble) {
      _streamContent += data.content;
      _streamBubble.textContent = _streamContent;
    } else {
      removeTypingIndicator();
      appendBubble('bot', data.content, true);
    }
    _streamBubble  = null;
    _streamContent = '';
    msgCount++;
    updateSessionDisplay();
    finishStreaming();

  } else if (data.type === 'error') {
    removeTypingIndicator();
    appendBubble('error', data.error || 'An error occurred', true);
    _streamBubble = null;
    finishStreaming();
  }
}

// ── Sending ───────────────────────────────────────────────────────
async function sendMessage() {
  const text = $input.value.trim();
  if (!text || isStreaming) return;

  document.getElementById('welcome-msg')?.remove();
  appendBubble('user', text, true);
  msgCount++;
  updateSessionDisplay();

  $input.value = '';
  autoResizeInput();
  startStreaming();
  showTypingIndicator();

  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ message: text }));
  } else {
    // Fall back to REST SSE if WebSocket not available
    await sendViaSSE(text);
  }
}

async function sendViaSSE(text) {
  try {
    const res = await apiFetch('/v1/chat/stream', {
      method: 'POST',
      body: JSON.stringify({ message: text, session_id: sessionId }),
    });

    if (!res.ok || !res.body) {
      removeTypingIndicator();
      appendBubble('error', `HTTP ${res.status}`, true);
      finishStreaming();
      return;
    }

    removeTypingIndicator();
    const bubble = appendBubble('bot', '', false);
    let content = '';

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;
        try {
          const evt = JSON.parse(raw);
          if (evt.type === 'token') { content += evt.content; bubble.textContent = content; scrollBottom(); }
          else if (evt.type === 'done') { content += evt.content; bubble.textContent = content; }
        } catch { /* skip malformed SSE line */ }
      }
    }

    msgCount++;
    updateSessionDisplay();
    finishStreaming();

  } catch (err) {
    removeTypingIndicator();
    appendBubble('error', `Failed to send: ${err.message}`, true);
    finishStreaming();
  }
}

// ── DOM helpers ───────────────────────────────────────────────────
function appendBubble(role, content, animate) {
  const wrap = document.createElement('div');
  wrap.className = `message message--${role === 'user' ? 'user' : role === 'error' ? 'error bot' : 'bot'}`;
  if (animate) wrap.style.animationDuration = '.2s';

  const avatar = document.createElement('div');
  avatar.className = 'message__avatar';
  avatar.textContent = role === 'user' ? '🧑' : '⚖';

  const bubble = document.createElement('div');
  bubble.className = 'message__bubble';
  bubble.textContent = content;

  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  $messages.appendChild(wrap);
  scrollBottom();
  return bubble;   // return the inner bubble for streaming updates
}

let _typingEl = null;
function showTypingIndicator() {
  removeTypingIndicator();
  const wrap = document.createElement('div');
  wrap.className = 'message message--bot';
  wrap.id = 'typing-indicator';

  const avatar = document.createElement('div');
  avatar.className = 'message__avatar';
  avatar.textContent = '⚖';

  const bubble = document.createElement('div');
  bubble.className = 'message__bubble';

  const ind = document.createElement('div');
  ind.className = 'typing-indicator';
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement('div');
    dot.className = 'typing-dot';
    ind.appendChild(dot);
  }
  bubble.appendChild(ind);
  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  $messages.appendChild(wrap);
  _typingEl = wrap;
  scrollBottom();
}
function removeTypingIndicator() {
  document.getElementById('typing-indicator')?.remove();
  _typingEl = null;
}

function scrollBottom() {
  $messages.scrollTop = $messages.scrollHeight;
}

function startStreaming() {
  isStreaming = true;
  $btnSend.disabled = true;
  $hint.textContent = 'Generating…';
}
function finishStreaming() {
  isStreaming = false;
  $btnSend.disabled = (ws?.readyState !== WebSocket.OPEN);
  $hint.textContent = '';
}

// ── Status indicator ──────────────────────────────────────────────
function setStatus(state, label) {
  $statusDot.className = `status-dot${state !== 'connecting' ? ` status-dot--${state}` : ''}`;
  $statusLabel.textContent = label ?? {
    ok:          'Connected',
    err:         'Disconnected',
    warn:        'Degraded',
    connecting:  'Connecting…',
  }[state] ?? state;
}

// ── Auth helper ───────────────────────────────────────────────────
function getAuthHeaders() {
  const mode  = $authMode.value;
  const token = $authToken.value.trim();
  const hdrs  = { 'Content-Type': 'application/json' };
  if (mode === 'api_key'  && token) hdrs['X-API-Key'] = token;
  if (mode === 'openbao'  && token) hdrs['Authorization'] = `Bearer ${token}`;
  return hdrs;
}

async function apiFetch(path, opts = {}) {
  return fetch(`${API_BASE}${path}`, {
    ...opts,
    headers: { ...getAuthHeaders(), ...(opts.headers ?? {}) },
  });
}

// ── Event bindings ────────────────────────────────────────────────
function bindEvents() {
  $btnSend.addEventListener('click', sendMessage);

  $input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  $input.addEventListener('input', () => {
    $btnSend.disabled = !$input.value.trim() || isStreaming || ws?.readyState !== WebSocket.OPEN;
    autoResizeInput();
  });

  $btnNew.addEventListener('click', () => {
    localStorage.removeItem(LS_KEY);
    location.reload();
  });

  $btnClear.addEventListener('click', async () => {
    if (!sessionId) return;
    if (!confirm('Clear all messages in this session?')) return;
    await apiFetch(`/v1/sessions/${sessionId}`, { method: 'DELETE' });
    localStorage.removeItem(LS_KEY);
    location.reload();
  });

  $authMode.addEventListener('change', () => {
    const needs = $authMode.value !== 'none';
    $authToken.style.display = needs ? '' : 'none';
    if (needs) $authToken.focus();
    // Reconnect WS so new auth headers take effect (WS can't have custom headers,
    // so for OpenBao/api_key modes the WS path relies on a short-lived token query
    // param or a handshake message — for now just reconnect REST path)
  });

  // Mobile sidebar
  $sidebarOpen.addEventListener('click', () => {
    $sidebar.classList.add('is-open');
    $sidebarOpen.setAttribute('aria-expanded', 'true');
  });
  $sidebarClose.addEventListener('click', () => {
    $sidebar.classList.remove('is-open');
    $sidebarOpen.setAttribute('aria-expanded', 'false');
  });
}

function autoResizeInput() {
  $input.style.height = 'auto';
  $input.style.height = Math.min($input.scrollHeight, 200) + 'px';
}
