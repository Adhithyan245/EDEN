# Quick Reference: Research Agent Integration

## What Changed?

EDEN now has a **working live knowledge pipeline**. When a user asks a question with research keywords ("latest", "trends", "news", etc.), EDEN retrieves current information from Tavily before responding.

---

## Files Modified

| File | What | Why |
|------|------|-----|
| `researcher.py` | Added `SearchToolProvider` adapter | Connects research agent to search tool |
| `config.py` | Added `tavily_api_key` + `has_tavily` | Configuration support for search API |
| `factory.py` | Added `build_search_tool()` + `build_research_agent()` | Dependency injection builders |
| `main.py` | Added research phase before LLM call | Retrieves context for INFORMATION_QUERY |
| `.env.example` | Added `TAVILY_API_KEY` documentation | Documents new optional credential |

---

## How It Works

### For User: Ask a Research Question
```
User: "What are the latest AI trends?"
  ↓
[EDEN detects INFORMATION_QUERY intent]
  ↓
[EDEN searches Tavily for current info]
  ↓
[Research context injected into prompt]
  ↓
[Gemini generates response with sources]
  ↓
[Frontend displays long answer + voice summary]
```

### For Developer: The Pipeline
```python
# Startup
RESEARCH = factory.build_research_agent()  # Creates with SearchTool + Tavily

# On each INFORMATION_QUERY
research_result = await RESEARCH.research(user_query)
  # → calls SearchToolProvider
  #   → calls SearchTool.search()
  #     → calls TavilySearchProvider
  #       → retrieves up to 5 sources
  # → formats as "[Source 1] ... [Source 2] ..."
  # → returns ResearchResult with sources + context + confidence

# Inject into messages
enriched_message = f"{query}\n\n[Research context:\n{context}]"
response = await LLM.stream_reply(messages_with_context, ...)
```

---

## Configuration

### No Search (Development)
```bash
# .env
GEMINI_API_KEY=<key>
# TAVILY_API_KEY not set
```
→ INFORMATION_QUERY works without research context

### With Search (Production)
```bash
# .env
GEMINI_API_KEY=<key>
TAVILY_API_KEY=<key>  # From https://tavily.com
```
→ INFORMATION_QUERY retrieves live data

---

## Key Classes

### `SearchToolProvider` (researcher.py)
Adapter that converts SearchTool results to researcher's Source format.

```python
# Usage in factory
provider = SearchToolProvider(search_tool)
researcher = ResearchAgent(search_provider=provider)
```

### `ResearchAgent.research()` (researcher.py)
Main method that orchestrates research.

```python
# Call during INFORMATION_QUERY
result = await researcher.research("What are the latest trends?")
# → result.context contains formatted sources
# → result.confidence is "high" | "medium" | "low"
# → result.sources is list of Source objects
```

### `SearchTool` (search.py)
Already exists; no changes. Used by SearchToolProvider.

---

## Error Handling

### Scenario 1: No Tavily Key
```
build_research_agent()
  → build_search_tool()
    → TAVILY_API_KEY not set
    → returns SearchTool(provider=None)  # graceful no-op
  → ResearchAgent continues
  → INFORMATION_QUERY proceeds without context
```

### Scenario 2: Tavily API Fails
```
RESEARCH.research(query)
  → SearchToolProvider.search()
    → Tavily request fails
    → returns []  # empty list
  → researcher returns status="no_results"
  → main.py logs warning, continues without context
```

### Scenario 3: Query Too Long
```
SearchTool validates query length
  → if > 500 chars, truncates
  → proceeds with truncated query
```

---

## Testing

### Test 1: Chat (No Research)
```bash
User: "Hello EDEN"
Expected: Normal short response, no research
```

### Test 2: Research with Key
```bash
export TAVILY_API_KEY="<key>"
User: "Latest AI news"
Expected: Long response with sources
Logs: "Research phase: gathering..." → "Research completed: X sources"
```

### Test 3: Research without Key
```bash
unset TAVILY_API_KEY
User: "Latest AI news"
Expected: Response without research context
Logs: "Research yielded no results; proceeding without context"
```

### Test 4: Build (Not Affected)
```bash
export EDEN_AGENT_ENABLED=true
User: "Create a todo app"
Expected: Normal build flow, no research
```

---

