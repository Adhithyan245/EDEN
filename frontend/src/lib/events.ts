// TypeScript mirror of backend/app/events.py — the shared event protocol.

export type EdenState = "idle" | "listening" | "thinking" | "speaking";

export type EdenEvent =
  | { type: "ready"; mode: string; llm: string; tts: string; user_name: string }
  | { type: "state"; state: EdenState }
  | { type: "token"; text: string }
  | { type: "reply_done"; text: string }
  | { type: "speak"; text: string }
  | { type: "speech_audio"; audio_b64: string; mime: string }
  | { type: "error"; message: string }
  | { type: "pong" };

export type OutgoingEvent =
  | { type: "user_message"; text: string }
  | { type: "ping" };
