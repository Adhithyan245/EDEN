// Frontend configuration. The WebSocket URL can be overridden via VITE_EDEN_WS.
export const WS_URL: string =
  (import.meta.env.VITE_EDEN_WS as string | undefined) ?? "ws://localhost:8000/ws";

// The backend's HTTP origin (for compiled-app previews), derived from WS_URL.
export const HTTP_BASE: string = (() => {
  try {
    const u = new URL(WS_URL);
    u.protocol = u.protocol === "wss:" ? "https:" : "http:";
    return u.origin;
  } catch {
    return "http://localhost:8000";
  }
})();
