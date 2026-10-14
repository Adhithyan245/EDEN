# EDEN Frontend Architecture Analysis

**Status:** Inspection Only — No modifications  
**Date:** 2026-07-22  
**Purpose:** Identify required changes for backend research agent integration  

---

## 1. Frontend Architecture Overview

```
┌─────────────────────────────────────────────────┐
│ App.tsx                                         │
│ - Initializes WebSocket connection              │
│ - Manages overall React component tree          │
│ - Routes events from socket to presentation     │
└──────────┬──────────────────────────────────────┘
           │
    ┌──────▼────────────┐
    │ EdenSocket        │ (lib/socket.ts)
    │ WebSocket manager │ Auto-reconnect logic
    │ JSON event stream │
    └──────┬────────────┘
           │
    ┌──────▼───────────────────┐
    │ Event Types              │ (lib/events.ts)
    │ 42 event types defined   │
    │ TypeScript interfaces    │
    └──────┬───────────────────┘
           │
    ┌──────▼──────────────────────┐
    │ usePresentation()           │
    │ - Event ingestion           │
    │ - Audio playback control    │
    │ - Reducer dispatch          │
    └──────┬───────────────────────┘
           │
    ┌──────▼──────────────────────┐
    │ presentation.ts (Reducer)   │
    │ - PresentationState         │
    │ - 25 action types           │
    │ - State derivation logic    │
    └──────┬───────────────────────┘
           │
    ┌──────▼────────────────────────┐
    │ Stage.tsx (Renderer)          │
    │ - Ambient environment         │
    │ - Presence (EDEN's face)      │
    │ - BuildStage (progress UI)    │
    │ - Captions (subtitles)        │
    │ - Composer (input)            │
    └───────────────────────────────┘
```

---

## 2. WebSocket Communication

### **File: `frontend/src/lib/socket.ts`**

**Purpose:** Thin WebSocket client with auto-reconnect  
**Design:** "The app is an event renderer"

**Key Components:**

```typescript
export class EdenSocket {
  // Constructor takes:
  // - url: WebSocket URL
  // - onEvent: (event: EdenEvent) => void  ← event handler
  // - onStatus: (connected: boolean) => void
  
  ws.onmessage = (msg) => {
    this.onEvent(JSON.parse(msg.data) as EdenEvent);
  }
}
```

**Current Flow:**
1. App.tsx creates EdenSocket
2. Socket receives JSON messages
3. Each message parsed as EdenEvent
4. Dispatched to usePresentation's `ingest()` callback
5. ingest() dispatches to reducer

**Auto-reconnect:** 1.5s delay on disconnect

---

## 3. Event Types & Message Format

### **File: `frontend/src/lib/events.ts`**

**Current Event Categories:**

```typescript
// Conversation spine (9 events)
- ready
- state (idle | listening | thinking | speaking)
- emotion (13 emotion types)
- token (streamed text)
- reply_done
- speak (text for browser TTS)
- speech_audio (MP3 b64 for ElevenLabs)
- error
- pong

// Agent routing (3 events)
- agent_routing
- task_created
- task_updated

// Build lifecycle (8 events)
- plan_ready
- build_started
- tool_called
- tool_result
- build_narrate
- build_complete  ← HAS BREAKING CHANGE
- build_failed

// Edit lifecycle (3 events)
- edit_started
- edit_complete
- edit_failed

// Collaboration (3 events)
- clarification_requested
- version_restored
- suggestion

// Render verification (4 events)
- render_verifying
- render_verified
- render_failed
- render_repairing
```

**CRITICAL FINDING:** No event type for sources/citations currently defined.

---

## 4. Assistant Response Rendering

### **File: `frontend/src/presentation/Captions.tsx`**

**Purpose:** Display EDEN's spoken/displayed text as cinematic subtitles  
**Current Props:**
```typescript
interface Props {
  text: string;              // ← caption text (streaming)
  suggestion: string | null; // ← optional suggestion
  visible: boolean;          // ← show/hide
}
```

**Current Behavior:**
- Displays `state.caption` (accumulated from `token` events)
- One-line subtitle at bottom of screen
- Fades in/out with motion animations
- No support for multi-line display
- No support for sources/citations

**Text Comes From:**
1. Backend sends `token` events (individual words/chunks)
2. usePresentation accumulates them in `state.caption`
3. Captions.tsx displays `state.caption`