## Logs to Expect

### Startup
```
SearchTool -> TavilySearchProvider        # if TAVILY_API_KEY set
SearchTool -> (no provider)               # if TAVILY_API_KEY not set
ResearchAgent initialized with SearchToolProvider
```

### On INFORMATION_QUERY
```
Research phase: gathering information for query: What are the latest AI trends?
Search started: latest AI trends          # SearchTool log
Search completed: 5 results               # SearchTool log
Research completed: 5 sources, confidence=high
```

### On Failure
```
Research failed; proceeding without context: <error>
```

---

## Frontend Integration (Next Steps)

The backend now produces:
1. **Long response** (up to 8192 tokens)
2. **Voice summary** (short version, if > 60 words)
3. **Sources** (in research context)

Frontend should display:
- Full response ✓ (already works)
- Voice summary ✓ (already works)
- **NEW:** Sources as citations (show title + URL)

To extract sources from research context:
```javascript
// Research context format:
// "[Source 1] Title (url)\nContent\n\n---\n\n[Source 2] Title (url)\nContent..."

const sourceRegex = /\[Source \d+\] ([^\(]+)\s*\(([^\)]+)\)/g;
const sources = [];
let match;
while ((match = sourceRegex.exec(context)) !== null) {
  sources.push({ title: match[1].trim(), url: match[2].trim() });
}
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────┐
│ main.py - Message Handler                   │
├─────────────────────────────────────────────┤
│ 1. Detect intent (intent.py)                │
│ 2. Route (router.py) → CONVERSATION         │
│ 3. ➜ IF INFORMATION_QUERY:                  │
│      3a. research_result = await            │
│          RESEARCH.research(query)           │
│      3b. Inject context into messages       │
│ 4. Call LLM.stream_reply(enriched_messages) │
│ 5. Parse response (personality)             │
│ 6. Split voice/display                      │
│ 7. Send to frontend                         │
└─────────────────────────────────────────────┘
                    ↓
         ┌──────────────────────┐
         │ ResearchAgent        │
         │ (researcher.py)      │
         ├──────────────────────┤
         │ 1. Analyze query     │
         │ 2. Search (provider) │
         │ 3. Build context     │
         │ 4. Assess confidence │
         └──────────────────────┘
                    ↓
      ┌─────────────────────────────┐
      │ SearchToolProvider          │
      │ (researcher.py - adapter)   │
      ├─────────────────────────────┤
      │ 1. Call SearchTool.search() │
      │ 2. Convert results          │
      │ 3. Return Sources           │
      └─────────────────────────────┘
                    ↓
         ┌──────────────────────┐
         │ SearchTool           │
         │ (search.py)          │
         ├──────────────────────┤
         │ Validate query       │
         │ Call provider        │
         │ Normalize results    │
         │ Handle errors        │
         └──────────────────────┘
                    ↓
      ┌─────────────────────────────┐
      │ TavilySearchProvider        │
      │ (search.py - if key set)    │
      ├─────────────────────────────┤
      │ Call Tavily API             │
      │ Return SearchResults        │
      └─────────────────────────────┘
```

---

## One-Liner Summaries

- **SearchToolProvider:** Adapter that makes SearchTool work with ResearchAgent
- **ResearchAgent:** Orchestrator that analyzes queries, retrieves sources, builds context
- **SearchTool:** Unified search interface; calls Tavily if key is set
- **TavilySearchProvider:** Actual API call to Tavily
- **main.py integration:** Injects research context into LLM prompt for INFORMATION_QUERY

---

## Checklist: Everything Working?

- [ ] Backend starts without errors
- [ ] `/health` endpoint returns `"ok"`
- [ ] CHAT messages work normally (no research)
- [ ] INFORMATION_QUERY detected (check logs)
- [ ] With TAVILY_API_KEY set: research logs appear
- [ ] Without TAVILY_API_KEY: graceful fallback
- [ ] Response includes researched information (if key set)
- [ ] No crashes on research failures
- [ ] BUILD requests unaffected (if EDEN_AGENT_ENABLED=true)

---

## Next Phase

**Phase 2: Frontend Integration**
- Display sources as citations
- Show confidence level
- Optionally collapse long responses
- Display "powered by Tavily" attribution

See `INTEGRATION_SUMMARY.md` for full details.

