// Presentation state — derived entirely from backend events, never polled.
//
// A single reducer turns the EdenEvent stream into the visual truth the UI
// renders: the presence macro-state (what EDEN's "face" is doing), the emotion
// (hue + micro-expression), the current caption, the build/edit environment and
// its phases, transient success/concern pulses, and collaboration prompts.
//
// High-frequency values (voice amplitude, breathing) do NOT live here — they are
// sampled from the AudioBus on requestAnimationFrame so this reducer only reacts
// to low-frequency events and never drives per-frame re-renders.

import type { EdenEmotion, EdenEvent, EdenState, ResponseMode, ResponseSource } from "../../lib/events";

export type Presence = "off" | "idle" | "listening" | "thinking" | "speaking";
export type BuildMode = "build" | "edit";
export type PulseType = "success" | "concern";
export type PhaseStatus = "pending" | "active" | "done" | "failed";

export interface Phase {
  id: string;
  label: string;
  status: PhaseStatus;
}

export interface PresentationState {
  connected: boolean;
  awake: boolean;                 // has EDEN illuminated this session
  presence: Presence;
  emotion: EdenEmotion;
  caption: string;                // EDEN's current spoken text (streamed)
  streaming: boolean;
  building: boolean;              // the build/edit environment is active
  buildMode: BuildMode | null;
  appName: string | null;
  phases: Phase[];
  pulseType: PulseType | null;    // one-shot bloom (success / concern)
  pulseId: number;                // increments to fire a new pulse
  clarify: string | null;         // pending clarification question
  suggestion: string | null;      // gentle proactive suggestion
  preview: { url: string; appName: string | null; version: number } | null; // compiled app
  meta: { mode: string; llm: string; tts: string };
  // --- structured response fields (additive; do not replace caption system) ---
  responseMode: ResponseMode;     // category of the last completed response
  displayResponse: string;        // full text for visual display
  voiceResponse: string;          // condensed text for TTS (falls back to displayResponse)
  sources: ResponseSource[];      // research sources when responseMode === "information"
}

export const initialState: PresentationState = {
  connected: false,
  awake: false,
  presence: "off",
  emotion: "idle",
  caption: "",
  streaming: false,
  building: false,
  buildMode: null,
  appName: null,
  phases: [],
  pulseType: null,
  pulseId: 0,
  clarify: null,
  suggestion: null,
  preview: null,
  meta: { mode: "—", llm: "—", tts: "—" },
  responseMode: "chat",
  displayResponse: "",
  voiceResponse: "",
  sources: [],
};

/** EDEN's current colour, derived identically wherever it is needed. */
export function colorFor(presence: Presence, emotion: EdenEmotion): string {
  if (presence === "thinking") return EMOTION_COLOR.thinking;
  if (presence === "listening") return "#5eead4";
  return EMOTION_COLOR[emotion];
}

export const EMOTION_COLOR: Record<EdenEmotion, string> = {
  idle: "#38bdf8",
  happy: "#34d399",
  confident: "#22d3ee",
  thinking: "#a855f7",
  curious: "#818cf8",
  sarcastic: "#fbbf24",
  concerned: "#fb7185",
};

const BUILD_PHASES: Phase[] = [
  { id: "planning", label: "Planning", status: "pending" },
  { id: "files", label: "Creating files", status: "pending" },
  { id: "install", label: "Installing packages", status: "pending" },
  { id: "compile", label: "Compiling", status: "pending" },
  { id: "verify", label: "Verifying", status: "pending" },
  { id: "done", label: "Ready", status: "pending" },
];

const EDIT_PHASES: Phase[] = [
  { id: "edit", label: "Applying change", status: "pending" },
  { id: "compile", label: "Compiling", status: "pending" },
  { id: "verify", label: "Verifying", status: "pending" },
  { id: "done", label: "Ready", status: "pending" },
];

// Internal (non-event) actions dispatched by the UI itself.
export type Action =
  | EdenEvent
  | { type: "@dismissClarify" }
  | { type: "@userSpoke" }
  | { type: "@listening"; active: boolean }
  | { type: "@connected"; connected: boolean };

