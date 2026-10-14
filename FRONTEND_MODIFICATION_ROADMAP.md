# Frontend Modification Roadmap

**Status:** Ready to Begin  
**Approach:** One file per phase, incremental testing  
**Goal:** Integrate backend research agent + support long information responses  

---

## Phase Overview

```
Phase 1: Event Protocol (30 min)
  File: frontend/src/lib/events.ts
  Change: Add response_ready event type
  Why: Backend needs a way to send integrated response data
  
Phase 2: State Management (45 min)
  Files: 
    - frontend/src/presentation/state/presentation.ts
    - frontend/src/presentation/state/usePresentation.ts
  Change: Add response_mode, sources, voice_response to state
  Why: State must hold new data for display components to use
  
Phase 3: Display Layer (60 min)
  File: frontend/src/presentation/Captions.tsx
  Change: Update to display long responses + sources
  Why: Current design assumes short single-line text
  
Phase 4: Compatibility (30 min)
  File: frontend/src/presentation/state/presentation.ts
  Change: Handle build_complete.workspace field
  Why: Backend changed url→workspace; need graceful handling
  
Phase 5: Polish (optional, 30 min)
  Files: Stage.tsx, custom styles
  Change: Enhanced source display, mode-aware styling
  Why: Better UX for different response types
```

---

## Phase 1: Event Protocol

### **File to Modify**
`frontend/src/lib/events.ts`

### **Current State**
42 event types defined, NO source/citation handling

### **What Needs Adding**
New event type for integrated response data:

```typescript
| { 
    type: "response_ready"; 
    response: string;           // Full display text (up to 8192 tokens)
    voice_response?: string;    // Short text for TTS (~50-100 words)
    response_mode: "chat" | "information" | "build" | "task" | "error";
    sources?: Array<{
      title: string;
      url: string;
    }>;
  }
```

### **Why This Event Type**
1. Bundles response + voice_response + mode + sources
2. Backwards compatible (all fields except type are optional)
3. Replaces/supplements the current token+speak path
4. Allows atomic response state updates

### **Testing After Phase 1**
```bash
# Backend sends response_ready
# Frontend receives it (no crash even though no handler yet)
# Existing token+speak path still works
```

---

## Phase 2: State Management

### **Files to Modify**
1. `frontend/src/presentation/state/presentation.ts` — Add state fields
2. `frontend/src/presentation/state/usePresentation.ts` — Handle event routing

### **What Needs Changing**

**In presentation.ts:**

Add to `PresentationState` interface:
```typescript
response_mode: "chat" | "information" | "build" | "task" | "error";
displayResponse: string;
voiceResponse: string;
sources: Array<{ title: string; url: string }>;
```

Add to `initialState`:
```typescript
response_mode: "chat",
displayResponse: "",
voiceResponse: "",
sources: [],
```

Add to reducer `reduce()` function:
```typescript
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

// Update existing case for backward compatibility:
case "build_complete": {
  // Handle both url (old) and workspace (new)
  // const workspace = action.workspace || action.url;
  return firePulse(
    { ...state, phases: allDone(state.phases), emotion: "happy" },
    "success",
  );
}
```

**In usePresentation.ts:**

Separate voice_response handling (if backend sends it as separate event):
```typescript
case "voice_response": {
  speakingLock.current = true;
  audioBus.resume();
  dispatch({ type: "state", state: "speaking" });
  speakBrowser(ev.text, {
    onEnd: () => {
      speakingLock.current = false;
      dispatch({ type: "state", state: "idle" });
    },
  });
  return;
}
```

### **Why These Changes**
- response_mode: identify response type for styling/behavior
- displayResponse: store full text for display
- voiceResponse: store short text for TTS only
- sources: store research citations

### **Testing After Phase 2**
```bash
# Backend sends response_ready
# State updates with new fields
# Captions.tsx still receives state.caption (from old token path)
# No visual changes yet; all behind-the-scenes
```

---

## Phase 3: Display Layer

### **File to Modify**
`frontend/src/presentation/Captions.tsx`

### **Current Implementation**
```typescript
interface Props {
  text: string;              // state.caption
  suggestion: string | null;
  visible: boolean;
}

// Displays single line of streaming text
// Fades in/out with animation
// Max width: 3xl (48rem)
```

### **What Needs Changing**

**Props additions:**
```typescript
interface Props {
  text: string;                    // Keep for compatibility
  suggestion: string | null;
  visible: boolean;
  displayResponse?: string;        // Full response (NEW)
  voiceResponse?: string;          // Short response (NEW)
  sources?: Array<{                // Citations (NEW)
    title: string;
    url: string;
  }>;
  response_mode?: string;          // Response type (NEW)
}
```

**Logic updates:**
```typescript
// Determine what to display
const responseText = displayResponse || text;  // Prefer new path
const showSources = sources && sources.length > 0;

// Display modes:
// - chat: single line as current
// - information: multi-line + sources
// - build/task/error: styled differently
```

**Rendering changes:**
```tsx
// Multi-line support (instead of single <p>)
<div className="max-h-[60vh] overflow-y-auto">
  <p className="whitespace-pre-wrap">{responseText}</p>
  
  {showSources && (
    <div className="mt-6 border-t border-white/10 pt-4">
      <p className="mb-3 text-xs uppercase tracking-wider text-white/50">
        Sources
      </p>
      {sources.map((src, i) => (
        <a key={i} href={src.url} className="text-cyan-300 hover:underline">
          {src.title}
        </a>
      ))}
    </div>
  )}
</div>
```

