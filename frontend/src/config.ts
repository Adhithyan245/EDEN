// Frontend configuration. The WebSocket URL can be overridden via VITE_EDEN_WS.
// Production builds default to the deployed Render backend, so a Git-triggered
// Vercel build (which has no VITE_EDEN_WS set) still connects.
export const WS_URL: string =
  (import.meta.env.VITE_EDEN_WS as string | undefined) ??
  (import.meta.env.PROD ? "wss://eden-backend-pusa.onrender.com/ws" : "ws://localhost:8000/ws");

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