**LIMITATION:** Current design assumes short, single-line captions. Information responses with long text (8K tokens) will overflow.

---

## 5. Voice/TTS Pipeline

### **File: `frontend/src/lib/audio.ts`**

**Two TTS Paths:**

#### Path 1: ElevenLabs (Server Audio)
```typescript
export function playAudioB64(audioB64: string, mime: string, cb?: SpeechCallbacks)

// Called from:
case "speech_audio": {
  playAudioB64(ev.audio_b64, ev.mime, {
    onEnd: () => {
      dispatch({ type: "state", state: "idle" });
    },
  });
}
```

**Current Flow:**
1. Backend sends `speech_audio` event with MP3 b64
2. Decoded to Uint8Array
3. Created as Blob
4. Played through HTMLAudioElement
5. Routed through WebAudio AnalyserNode for amplitude
6. onEnded callback updates state to idle

#### Path 2: Browser SpeechSynthesis (Fallback)
```typescript
export function speakBrowser(text: string, cb?: SpeechCallbacks)

// Called from:
case "speak": {
  speakBrowser(ev.text, {
    onEnd: () => {
      dispatch({ type: "state", state: "idle" });
    },
  });
}
```

**Current Flow:**
1. Backend sends `speak` event with text
2. Passed to window.speechSynthesis
3. No amplitude data available
4. onEnd callback updates state

**AudioBus:**
- Singleton that manages audio context
- Exposes `amplitude` (0..1) sampled by Presence component
- Used for visual feedback (breathing, pulsing)

**CRITICAL FINDING:** No distinction between `response` and `voice_response` currently.  
The `speak` event sends ALL text to TTS.

---

## 6. Build UI / Project Generation

### **File: `frontend/src/presentation/BuildStage.tsx`**

**Purpose:** Display build/edit progress as a constellation of phases

**Current Props:**
```typescript
interface Props {
  visible: boolean;
  appName: string | null;
  mode: "build" | "edit" | null;
  phases: Phase[];
  color: string;
}

interface Phase {
  id: string;
  label: string;
  status: "pending" | "active" | "done" | "failed";
}
```

**Phases Tracked:**

**BUILD_PHASES:**
```
1. Planning
2. Creating files
3. Installing packages
4. Launching
5. Verifying
6. Ready
```

**EDIT_PHASES:**
```
1. Applying change
2. Verifying
3. Ready
```

**Build Completion Event:**

```typescript
case "build_complete":
  // Currently expects:
  // { type: "build_complete"; url: string; app_name: string; task_id: string }
  
  // Backend now sends:
  // { type: "build_complete"; workspace: string; app_name: string; task_id: string }
  // ← BREAKING CHANGE: url → workspace
```

**Identified Issue:** BuildStage receives phases, but doesn't do anything with the URL/workspace. The URL is likely consumed elsewhere (possibly by a build verification event or stored for later use).

Need to find where build_complete.url is actually used.

---

## 7. State Management

### **File: `frontend/src/presentation/state/usePresentation.ts`**

**Hook Structure:**
```typescript
export function usePresentation() {
  const [state, dispatch] = useReducer(reduce, initialState);
  const speakingLock = useRef(false);
  
  const ingest = useCallback((ev: EdenEvent) => {
    // Event ingestion logic
    // Routes to audio playback OR reducer dispatch
  }, []);
  
  return { 
    state,                // PresentationState object
    ingest,               // Event handler
    dispatch,             // Direct dispatch (unused)
    dismissClarify,       // Clear clarification
    userSpoke,            // Reset transient UI
    setListening,         // Mic status
    setConnected,         // Connection status
  };
}
```

**Key Behavior:** `speakingLock`
- Prevents state updates while audio is playing
- Audio end event (not backend state event) drives speaking→idle transition
- Allows smooth audio playback even if backend responds quickly

### **File: `frontend/src/presentation/state/presentation.ts`**

