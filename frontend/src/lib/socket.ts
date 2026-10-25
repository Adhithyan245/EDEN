import type { EdenEvent, OutgoingEvent } from "./events";

type EventHandler = (event: EdenEvent) => void;
type StatusHandler = (connected: boolean) => void;
type AuthHandler = (rejectedCode: boolean) => void;

// Close codes sent by backend/app/guard.py.
const CLOSE_UNAUTHORIZED = 4401;
const CLOSE_FORBIDDEN_ORIGIN = 4403;

/** Base64url of a UTF-8 string — a valid WebSocket subprotocol token. */
function encodeCode(code: string): string {
  const bytes = new TextEncoder().encode(code);
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Thin WebSocket client with auto-reconnect. The app is an event renderer. */
export class EdenSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private onEvent: EventHandler;
  private onStatus: StatusHandler;
  private onAuthRequired: AuthHandler;
  private reconnectTimer: number | null = null;
  private closed = false;
  private code: string | null;

  constructor(
    url: string,
    onEvent: EventHandler,
    onStatus: StatusHandler,
    onAuthRequired: AuthHandler = () => {},
    code: string | null = null,
  ) {
    this.url = url;
    this.onEvent = onEvent;
    this.onStatus = onStatus;
    this.onAuthRequired = onAuthRequired;
    this.code = code;
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  /** Reconnect with a new access code. */
  authenticate(code: string): void {
    this.code = code;
    this.ws?.close();
    this.connect();
  }

  private open(): void {
    // The access code travels as a subprotocol so it never lands in a URL.
    const protocols = ["eden", ...(this.code ? [`code.${encodeCode(this.code)}`] : [])];
    try {
      this.ws = new WebSocket(this.url, protocols);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => this.onStatus(true);
    this.ws.onclose = (ev) => {
      this.onStatus(false);
      if (ev.code === CLOSE_UNAUTHORIZED) {
        // Wait for the user to supply a code instead of hammering the server.
        this.closed = true;
        this.onAuthRequired(this.code !== null);
        return;
      }
      if (ev.code === CLOSE_FORBIDDEN_ORIGIN) {
        this.closed = true;
        return;
      }
      if (!this.closed) this.scheduleReconnect();
    };
    this.ws.onerror = () => this.ws?.close();
    this.ws.onmessage = (msg) => {
      try {
        this.onEvent(JSON.parse(msg.data) as EdenEvent);
      } catch {
        /* ignore malformed frames */
      }
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closed) this.open();
    }, 1500);
  }

  send(event: OutgoingEvent): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(event));
    }
  }

  close(): void {
    this.closed = true;
    this.ws?.close();
  }
}