// --- phase helpers -----------------------------------------------------------

function seed(phases: Phase[]): Phase[] {
  return phases.map((p) => ({ ...p, status: "pending" as PhaseStatus }));
}

/** Mark every phase before `id` done and `id` active. */
function advanceTo(phases: Phase[], id: string): Phase[] {
  const idx = phases.findIndex((p) => p.id === id);
  if (idx === -1) return phases;
  return phases.map((p, i) => {
    if (i < idx) return p.status === "failed" ? p : { ...p, status: "done" };
    if (i === idx) return { ...p, status: "active" };
    return p;
  });
}

function markDone(phases: Phase[], id: string): Phase[] {
  return phases.map((p) => (p.id === id ? { ...p, status: "done" } : p));
}

function allDone(phases: Phase[]): Phase[] {
  return phases.map((p) => ({ ...p, status: "done" as PhaseStatus }));
}

function failActive(phases: Phase[]): Phase[] {
  let hit = false;
  return phases.map((p) => {
    if (!hit && (p.status === "active" || p.status === "pending")) {
      hit = true;
      return { ...p, status: "failed" };
    }
    return p;
  });
}

function presenceFromState(s: EdenState): Presence {
  return s; // EdenState is a subset of Presence
}

function awaken(state: PresentationState): PresentationState {
  return state.awake ? state : { ...state, awake: true };
}

function firePulse(state: PresentationState, type: PulseType): PresentationState {
  return { ...state, pulseType: type, pulseId: state.pulseId + 1 };
}

// --- reducer -----------------------------------------------------------------