**PresentationState Interface:**
```typescript
export interface PresentationState {
  connected: boolean;           // WebSocket connected
  awake: boolean;               // EDEN illuminated (first interaction)
  presence: Presence;           // off | idle | listening | thinking | speaking
  emotion: EdenEmotion;         // 13 emotions for color/expression
  caption: string;              // Current streaming text
  streaming: boolean;           // Text currently streaming
  building: boolean;            // Build/edit environment active
  buildMode: BuildMode | null;  // "build" | "edit"
  appName: string | null;       // Current app being built/edited
  phases: Phase[];              // Build phase progress
  pulseType: PulseType | null;  // "success" | "concern"
  pulseId: number;              // Increments to fire pulse animation
  clarify: string | null;       // Pending clarification question
  suggestion: string | null;    // Proactive suggestion
  meta: { mode, llm, tts };    // Provider info from /health
}
```

**Reducer Actions:** 25+ action types handling:
- Conversation flow (ready, state, emotion, token, reply_done)
- Agent routing (agent_routing, task_created)
- Build lifecycle (build_started, build_complete, etc.)
- Voice management (speak, speech_audio)
- UI interactions (@dismissClarify, @userSpoke, @listening)

**State Derivation Logic:**
- Phase advancement based on tool calls
- Settling idle state (retiring build environment)
- Pulse firing (visual feedback)
- Awaken (first interaction triggers full UI)

---

## 8. Component Tree

```
App.tsx (WebSocket setup)
  ↓
Stage.tsx (Renderer)
  ├── Ambient.tsx (background effect)
  ├── Presence.tsx (EDEN's face/breathing)
  ├── BuildStage.tsx (project phases)
  │   └── PhaseNode.tsx (individual phase)
  ├── Captions.tsx (subtitles)
  ├── Clarification.tsx (prompt UI)
  └── Composer.tsx (input + mic)
```

**Data Flow:**
```
WebSocket event
  ↓ (EdenSocket)
  ↓ (JSON parsed)
  ↓ (usePresentation.ingest)
  ├─→ Audio playback (speak, speech_audio)
  └─→ dispatch(action) to reducer
      ↓
      PresentationState updated
      ↓
      Stage.tsx re-renders
      ↓
      Child components animate/display
```

---

## 9. Compatibility Issues: What Will Break

### **Issue 1: build_complete Event Change**
```typescript
// OLD (backend currently sends):
{ type: "build_complete"; url: string; ... }

// NEW (backend now sends):
{ type: "build_complete"; workspace: string; ... }
```
**Impact:** If frontend code expects `url`, it will fail silently (url is undefined)  
**Status:** Unknown if this is used; need to grep for build_complete usage

### **Issue 2: No Sources/Citations Support**
**Current:** No event type for sources  
**Needed:** New event carrying research sources  
**Impact:** Frontend can't display citations for INFORMATION_QUERY responses

### **Issue 3: response vs voice_response Not Separated**
**Current:** Single `speak` or `speech_audio` event sent to TTS  
**Needed:** Distinction between:
- `response` (full display text, up to 8192 tokens)
- `voice_response` (short TTS summary, ~50-100 words)
**Impact:** Long INFORMATION_QUERY responses will try to be read aloud in full (bad UX)

### **Issue 4: Caption Overflow**
**Current:** Captions.tsx designed for single-line subtitles  
**Needed:** Support for multi-paragraph long responses  
**Impact:** 8K-token responses will be truncated or overflow screen

### **Issue 5: No response_mode Support**
**Current:** No handling of different response types (chat, information, build, task, error)  
**Needed:** Different styling/layout based on mode  
**Impact:** All responses look the same; can't differentiate information responses

### **Issue 6: Amplitudes May Not Update**
**Current:** AudioBus computes amplitude from speech_audio only  
**Needed:** If voice_response uses browser TTS, amplitude is synthetic  
**Impact:** Visual presentation may be less reactive to voice

---

## 10. Files Requiring Modification

### **TIER 1: Critical (Blocks functionality)**

| File | Reason | Change |
|------|--------|--------|
| `lib/events.ts` | No source/citation event type | Add event type for research sources |
| `presentation.ts` | No source state | Add sources to PresentationState |
| `presentation.ts` | No response_mode | Add response_mode to PresentationState |

### **TIER 2: High (Affects UX)**

| File | Reason | Change |
|------|--------|--------|
| `usePresentation.ts` | No handling for voice_response | Split speak/speech_audio for voice vs display |
| `Captions.tsx` | Single-line only | Support multi-line/scrollable display |

### **TIER 3: Medium (Improves compatibility)**

