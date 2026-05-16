/**
 * Collaboration WebSocket client.
 *
 * Wraps a single WS connection to /api/v1/ws/surveys/{id}, handles JWT
 * auth handshake, exponential-backoff reconnect, heartbeats, and
 * dispatches typed events to a single message handler.
 */

export type CollabIncomingMessage =
    | { type: 'auth.ok'; connection_id: string; color: string }
    | { type: 'presence.snapshot'; users: CollaboratorPresence[] }
    | { type: 'presence.join'; user: CollaboratorPresence }
    | { type: 'presence.leave'; user_id: string; connection_id: string }
    | {
        type: 'focus.update';
        connection_id: string;
        user_id: string;
        display_name: string;
        color: string;
        question_id: string | null;
        expires_at: string | null;
    }
    | {
        type: 'survey.saved';
        version: number;
        actor_user_id: string;
        updated_at: string;
    }
    | { type: 'heartbeat.ack' }
    | { type: 'pong' }
    | { type: 'error'; code?: string; detail?: string };

export interface CollaboratorPresence {
    connection_id: string;
    user_id: string;
    display_name: string;
    color: string;
    focused_question_id: string | null;
    focus_expires_at: string | null;
    joined_at: string;
}

export type CollabSocketStatus =
    | 'idle'
    | 'connecting'
    | 'open'
    | 'reconnecting'
    | 'closed';

export interface CollabSocketOptions {
    surveyId: string;
    /** Lazy access-token getter so refresh tokens propagate. */
    getToken: () => string | null;
    onMessage: (msg: CollabIncomingMessage) => void;
    onStatusChange?: (status: CollabSocketStatus) => void;
}

const HEARTBEAT_INTERVAL_MS = 30_000;
const MAX_BACKOFF_MS = 30_000;
const INITIAL_BACKOFF_MS = 1_000;

function buildWsUrl(surveyId: string): string {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Use the same host:port — Vite dev server proxies, prod serves both.
    const host = window.location.host;
    return `${proto}//${host}/api/v1/ws/surveys/${encodeURIComponent(surveyId)}`;
}

export class CollabSocket {
    private ws: WebSocket | null = null;
    private heartbeatTimer: number | null = null;
    private reconnectTimer: number | null = null;
    private backoffMs = INITIAL_BACKOFF_MS;
    private closed = false;
    private status: CollabSocketStatus = 'idle';
    private connectionId: string | null = null;
    private readonly opts: CollabSocketOptions;

    constructor(opts: CollabSocketOptions) {
        this.opts = opts;
    }

    open() {
        if (this.ws || this.closed) return;
        this.connect();
    }

    close() {
        this.closed = true;
        this.setStatus('closed');
        this.clearTimers();
        if (this.ws) {
            try {
                this.ws.close();
            } catch {
                /* noop */
            }
            this.ws = null;
        }
    }

    /** Tell the server which question this user is now editing. */
    acquireFocus(questionId: string | null) {
        this.send({ type: 'focus.acquire', question_id: questionId });
    }

    releaseFocus() {
        this.send({ type: 'focus.release' });
    }

    /** Connection id assigned by the server, available after auth.ok. */
    getConnectionId(): string | null {
        return this.connectionId;
    }

    // ── internals ──────────────────────────────────────────────────

    private connect() {
        const token = this.opts.getToken();
        if (!token) {
            // Without auth, defer; caller will reopen on login.
            this.setStatus('idle');
            return;
        }

        this.setStatus(this.backoffMs === INITIAL_BACKOFF_MS ? 'connecting' : 'reconnecting');

        let ws: WebSocket;
        try {
            ws = new WebSocket(buildWsUrl(this.opts.surveyId));
        } catch {
            this.scheduleReconnect();
            return;
        }
        this.ws = ws;

        ws.onopen = () => {
            // First frame must be auth.
            ws.send(JSON.stringify({ type: 'auth', token }));
        };

        ws.onmessage = (event) => {
            let parsed: CollabIncomingMessage;
            try {
                parsed = JSON.parse(event.data) as CollabIncomingMessage;
            } catch {
                return;
            }
            if (parsed.type === 'auth.ok') {
                this.connectionId = parsed.connection_id;
                this.setStatus('open');
                // Reset backoff after a stable connection.
                this.backoffMs = INITIAL_BACKOFF_MS;
                this.startHeartbeat();
            }
            this.opts.onMessage(parsed);
        };

        ws.onerror = () => {
            // Browsers don't expose error details; treat as a closed event.
        };

        ws.onclose = (event) => {
            this.clearTimers();
            this.ws = null;
            this.connectionId = null;
            if (this.closed) return;

            // Auth failures (4401/4403) should not loop forever.
            if (event.code === 4401 || event.code === 4403) {
                this.setStatus('closed');
                this.opts.onMessage({
                    type: 'error',
                    code: String(event.code),
                    detail: event.reason || '认证失败',
                });
                return;
            }
            this.scheduleReconnect();
        };
    }

    private send(msg: unknown) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
                this.ws.send(JSON.stringify(msg));
            } catch {
                /* drop */
            }
        }
    }

    private startHeartbeat() {
        this.clearHeartbeat();
        this.heartbeatTimer = window.setInterval(() => {
            this.send({ type: 'heartbeat' });
        }, HEARTBEAT_INTERVAL_MS);
    }

    private clearHeartbeat() {
        if (this.heartbeatTimer !== null) {
            window.clearInterval(this.heartbeatTimer);
            this.heartbeatTimer = null;
        }
    }

    private scheduleReconnect() {
        if (this.closed) return;
        this.setStatus('reconnecting');
        this.clearReconnect();
        const delay = this.backoffMs;
        this.backoffMs = Math.min(this.backoffMs * 2, MAX_BACKOFF_MS);
        this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
    }

    private clearReconnect() {
        if (this.reconnectTimer !== null) {
            window.clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }

    private clearTimers() {
        this.clearHeartbeat();
        this.clearReconnect();
    }

    private setStatus(next: CollabSocketStatus) {
        if (this.status === next) return;
        this.status = next;
        this.opts.onStatusChange?.(next);
    }
}
