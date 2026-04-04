# RAG System — Current State and Future

## Current usage

RAG is integrated into **CoreAgent** (old agent) prompt pipeline:

1. `CoreAgent.__init__()` creates `RagModel()` from `src/agent/rag.py`
2. Uses FAISS vector store + OpenAI embeddings (via LM Studio API)
3. On each prompt: takes last 2-3 chat events → `rag_model.explain(events)` → vocabulary context
4. Result added to prompt as `"Some vocabulary explanation:\n{rag_context}"`

Primary data source: `resources/Documents/knowledge/NetTyanSlang2026.txt` — Russian slang dictionary.

**NOT used in ChatAgent** — only in CoreAgent which is deprecated.

## Assessment

RAG for slang vocabulary is overkill:
- Slang file is ~500 tokens — fits directly in prompt
- Embedding search adds latency for no benefit
- Modern LLMs (Qwen 3.5, etc.) already know most slang from training

## Where RAG/DB actually needed

| Use case | Solution | RAG? |
|---|---|---|
| Slang/vocabulary | Direct prompt injection from knowledge file | No |
| User memory (facts about players) | `save_user_info` tool → DB (already exists) | No |
| Long dialogue history (>25k context) | Summarization + DB storage | No |
| Chat filter (is this offensive?) | Classifier model, not retrieval | No |
| Knowledge about game mechanics | Static prompt section or knowledge file | No |
| Searching old conversations | Embedding search over session logs | Maybe |

## Conclusion

RAG can be removed from active pipeline. User memory through DB tools is sufficient.
If needed later (e.g., searching past conversations for DIALOGUE agent),
can be re-added as a tool (`search_memory`) rather than automatic prompt injection.