| File | Reason | Change |
|------|--------|--------|
| `presentation.ts` | build_complete URL handling | Handle workspace property |
| `presentation.ts` | No response mode awareness | Style/behavior based on response_mode |

### **TIER 4: Nice-to-have (Polish)**

| File | Reason | Change |
|------|--------|--------|
| `Captions.tsx` | No citations shown | Render sources below response |
| `Stage.tsx` | No citation layer | Add sources visualization |

---

## 11. Recommended Modification Order

### **Phase 1: Event Protocol (CRITICAL)**
**Files:** 
1. `lib/events.ts` — Add new event types

**Why first:** Backend can now send new events, but frontend won't crash if events are missing. Add types before consuming them.

**What to add:**
```typescript
// Add to EdenEvent union:
| { 
    type: "response_ready"; 
    response: string;           // Full display text
    voice_response?: string;    // Short TTS text (optional)
    response_mode: "chat" | "information" | "build" | "task" | "error";
    sources?: Array<{
      title: string;
      url: string;
    }>;
  }

// OR split into separate events:
| { type: "display_response"; text: string; response_mode: string; sources?: ... }
| { type: "voice_response"; text: string }
```

---

### **Phase 2: State Management (CRITICAL)**
**Files:**
2. `presentation.ts` — Add response_mode + sources to state
3. `usePresentation.ts` — Handle voice_response separately

**Why second:** State structure changes before display logic  
**What to add:**
```typescript
// In PresentationState:
response_mode: "chat" | "information" | "build" | "task" | "error";
sources: Array<{ title: string; url: string }>;
displayResponse: string;  // Full response for display
voiceResponse: string;    // Short response for TTS
```

---

### **Phase 3: Display Layer (HIGH)**
**Files:**
4. `Captions.tsx` — Update to support long responses + sources
5. `Stage.tsx` — Add citations/sources visualization

**Why third:** State exists, now display it  
**What to change:**
- Captions.tsx: from single-line to multi-line scrollable
- Add sources list component
- Add response_mode styling

---

### **Phase 4: Behavioral Updates (MEDIUM)**
**Files:**
6. `presentation.ts` — Handle build_complete workspace field
7. `presentation.ts` — Response mode-aware behavior

**Why fourth:** Won't break anything if skipped; improves robustness

---

### **Phase 5: Polish (NICE-TO-HAVE)**
**Files:**
8. Visual enhancements for sources
9. Response mode styling variants

---

## 12. Detailed Change Map

### **CHANGE 1: lib/events.ts**
```typescript
// BEFORE:
export type EdenEvent = 
  | { type: "token"; text: string }
  | { type: "reply_done"; text: string }
  // ... 40+ more types

// AFTER: Add new event type
export type EdenEvent = 
  | { type: "token"; text: string }
  | { type: "reply_done"; text: string }
  | { type: "response_ready"; response: string; voice_response?: string; response_mode: string; sources?: Array<{ title: string; url: string }> }
  // ... existing types
```

---

### **CHANGE 2: presentation.ts (State)**
```typescript
// BEFORE:
export interface PresentationState {
  caption: string;
  streaming: boolean;
  // ... 11 more fields
}

// AFTER: Add
export interface PresentationState {
  caption: string;
  streaming: boolean;
  response_mode: "chat" | "information" | "build" | "task" | "error";
  displayResponse: string;
  voiceResponse: string;
  sources: Array<{ title: string; url: string }>;
  // ... existing fields
}
```

---

### **CHANGE 3: presentation.ts (Reducer)**
```typescript
// Add case:
case "response_ready": {
  return {
    ...state,
    displayResponse: action.response,
    voiceResponse: action.voice_response || action.response,
    response_mode: action.response_mode,
    sources: action.sources || [],
    caption: "",  // Clear streaming caption
    streaming: false,
  };
}

case "build_complete": {
  // Update to handle workspace field:
  // const workspace = action.workspace || action.url;
  // (for backward compatibility)
}
```

---

### **CHANGE 4: usePresentation.ts**
```typescript
// BEFORE: single speak/speech_audio path
case "speak": {
  speakBrowser(ev.text, { ... });
}

// AFTER: distinguish voice_response
case "voice_response": {
  speakBrowser(ev.text, { ... });
}

// Handle response_ready separately if voice_response is in that event
```

---

