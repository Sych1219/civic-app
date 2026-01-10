# Project Structure (Easy Version)

This doc explains how we organize the code so we can add many “agents” later without making a mess.

## 1. Quick Definitions
- **Agent**: a “worker” that can finish a whole job by itself (end-to-end).
  - Example job: “Take API docs text and create a correct registration.”
- **Graph**: a “manager” that decides which agent to run and in what order.
  - Example: “If registration fails because it already exists, run the conflict agent.”
  - A “conflict agent” (like `ConflictResolutionAgent`) helps when there is a clash, like a duplicate (“already exists” / `409`). It compares the old vs new registration and suggests “use existing”, “update”, or “merge”, then asks for approval.
- **Contract**: the saved “API calling recipe” (a JSON shape) that tells us how to call an API.
  - Example fields: `baseUrl`, `httpMethod`, `headers`, `queryParams`.
- **State**: the “shared backpack” of data passed around while work is happening.
  - Example: `source_text`, `contract`, `validation_errors`.

## 2. Simple Rules
- **One contract shape**: define the contract in one place (`app/shared/models.py`) so all agents agree.
- **Agents do full jobs**: an agent can do many steps inside, but it owns one big capability.
- **Reuse common parts**: put shared helpers in `app/components/` and `app/shared/` so we don’t repeat the same code in many agents (fix once, everyone benefits).
- **Graphs only coordinate**: graphs should mostly connect agents and handle “if/else” decisions.

## 3. What Agents We Expect
- `RegisterAgent`: makes an API registration from docs text; can submit it if allowed.
- `ApiCatalogAgent`: finds/list available APIs so other agents can choose one to get the data they need.
- `ConflictResolutionAgent`: handles duplicates (like “already exists”) by proposing changes/merges for approval.

## 4. What Graphs Do
- `registration_graph`: runs `RegisterAgent`, stops for review, or submits when approved.
- `catalog_graph`: runs `ApiCatalogAgent` to produce a clean list of APIs.
- `router_graph` (optional): looks at the user request and chooses which graph/agent to run.

## 5. Repository Layout (target)
```
app/
  agents/
    register_agent.py
    api_catalog_agent.py
    conflict_resolution_agent.py
  graphs/
    registration.py       # orchestrates agents into a graph factory
    conflict_resolution.py
    catalog.py
    router.py
  components/
    normalize.py
    chunk.py
    draft.py
    validate.py
    register.py
    audit.py
  shared/
    state.py              # shared state data keys
    models.py             # contract “shape” (schema) + validation
    prompts.py            # shared prompt text
    clients.py            # shared HTTP clients
    text.py               # shared text helpers
  tests/
    agents/...            # tests for each agent
    components/...        # tests for shared helpers
    graphs/...            # tests for full graphs
design_docs/
  repo-structure.md       # this doc
  web-page-to-request.md
```

## 6. How “One Contract Shape” Helps (example)
If the contract shape lives in `app/shared/models.py`, then:
- `RegisterAgent` can create a contract and validate it.
- `ApiCatalogAgent` can return a list of contracts using the same shape.
- Any other agent can read `contract["baseUrl"]` and trust it exists and is formatted the same way.

## 7. Example Flow (Registration)
1. User pastes API docs text.
2. `registration_graph` runs `RegisterAgent`.
3. `RegisterAgent` uses helpers in `app/components/` to do things like clean text, draft JSON, and validate it.
4. If there are errors, the graph stops and shows them.
5. If it looks good and the user approves, the agent submits it using a client from `app/shared/clients.py`.

## 8. Adding a New Agent Later
1. Create a new file in `app/agents/` (example: `data_fetch_agent.py`).
2. Reuse shared helpers from `app/components/` and `app/shared/`.
3. Wire it into a graph in `app/graphs/` (or add it to `router.py`).
