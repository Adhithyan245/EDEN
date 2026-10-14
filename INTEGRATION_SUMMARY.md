# EDEN Research Agent & Search Tool Integration

## Overview

EDEN now has a working **live knowledge pipeline**:

```
User Query
    ↓
intent.py (detect INFORMATION_QUERY)
    ↓
router.py (route to CONVERSATION)
    ↓
main.py → Research Phase
    ↓
researcher.py (orchestrate knowledge gathering)
    ↓
search.py (retrieve results from Tavily)
    ↓
Research Context (formatted sources + content)
    ↓
llm_gemini.py (generate response with grounding)
    ↓
narrator.py (display_response + voice_response split)
    ↓
Frontend (render long answer + sources + voice summary)
```

---

## Modified Files

### 1. `app/agents/researcher.py`
**Changes:**
- Added import: `from ..tools.search import SearchResult, SearchTool`
- Added `SearchToolProvider` class: adapts `SearchTool` to the `SearchProvider` interface
  - Converts `SearchResult` objects from `search.py` to `Source` objects used by the Research Agent
  - Handles error states gracefully (returns empty list on failure)

**Why:**
- Allows the Research Agent to use the unified SearchTool layer without directly coupling to Tavily
- Maintains the separation of concerns: researcher.py orchestrates; search.py handles retrieval

### 2. `app/config.py`
**Changes:**
- Added: `self.tavily_api_key = _env("TAVILY_API_KEY")`
- Added property: `has_tavily` → checks if TAVILY_API_KEY is configured

**Why:**
- Makes search configuration available at startup
- Follows existing pattern for optional credentials (gemini, elevenlabs)

### 3. `app/providers/factory.py`
**Changes:**
- Added imports: `SearchTool`, `SearchToolProvider`, `ResearchAgent`
- Added `build_search_tool()`: creates SearchTool with TavilySearchProvider if available
- Added `build_research_agent()`: creates ResearchAgent with SearchToolProvider

**Why:**
- Single point of dependency injection for research infrastructure
- Lazy-loads Tavily only if credentials exist
- Falls back gracefully (no-op SearchTool) if no API key is set

### 4. `app/main.py`
**Changes:**
- Added: `RESEARCH = factory.build_research_agent()` at startup (line 75)
- Added research phase in message handler (before LLM call):
  - Checks if intent is INFORMATION_QUERY
  - Calls `RESEARCH.research(text)` to gather external knowledge
  - Injects research context into the user message sent to Gemini
  - Logs: research start, completion, and any failures
  - Graceful error handling: continues without context if research fails

**Why:**
- INFORMATION_QUERY requests now receive grounding before the LLM responds
- Research context is transparently injected into the prompt
- No impact on CHAT, BUILD, or other intents
- Safe fallback: if Tavily is unavailable, EDEN responds without research

### 5. `backend/.env.example`
**Changes:**
- Added: `# ── Research / Search — optional ──` section with TAVILY_API_KEY example

**Why:**
- Documents the new optional credential
- Follows existing documentation pattern

---

## How It Works

### Test 1: Normal Chat
```
User: "Hello EDEN"
  ↓
Intent: CONVERSATION (no research keywords)
  ↓
Research: skipped (intent ≠ INFORMATION_QUERY)
  ↓
Gemini: responds directly
  ↓
Result: normal short response, unchanged behavior
```

### Test 2: Information Query with Research
```
User: "What are the latest AI trends?"
  ↓
Intent: INFORMATION_QUERY (detected by intent.py)
  ↓
Research Phase:
  • Query refined: "latest AI trends"
  • SearchTool.search() → TavilySearchProvider
  • Returns 5 sources with titles, URLs, content
  • ResearchResult.context built with formatted sources
  ↓
Gemini receives:
  • Original user message
  • [Research context: 5 formatted sources]
  ↓
Gemini response: detailed, well-sourced answer with up-to-date info
  ↓
Narrator: long answer (display) + short summary (voice)
  ↓
Frontend: shows full response + sources list + plays voice summary
```

