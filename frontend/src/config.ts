// Frontend configuration. The WebSocket URL can be overridden via VITE_EDEN_WS.
export const WS_URL: string =
  (import.meta.env.VITE_EDEN_WS as string | undefined) ?? "ws://localhost:8000/ws";