export function reduce(state: PresentationState, action: Action): PresentationState {
  switch (action.type) {
    case "@connected":
      return { ...state, connected: action.connected };
    case "@dismissClarify":
      return { ...state, clarify: null };
    case "@userSpoke":
      // A new user turn clears transient prompts.
      return { ...state, clarify: null, suggestion: null };

    case "@listening": {
      // Local, mic-driven presence — never overrides a real backend state
      // like "speaking" or an active build; only idle/thinking flips visually
      // to show the mic is live, and only settles back to idle (never yanks
      // the face out of thinking/speaking/building when the mic stops).
      if (state.building || state.presence === "speaking") return state;
      if (action.active) return { ...awaken(state), presence: "listening" };
      return state.presence === "listening" ? { ...state, presence: "idle" } : state;
    }

    case "ready":
      return { ...state, meta: { mode: action.mode, llm: action.llm, tts: action.tts } };

    case "state": {
      const next = { ...awaken(state), presence: presenceFromState(action.state) };
      if (action.state === "idle") {
        // Audio ended — retire captions and settle the build environment.
        const settled = settleIdle({ ...next, caption: "" });
        // During an active build, stay engaged between narrations instead of going fully idle.
        if (settled.building) return { ...settled, presence: "thinking" };
        return settled;
      }
      return next;
    }

    case "emotion":
      // Every spoken segment begins with an emotion — start a fresh caption.
      return { ...awaken(state), emotion: action.emotion, caption: "", streaming: true };

    case "token":
      return { ...awaken(state), caption: state.caption + action.text };

    case "reply_done":
      return { ...state, streaming: false };

    // --- structured response -------------------------------------------------
    case "response_ready":
      return {
        ...awaken(state),
        displayResponse: action.response,
        // Fall back to the full response when the backend omits a voice variant.
        voiceResponse: action.voice_response ?? action.response,
        responseMode: action.response_mode,
        sources: action.sources ?? [],
        // A completed response ends any streaming caption mode.
        streaming: false,
      };

    // --- build lifecycle -----------------------------------------------------
    case "agent_routing":
      return awaken(state);

    case "task_created": {
      const isEdit = action.task.intent === "edit";
      return {
        ...awaken(state),
        building: true,
        buildMode: isEdit ? "edit" : "build",
        appName: action.task.app_name ?? state.appName,
        phases: isEdit ? advanceTo(seed(EDIT_PHASES), "edit") : advanceTo(seed(BUILD_PHASES), "planning"),
        clarify: null,
        suggestion: null,
      };
    }

    case "plan_ready":
      return {
        ...awaken(state),
        building: true,
        buildMode: "build",
        appName: action.app_name ?? state.appName,
        phases: advanceTo(
          state.phases.length ? state.phases : seed(BUILD_PHASES),
          "files",
        ),
      };

    case "build_started":
      return {
        ...awaken(state),
        building: true,
        buildMode: "build",
        appName: action.app_name ?? state.appName,
        phases: advanceTo(state.phases.length ? state.phases : seed(BUILD_PHASES), "files"),
      };

    case "edit_started":
      return {
        ...awaken(state),
        building: true,
        buildMode: "edit",
        appName: action.app_name ?? state.appName,
        phases: advanceTo(seed(EDIT_PHASES), "edit"),
        clarify: null,
        suggestion: null,
      };

    case "tool_called": {
      if (!state.building) return state;
      const cmd = String((action.args as Record<string, unknown>)?.command ?? "").toLowerCase();
      let phases = state.phases;
      if (action.tool === "create_directory" || action.tool === "create_file") {
        phases = advanceTo(phases, "files");
      } else if (action.tool === "edit_file") {
        phases = advanceTo(phases, "edit");
      } else if (action.tool === "run_command") {
        if (cmd.includes("install")) phases = advanceTo(phases, "install");
        else if (cmd.includes("run build")) phases = advanceTo(phases, "compile");
      } else if (action.tool === "open_browser") {
        phases = advanceTo(phases, "verify");
      }
      return { ...state, phases };
    }

    case "tool_result": {
      if (!state.building) return state;
      let phases = state.phases;
      const failed = !action.success;
      if (failed) return { ...state, phases: failActive(phases) };
      if (action.tool === "run_command") {
        // Completing install advances toward launch visually.
        if (state.phases.some((p) => p.id === "install" && p.status === "active")) {
          phases = markDone(phases, "install");
        }
      }
      return { ...state, phases };
    }

    case "task_updated": {
      if (!state.building) return state;
      const s = action.task.status;
      if (s === "validating") return { ...state, phases: advanceTo(state.phases, "verify") };
      if (s === "completed") return { ...state, phases: allDone(state.phases) };
      if (s === "failed") return { ...state, phases: failActive(state.phases) };
      return state;
    }

    case "build_complete":
    case "edit_complete":
      return firePulse(
        {
          ...state,
          phases: allDone(state.phases),
          emotion: "happy",
          preview: withPreview(state, action.preview_url, action.app_name),
        },
        "success",
      );

    case "build_failed":
    case "edit_failed":
      return firePulse({ ...state, phases: failActive(state.phases), emotion: "concerned" }, "concern");

    case "version_restored":
      return firePulse(
        { ...state, suggestion: null, preview: withPreview(state, action.preview_url, state.appName) },
        "success",
      );

    case "clarification_requested":
      return { ...awaken(state), clarify: action.question };

    case "suggestion":
      return { ...state, suggestion: action.text };

    case "error":
      return firePulse({ ...state, emotion: "concerned" }, "concern");

    // speak / speech_audio / pong / build_narrate — no state change here
    // (speaking is driven by the `state` event; audio is handled in App).
    default:
      return state;
  }
}

/** The new preview link, bumping `version` so the browser reloads it. */
function withPreview(
  state: PresentationState,
  url: string | null | undefined,
  appName: string | null,
): PresentationState["preview"] {
  if (!url) return state.preview;
  return { url, appName, version: (state.preview?.version ?? 0) + 1 };
}

/** Called on each `state: idle` to retire a finished build environment. */
export function settleIdle(state: PresentationState): PresentationState {
  if (state.building && state.phases.every((p) => p.status === "done" || p.status === "failed")) {
    return { ...state, building: false, buildMode: null };
  }
  return state;
}