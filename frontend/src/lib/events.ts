// TypeScript mirror of backend/app/events.py — the shared event protocol.
// Keep in sync with backend/app/events.py.

export type EdenState = "idle" | "listening" | "thinking" | "speaking";

export type EdenEmotion =
  | "idle"
  | "happy"
  | "confident"
  | "thinking"
  | "curious"
  | "sarcastic"
  | "concerned";

/**
 * Describes the category/mode of a completed AI response.
 * Used by the response_ready event to drive conditional UI rendering.
 */
export type ResponseMode =
  | "chat"
  | "information"
  | "build"
  | "task"
  | "error";

/** A single research source attached to an information response. */
export interface ResponseSource {
  title: string;
  url: string;
  snippet?: string;
}

/** Mirror of Task.to_dict() on the backend. */
export interface TaskInfo {
  id: string;
  user_request: string;
  intent: string;
  status:
    | "pending"
    | "planning"
    | "running"
    | "editing"
    | "validating"
    | "completed"
    | "failed"
    | "cancelled";
  current_step: string | null;
  completed_steps: string[];
  failed_steps: string[];
  retry_count: number;
  working_directory: string | null;
  generated_files: string[];
  executed_commands: string[];
  created_at: string;
  updated_at: string;
  app_type: string | null;
  app_name: string | null;
}

export type EdenEvent =
  // --- conversation spine ---
  | { type: "ready"; mode: string; llm: string; tts: string; user_name: string }
  | { type: "state"; state: EdenState }
  | { type: "emotion"; emotion: EdenEmotion }
  | { type: "token"; text: string }
  | { type: "reply_done"; text: string }
  | { type: "speak"; text: string }
  | { type: "speech_audio"; audio_b64: string; mime: string }
  | { type: "error"; message: string }
  | { type: "pong" }
  // --- structured response (research-aware, narrator-separated) ---
  | {
      type: "response_ready";
      /** Full text for visual display — may include sources, depth, formatting. */
      response: string;
      /** Condensed text for voice playback. Falls back to `response` if absent. */
      voice_response?: string;
      /** Drives conditional UI: sources panel, build status, etc. */
      response_mode: ResponseMode;
      /** Populated when response_mode === "information" and sources were retrieved. */
      sources?: ResponseSource[];
    }
  // --- agent routing / planning ---
  | { type: "agent_routing"; route: string; intent: string; confidence: number }
  | { type: "task_created"; task: TaskInfo }
  | { type: "task_updated"; task: TaskInfo }
  | { type: "plan_ready"; task_id: string; steps: string[]; app_name: string; app_type: string; step_count: number }
  // --- build lifecycle ---
  | { type: "build_started"; app_type: string; app_name: string; task_id: string }
  | { type: "tool_called"; tool: string; args: Record<string, unknown>; step_index: number; task_id: string }
  | { type: "tool_result"; tool: string; success: boolean; output: string; step_index: number; task_id: string }
  | { type: "build_narrate"; text: string; task_id: string }
  | { type: "build_complete"; url: string; app_name: string; task_id: string }
  | { type: "build_failed"; reason: string; used_fallback: boolean; task_id: string }
  // --- edit lifecycle ---
  | { type: "edit_started"; task_id: string; app_name: string; summary: string; files: string[] }
  | { type: "edit_complete"; task_id: string; app_name: string; url: string; files: string[] }
  | { type: "edit_failed"; task_id: string; reason: string; restored: boolean }
  // --- collaboration ---
  | { type: "clarification_requested"; question: string }
  | { type: "version_restored"; task_id: string; action: string; label: string; url: string }
  | { type: "suggestion"; text: string }
  // --- render verification (after HTTP verify, before browser open) ---
  | { type: "render_verifying"; url: string; task_id: string }
  | { type: "render_verified"; url: string; task_id: string }
  | { type: "render_failed"; errors: string[]; error_summary: string; task_id: string }
  | { type: "render_repairing"; attempt: number; error_summary: string; task_id: string };

export type OutgoingEvent =
  | { type: "user_message"; text: string }
  | { type: "ping" };