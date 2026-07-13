import type { EdenEvent, OutgoingEvent } from "./events";

type EventHandler = (event: EdenEvent) => void;
type StatusHandler = (connected: boolean) => void;

/** Thin WebSocket client with auto-reconnect. The app is an event renderer. */
export class EdenSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private onEvent: EventHandler;
  private onStatus: StatusHandler;
  private reconnectTimer: number | null = null;
  private closed = false;

  constructor(url: string, onEvent: EventHandler, onStatus: StatusHandler) {
    this.url = url;
    this.onEvent = onEvent;
    this.onStatus = onStatus;
  }

  connect(): void {
    this.closed = false;
    this.open();
  }

  private open(): void {
    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => this.onStatus(true);
    this.ws.onclose = () => {
      this.onStatus(false);
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
