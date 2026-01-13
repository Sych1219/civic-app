# Router Graph (`app/graphs/router.py`)

Short note on how the router graph decides between registering a new API vs invoking an existing one, and how it prepares the inputs for each path.

## Goal
- Read the user chat (`state["source_text"]`) and choose the right path.
- If intent is registration, run `RegisterAgent` and finish.
- If intent is invocation, search the catalog, pick the best API, and trigger it with minimal required payload.

## Inputs and Outputs (state keys)
- Inputs: `source_text`, `metadata.intent` (optional), `metadata.catalog_query` (optional), `metadata.trigger` (optional).
- Outputs (invoke path): `catalog_response`, `metadata.trigger.api_id`, `trigger_request`, `trigger_response`, `trigger_summary`.
- Outputs (register path): whatever `RegisterAgent` writes (e.g., `registry_response`, `validation_errors`).

## Flow (nodes and edges)
1. **route** (entry): calls `_choose_path` to pick `register` or `invoke`.
2. **register** path: `register_agent` → `END`.
3. **invoke** path:
   - `prepare_catalog_query`: ensure a broad query exists; defaults to `{"page": 0, "size": 100}` when missing.
   - `api_catalog_agent`: calls registry `list_apis`.
   - `prepare_trigger_input`: choose an `api_id` and ensure a minimal trigger payload.
   - `api_trigger_agent`: POST trigger call.
   - `trigger_summary_agent`: summarize the trigger result → `END`.

## Routing decision (`_choose_path`)
- Uses `metadata.intent` if already present; otherwise calls `ChatOpenAI` (default `gpt-4o-mini`, `temperature=0`) with a REGISTER vs INVOKE classifier prompt.
- Writes back `metadata.intent` for downstream visibility.
- On any error or unclear output, defaults to `invoke` to avoid blocking users who just want data.

## Preparing the catalog query (`_prepare_catalog_query`)
- Reads `metadata.catalog_query`; if empty, injects a broad pagination query to let the LLM rank candidates later.
- Returns `{"metadata": updated_metadata}` so only metadata is mutated.

## Selecting and preparing trigger inputs (`_prepare_trigger_input`)
- If `metadata.trigger.api_id`/`apiId` is missing, flatten `state.catalog_response` via `_extract_candidates` (looks for `content/items/results/data/apis` or a singleton) and keep id/name/description/method/baseUrl.
- `_select_best_candidate` uses an LLM to rank candidates against `source_text`; if the model returns an index, it maps it; otherwise looks for an id substring. Falls back to the first candidate or `None` when empty.
- If no payload is provided under `metadata.trigger`, injects `request: {"useExampleDefaults": True}` so triggers run with example defaults instead of failing for missing inputs.

## Error and safety considerations
- LLM calls are wrapped in `try/except`; routing falls back to invoke, candidate selection falls back to the first option.
- Agents themselves add to `validation_errors` on validation/IO issues (`ApiCatalogAgent`, `ApiTriggerAgent`).
- Trigger agent supports `dry_run` via `GraphConfig`; router passes through config untouched.

## Extensibility
- Constructor allows injecting custom agents or LLMs for testing or alternative behaviors.
- Additional paths can be added by extending `_choose_path` labels and wiring new nodes/edges in `compile()`.

## How to run
- `create_router_graph()` returns the compiled LangGraph object. Invoke it with a `GovApiState` dict; start state typically includes `source_text` and optional `metadata` for intent/catalog/trigger overrides.