### **CHANGE 5: Captions.tsx**
```typescript
// BEFORE:
export default function Captions({ text, suggestion, visible }: Props)
// - Single line
// - No sources

// AFTER:
export default function Captions({ 
  text, 
  suggestion, 
  visible,
  sources,              // NEW
  response_mode,        // NEW
  displayResponse,      // NEW
  voiceResponse,        // NEW (for debugging)
}: Props)
// - Multi-line scrollable display
// - Sources list below response
// - Mode-aware styling
```

---

## 13. Backward Compatibility Strategy

### **Option A: Parallel Events (Safest)**
Backend sends BOTH old events AND new events:
```
OLD: token, speak, speech_audio
NEW: response_ready
```
Frontend handles both, prefers new.

**Pros:** Zero frontend breakage  
**Cons:** Backend duplicates data

### **Option B: Gradual Migration**
Backend sends response_ready for INFORMATION_QUERY only:
```
CONVERSATION: token + speak (old path)
INFORMATION_QUERY: response_ready + voice_response (new path)
BUILD: existing events (unchanged)
```

**Pros:** Minimal backend changes  
**Cons:** Requires handling both paths in frontend

### **Option C: Clean Break (Simplest)**
Backend always sends response_ready:
```
All responses: response_ready
```
Frontend defaults voice_response to response if not provided.

**Pros:** Clean, consistent  
**Cons:** Requires coordinated backend/frontend rollout

---

## 14. Testing Checklist

### **After Phase 1 (events.ts changes):**
- [ ] Backend sends response_ready with all fields
- [ ] Frontend doesn't crash on response_ready (no handler yet)
- [ ] Existing tokens/speak still work

### **After Phase 2 (state changes):**
- [ ] response_ready → state update
- [ ] sources stored in state
- [ ] response_mode stored in state

### **After Phase 3 (display changes):**
- [ ] Long responses display without truncation
- [ ] Sources visible below response
- [ ] Multiple sources render correctly
- [ ] Existing short responses still work

### **After Phase 4 (behavior updates):**
- [ ] build_complete handles workspace field
- [ ] Response mode affects styling
- [ ] INFORMATION_QUERY responses have different appearance

---

## 15. Current Assumptions to Verify

1. **Is build_complete.url used?** Grep needed to find where URL is stored/used.
2. **Does frontend open URL automatically?** Or just store it?
3. **Are there any external components displaying responses?** Outside of Captions.tsx?
4. **Does the build environment need to reference URL anywhere?**

---

## Summary

### **Architecture Health:**
- ✅ Clean event-driven design
- ✅ Proper state management with useReducer
- ✅ Good separation of concerns
- ✅ Audio handling is sophisticated

### **Required Changes:**
- ❌ No source/citation event type
- ❌ No response_mode support
- ❌ No voice_response separation
- ⚠️ Caption UI assumes short text only
- ⚠️ build_complete event needs field rename handling

### **Risk Level:**
- **Low Risk:** Event types, state additions (backward compatible)
- **Medium Risk:** Captions.tsx changes (visual layout)
- **High Risk:** None identified

### **Recommended Approach:**
1. Add event types (no behavior change)
2. Add state fields (reducer defaults to old behavior)
3. Update display components (incremental, testable)
4. Verify build_complete.url handling
5. Deploy with feature flag for response_ready handling

---

## Appendix: File Locations

```
frontend/
├── src/
│   ├── App.tsx                          ← Main app, WebSocket setup
│   ├── lib/
│   │   ├── socket.ts                    ← WebSocket client
│   │   ├── events.ts                    ← Event types (CHANGE: add types)
│   │   └── audio.ts                     ← TTS playback
│   ├── presentation/
│   │   ├── Stage.tsx                    ← Main renderer
│   │   ├── Captions.tsx                 ← Display response text (CHANGE)
│   │   ├── BuildStage.tsx               ← Build UI (review only)
│   │   ├── Presence.tsx                 ← EDEN's face
│   │   ├── Composer.tsx                 ← Input box
│   │   ├── Clarification.tsx            ← Clarification prompt
│   │   ├── Ambient.tsx                  ← Background effects
│   │   ├── PhaseNode.tsx                ← Phase node (visual)
│   │   └── state/
│   │       ├── presentation.ts          ← Reducer (CHANGE: add state)
│   │       └── usePresentation.ts       ← Hook (CHANGE: voice handling)
│   └── main.tsx                         ← React entry
```