### Test 3: Information Query, No Search Provider
```
User: "What are the latest AI trends?"
  ↓
Intent: INFORMATION_QUERY
  ↓
Research Phase:
  • TAVILY_API_KEY not set
  • SearchTool.from_environment() returns no-op
  • RESEARCH.research() returns status="no_provider"
  • Log: "Research yielded no results; proceeding without context"
  ↓
Gemini receives:
  • Original user message only (no research context)
  ↓
Gemini response: generated from training data (may be outdated)
  ↓
Result: EDEN still responds gracefully, no crash
```

### Test 4: Search Fails / Times Out
```
User: "Latest blockchain news"
  ↓
Research Phase:
  • Tavily API call fails or times out
  • Exception caught in main.py
  • Log: "Research failed; proceeding without context: <error>"
  ↓
Gemini receives:
  • Original user message only
  ↓
Result: EDEN continues responding, no crash
```

---

## Configuration

### Minimum Setup (No Search)
```bash
# Just use mock LLM + browser voice
python backend/main.py
# All intents work; INFORMATION_QUERY gets no research context
```

### With Tavily Search
```bash
# 1. Get a free API key from https://tavily.com
# 2. Set in .env or environment:
export TAVILY_API_KEY="your_key_here"

# 3. Restart backend
python backend/main.py
# INFORMATION_QUERY now retrieves live data
```

### With Gemini + Tavily
```bash
export GEMINI_API_KEY="your_gemini_key"
export TAVILY_API_KEY="your_tavily_key"
python backend/main.py
# Gemini + Tavily + ElevenLabs voice (if available)
```

---

## Flow Details

### Intent Detection (`app/agents/intent.py`)
No changes needed. Already detects INFORMATION_QUERY from keywords:
- "latest", "recent", "trends", "news", "research", "compare", etc.
- Falls back to LLM classification if needed

### Router (`app/agents/router.py`)
No changes needed. Already routes INFORMATION_QUERY to conversational pipeline:
```python
if intent.intent == IntentType.INFORMATION_QUERY:
    return RoutingDecision(
        route  = Route.CONVERSATION,
        intent = intent,
        ...
    )
```

### Research (`app/agents/researcher.py`)
**Workflow:**
1. `researcher.research(query)` is called with raw user input
2. `_analyze_query(query)` refines it (removes filler words, detects time sensitivity)
3. `SearchProvider.search(refined_query)` retrieves sources
4. `_build_context(sources)` formats them as a readable prompt injection
5. `_assess_confidence(sources)` estimates answer quality
6. Returns `ResearchResult` with sources, context, confidence

**Error Handling:**
- If `SearchProvider` is None → returns empty result, logs warning
- If search times out → returns fallback result, logs error
- If search fails → returns fallback result, logs error
- No exception propagates; caller always receives a valid ResearchResult

### SearchTool (`app/tools/search.py`)
No changes. Used as-is by SearchToolProvider adapter.

**Status codes:**
- `"ok"` → results found, use them
- `"empty"` → query valid, no results
- `"unavailable"` → no provider configured
- `"error"` → API failure or timeout

### Gemini Integration (`app/providers/llm_gemini.py`)
No changes needed. Already tuned for INFORMATION_QUERY:
```python
if intent == IntentType.INFORMATION_QUERY:
    return {"max_output_tokens": 8192, "temperature": 0.5}
```
This gives the model plenty of tokens and low temperature for accuracy.

### System Prompt (`app/prompts/eden_personality.py`)
No changes. Research context is injected per-message in main.py, not in the system prompt.
This keeps personality separate from knowledge.

---

## Data Flow: Research Context

Research context is injected into the user message as a bracketed annotation:

```json
{
  "role": "user",
  "content": "What are the latest AI trends?\n\n[Research context:\n[Source 1] ...\n\n[Source 2] ...\n...]"
}
```