### **Why These Changes**
- Support long responses (8K tokens)
- Display sources for INFORMATION_QUERY
- Maintain backward compatibility with streaming text
- Mode-aware styling (optional, Phase 5)

### **Testing After Phase 3**
```bash
# Test 1: Long response (INFORMATION_QUERY)
# - Should display full multi-line response
# - Sources visible below
# - Voice plays short summary only

# Test 2: Short response (CHAT)
# - Should display as before
# - No sources
# - Full response read aloud

# Test 3: Build response (BUILD)
# - Build progress visible
# - Response text minimal or hidden
# - No sources

# Test 4: Existing token stream
# - Should still work (caption appears word-by-word)
# - Fallback when response_ready not used
```

---

## Phase 4: Compatibility

### **File to Modify**
`frontend/src/presentation/state/presentation.ts`

### **What Needs Updating**

**Current code (line ~286):**
```typescript
case "build_complete":
case "edit_complete":
  return firePulse(
    { ...state, phases: allDone(state.phases), emotion: "happy" },
    "success",
  );
```

**Updated code:**
```typescript
case "build_complete":
case "edit_complete": {
  // Handle both old (url) and new (workspace) field names
  // const workspace = action.workspace || action.url;
  // If needed elsewhere, store it:
  // { ...state, lastWorkspace: action.workspace || action.url }
  return firePulse(
    { ...state, phases: allDone(state.phases), emotion: "happy" },
    "success",
  );
}
```

### **Why This Change**
Backend changed from sending `url` to `workspace`. Frontend needs to handle both during transition period.

### **Testing After Phase 4**
```bash
# Test: Build completes
# - Should fire success pulse
# - Regardless of whether event has url or workspace
# - Phases marked as done
```

---

## Phase 5: Polish (Optional)

### **Files to Consider**
- `frontend/src/presentation/Stage.tsx` — Add sources rendering component
- `frontend/src/presentation/Captions.tsx` — Enhanced styling
- New file: `frontend/src/presentation/Sources.tsx` — Dedicated sources display

### **Enhancements**
1. Separate Sources component (abstraction)
2. Mode-aware styling:
   - information: cyan/blue for sources
   - chat: minimal styling
   - build: hidden
3. Attribution: "powered by Tavily"
4. Scrollable long responses with visual indicators
5. Mobile responsiveness for sources

### **Testing After Phase 5**
```bash
# Test: Different response modes
# - INFORMATION_QUERY: sources prominent
# - CHAT: sources hidden
# - BUILD: response hidden, build UI prominent
```

---

## Implementation Sequence

### **Week 1**
```
Day 1: Phase 1 (events.ts) — 30 min
       Phase 2 (state) — 45 min
       Cumulative test
       
Day 2: Phase 3 (Captions) — 60 min
       Manual testing with long responses
       
Day 3: Phase 4 (compatibility) — 30 min
       Test build_complete handling
       
TOTAL: 2.5 hours core work + testing
```

### **Week 2 (Optional)**
```
Phase 5 (polish) — 30 min
Enhanced UX + styling
```

---

## Testing Strategy

### **After Each Phase**
1. No console errors
2. Existing functionality unchanged
3. New event type handled (or gracefully ignored)
4. State updates correctly
5. Visual output correct

### **Full Integration Test**
```
Scenario 1: INFORMATION_QUERY
  User: "What are latest AI trends?"
  ✓ Backend searches (Tavily)
  ✓ Backend sends response_ready with sources
  ✓ Frontend state updates
  ✓ Display shows: full response + sources
  ✓ Audio plays: short voice_response
  
Scenario 2: Normal CHAT
  User: "Hello EDEN"
  ✓ Backend sends token stream
  ✓ Frontend shows: streaming text (old path)
  ✓ Audio plays: full response
  ✓ No sources displayed
  
Scenario 3: BUILD
  User: "Create a todo app"
  ✓ Build phases progress
  ✓ Response minimal/hidden
  ✓ Build constellation visible
  
Scenario 4: Fallback (no response_ready)
  ✓ Old token + speak path still works
  ✓ UI responds normally
  ✓ No crashes
```

---

## File Dependency Graph

```
events.ts
  ↓
  → usePresentation.ts (consumes events)
  → presentation.ts (types)
  
presentation.ts (state)
  ↓
  → usePresentation.ts (reducer)
  → Captions.tsx (props)
  → Stage.tsx (passes props)
  
usePresentation.ts (ingest)
  ↓
  → App.tsx (consumes hook)
```

---

## Rollback Strategy

If any phase breaks:
1. Revert that file only
2. Keep previous phases (they're additive)
3. No data loss in production

---

## Success Criteria

✅ **Phase 1:** Backend can send response_ready; frontend doesn't crash  
✅ **Phase 2:** State contains sources + response_mode + voice_response  
✅ **Phase 3:** Long responses display; sources visible; voice plays short summary  
✅ **Phase 4:** build_complete handles workspace field  
✅ **Phase 5:** Enhanced UX for information responses  

**Overall:** EDEN renders long, sourced responses beautifully while maintaining backward compatibility.

---

## Ready to Start?

Confirm, and we'll begin with **Phase 1: events.ts**

Each phase will:
1. Show you the file before/after
2. Explain every change
3. Verify no breakage
4. Move to next phase

Estimated total time: **3 hours (core) + testing**