This approach:
- ✅ Keeps Gemini's JSON output clean (personality layer still works)
- ✅ Makes sources transparent to the model (it can cite them)
- ✅ Survives message history (context stays with the user message)
- ✅ No need to change LLM provider interface
- ✅ Works with voice summary extraction (context is in the message, not the response)

---

## Error Scenarios

### Scenario 1: Tavily API Down
```
main.py → RESEARCH.research(text)
  → SearchToolProvider.search()
    → TavilySearchProvider.search()
      → Exception caught
      → SearchToolProvider returns []
      → researcher.py returns fallback ResearchResult
      → main.py logs warning, continues
      → Gemini responds without research context
Result: No crash, graceful degradation
```

### Scenario 2: Malformed Query
```
SearchTool._validate() rejects empty/truncated queries
Returns SearchResponse(status="error")
SearchToolProvider.search() returns []
researcher.py returns fallback ResearchResult
main.py continues
Result: No crash
```

### Scenario 3: Too Many Results
```
SearchResult._normalise() clips content to 4000 chars
Researcher._build_context() formats all sources
If context is very long, Gemini's max_output_tokens handles truncation
Result: Model receives valid context, response may be limited in length
```

---

## Logging

Research phases are logged for debugging:

```
INFO Research phase: gathering information for query: What are the latest AI trends?
INFO Research completed: 5 sources, confidence=high
DEBUG SearchTool: Tavily provider enabled.
INFO Search started: latest AI trends
INFO Search completed: 5 results
```

Errors are logged:
```
WARNING Research failed; proceeding without context: <exception>
ERROR ResearchAgent: search timed out for query: ...
ERROR SearchTool: provider timed out for query: ...
```

---

## Next Steps: Frontend Integration

The backend now produces:
1. **Long display response** (up to 8192 tokens for INFORMATION_QUERY)
2. **Short voice summary** (extracted by narrator if > 60 words)
3. **Sources list** (available in research context)

The frontend should:
1. Display the full response (already done)
2. Display sources as citations (show title + URL)
3. Play the voice summary (already done for voice_response)
4. Optionally collapse long answers with "Read more"

---

## Checklist

✅ **researcher.py**: SearchToolProvider adapter added, handles search failures  
✅ **config.py**: TAVILY_API_KEY configuration added  
✅ **factory.py**: SearchTool and ResearchAgent builders added  
✅ **main.py**: Research phase integrated before LLM call  
✅ **.env.example**: TAVILY_API_KEY documented  
✅ **No breaking changes**: CHAT/BUILD/other intents unaffected  
✅ **Graceful fallback**: Works without Tavily API key  
✅ **Error handling**: Research failures don't crash pipeline  
✅ **Logging**: Research progress tracked for debugging  

---

## Architecture Preserved

- ✅ Personality system unchanged (emotion extraction still works)
- ✅ Intent detection unchanged (INFORMATION_QUERY detection works as-is)
- ✅ Router unchanged (INFORMATION_QUERY routing to conversational pipeline)
- ✅ LLM provider interface unchanged (Gemini gets messages + system prompt)
- ✅ Voice delivery unchanged (voice_response extraction still works)
- ✅ Session history unchanged (messages array preserved)
- ✅ Agent subsystem unaffected (BUILD/EDIT flows untouched)

---

## Summary

**Before integration:**
- INFORMATION_QUERY was detected but had no research context
- Gemini responded from training data alone (potentially outdated)
- User got generic knowledge response

**After integration:**
- INFORMATION_QUERY triggers research phase
- SearchTool (Tavily) retrieves live information
- Gemini responds with grounding from real sources
- Frontend can display sources as citations
- Pipeline gracefully handles missing credentials / API failures

**Impact:**
- User asks "What are the latest AI trends?"
- Backend searches for current information
- Gemini synthesizes a detailed, well-sourced response
- User hears a short voice summary
- Complete end-to-end knowledge retrieval pipeline

✨ **EDEN now has live information retrieval.** ✨

