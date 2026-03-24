# Chat & LLM Vision Analysis - MVP Design Document

## Background

This service is the LLM-powered intelligence layer of the traffic camera system. It receives natural language queries from users, determines which cameras are relevant, fetches their latest snapshots from `gov-data` (Java backend), and uses OpenAI Vision to analyze the images and return a human-readable assessment.

For overall system context, see `gov-data` → `docs/traffic-image-design-doc.md`.

---

## 1. Architecture

```
civic-frontend (Next.js)
    ↓ POST /api/traffic-chat
civic-app (Python LLM service)  ← this project
    ↓ GET /api/cameras/...
gov-data (Java backend, PostgreSQL)
```

---

## 2. API Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/traffic-chat` | Natural language query → LLM-powered response (body: `{ "message": "Is CTE jammed?" }`) |

### Request

```json
{
  "message": "Is CTE jammed?"
}
```

### Response

The response includes a `view_type` field that tells the frontend which right-panel component to render (see `civic-frontend` → `docs/traffic-camera-ui-design.md` Section 11 for view routing).

```json
{
  "answer": "CTE is experiencing heavy congestion from Braddell to AMK. Consider taking PIE instead.",
  "view_type": "corridor",
  "cameras": [
    {
      "camera_id": "1701",
      "location_name": "CTE - Ang Mo Kio",
      "image_url": "https://...",
      "analysis": {
        "congestion": "heavy",
        "vehicle_density": "packed",
        "incidents": "None visible",
        "weather": "clear",
        "road_surface": "dry",
        "summary": "Heavy bumper-to-bumper traffic in both directions."
      }
    }
  ]
}
```

### `view_type` Values

| `view_type` | Frontend Component | When to Return |
|---|---|---|
| `camera_map` | CameraMap | "Show all cameras", "Which cameras are online?" |
| `corridor` | CorridorMap | "Is CTE jammed?", "BKE cameras" |
| `camera_detail` | CameraDetail | "Show camera 1005", specific camera queries |
| `replay` | ReplayPlayer | "Show Woodlands at 8am" |
| `alerts` | AlertsPanel | "Any incidents right now?" |

---

## 3. LangChain Agent Design

### Two-Phase Architecture

The agent uses a two-phase design to separate cheap text reasoning from expensive vision analysis.

```
User: "Is CTE jammed?"
        │
   ┌────▼──────────────────────────┐
   │  Phase 1: Route & Fetch       │  ← Text-only LLM with tool-calling
   │  - classify view_type         │     (gpt-4o-mini, no vision needed)
   │  - pick gov-data API endpoint │
   │  - call tool to fetch cameras │
   └────┬──────────────────────────┘
        │ cameras + image URLs
   ┌────▼──────────────────────────┐
   │  Phase 2: Vision & Synthesize │  ← Multimodal LLM call
   │  - send images to OpenAI     │     (gpt-4o-mini with vision)
   │    Vision in parallel         │
   │  - per-camera structured      │
   │    analysis (JSON)            │
   │  - synthesize corridor-level  │
   │    summary across all cameras │
   └────┬──────────────────────────┘
        │
   { answer, view_type, cameras[] }
```

### Why Two Phases

- **Cost** — Phase 1 is text-only (cheap). Only Phase 2 uses vision tokens (expensive). If the user says "Show all cameras" (`camera_map`), Phase 2 is skipped entirely — no vision needed, just return the camera list.
- **Latency** — Phase 2 vision calls are parallelized across cameras with `asyncio.gather`, bringing corridor analysis (e.g., 9 CTE cameras) from ~9× latency down to ~1×.
- **Reliability** — A single agent loop that tries to fetch → analyze → synthesize risks confused tool-calling. Splitting makes each phase deterministic.

### Phase 1 — Intent Classification + Data Fetch

Uses `ChatOpenAI(model="gpt-4o-mini", temperature=0)` with bound tools:

| Tool | What It Does | Gov-data Endpoint |
|------|-------------|-------------------|
| `fetch_all_cameras` | List all cameras with latest snapshot | `GET /api/cameras` |
| `fetch_camera_detail` | Single camera by ID | `GET /api/cameras/{id}` |
| `fetch_expressway` | All cameras along a corridor | `GET /api/cameras/expressway/{code}` |
| `fetch_nearby` | Cameras near a GPS point | `GET /api/cameras/nearby?lat=&lng=&radius=` |
| `search_cameras` | Search by location name | `GET /api/cameras/search?q=` |
| `geocode_place` | Resolve place name → lat/lng (reused from taxi agent) | OneMap Singapore API |

The system prompt instructs the LLM to also return a `view_type` classification alongside the tool call. Enforced via `with_structured_output`.

### Phase 2 — Vision Analysis + Synthesis

**Not an agent** — this is a deterministic chain with no tool-calling:

1. For each camera, build a multimodal message containing the image URL + the vision prompt (Section 4)
2. Fan out all camera analyses in parallel via `asyncio.gather`
3. Parse structured JSON output per camera (congestion, vehicle_density, etc.)
4. Run one final LLM call to **synthesize** a corridor-level summary from all per-camera analyses (e.g., "CTE is clear from Ang Mo Kio to Braddell, congested near Moulmein exit")

### When to Skip Phase 2

| `view_type` | Needs Vision? | Reason |
|---|---|---|
| `camera_map` | No | Just display camera markers on map |
| `corridor` | Yes | Need congestion analysis per camera |
| `camera_detail` | Yes | Single camera deep analysis |
| `replay` | Yes | Analyze historical frames |
| `alerts` | Yes | Scan all cameras for incidents |

### Relationship to Existing Taxi Agent

This camera agent is **separate** from the taxi OpenAPI planner in `agent.py` — different LLM config, different tools, different response models. Shared infrastructure:

- `geocode_place` tool (reused from `tools.py`)
- FastAPI app, CORS config, health check (in `main.py`)
- Docker and environment setup

> **Note:** `langgraph` is already in `requirements.txt` but not needed for MVP. The two-phase approach is simple enough with plain LangChain + async. LangGraph becomes worthwhile if we add loops (e.g., agent realizes it needs more cameras and re-fetches).

---

## 4. Query Flow

```
User query ("Is CTE jammed?")
  → Phase 1: LLM classifies intent → view_type="corridor", tool=fetch_expressway("CTE")
  → Phase 1: Tool fetches 9 CTE cameras from gov-data API
  → Phase 2: 9 camera images sent to OpenAI Vision in parallel
  → Phase 2: Per-camera JSON analysis returned
  → Phase 2: LLM synthesizes corridor summary across all 9 analyses
  → Return { answer, view_type, cameras[] } to frontend
  → Frontend renders CorridorMap component based on view_type
```

---

## 5. Vision Analysis Prompt (used in Phase 2)

```
You are a Singapore traffic analyst. Analyze this traffic camera image.

Camera: {camera_id} — {location_name}
Expressway: {expressway_code}
Time: {timestamp}

Provide a structured assessment:
1. Congestion: free_flow | light | moderate | heavy | standstill
2. Vehicle density: empty | sparse | normal | dense | packed
3. Incidents: none | accident | breakdown | obstruction | roadworks
4. Weather: clear | rain | heavy_rain | fog
5. Road surface: dry | wet | flooded | construction
6. Summary: One sentence describing what you see.

Respond in JSON format.
```

---

## 6. `analysis` Object Definition

Each camera in the response `cameras[]` array includes an `analysis` object produced by Phase 2 vision analysis.

| Field | Type | Allowed Values | Description |
|---|---|---|---|
| `congestion` | `string` | `free_flow` \| `light` \| `moderate` \| `heavy` \| `standstill` | Overall traffic flow level on the road segment visible in the image |
| `vehicle_density` | `string` | `empty` \| `sparse` \| `normal` \| `dense` \| `packed` | How tightly vehicles are packed in the frame |
| `incidents` | `string` | `none` \| `accident` \| `breakdown` \| `obstruction` \| `roadworks` | Most severe incident type visible in the frame; `none` if nothing detected |
| `weather` | `string` | `clear` \| `rain` \| `heavy_rain` \| `fog` | Ambient weather conditions inferred from the image |
| `road_surface` | `string` | `dry` \| `wet` \| `flooded` \| `construction` | Visible road surface condition |
| `summary` | `string` | Free text (one sentence) | Human-readable sentence describing what the LLM sees in the image |

### Notes

- All fields are **required** — the Phase 2 vision prompt enforces structured JSON output with all six fields.
- If the LLM cannot determine a field (e.g., road surface is not visible), it should default to the most conservative value (e.g., `"dry"` for road surface, `"none"` for incidents).
- `summary` is used directly in the frontend camera card tooltip and should be concise (≤ 20 words).

---

## 7. Supported Query Types

| User Says | Behavior | `view_type` |
|-----------|----------|-------------|
| "Show all cameras" | Return all cameras with status | `camera_map` |
| "Show me Woodlands" | Search cameras near Woodlands, return images | `camera_map` |
| "BKE cameras" | Fetch all BKE corridor cameras → corridor analysis | `corridor` |
| "Is CTE jammed?" | Fetch CTE cameras → LLM vision analysis → corridor summary | `corridor` |
| "Show camera 1005" | Single camera detail + LLM analysis | `camera_detail` |
| "Cameras near me" | Find nearest cameras by lat/lng | `camera_map` |
| "Show Woodlands at 8am" | Historical replay with LLM narration | `replay` |
| "Any accidents right now?" | Fetch all cameras → LLM scans for incidents | `alerts` |

---

## 8. Cost Estimate

Vision analysis is **on-demand only** — triggered by user queries, not background jobs.

| | Per call | Per day (~500 queries, avg 5 cameras) |
|--|:--------:|:-------------------------------------:|
| Input tokens | ~1,500 (image + prompt) | ~3.75M |
| Output tokens | ~300 (JSON response) | ~750K |
| Cost (Haiku) | ~$0.002 | **~$5** |

---

## 9. Dependencies

- **gov-data API** — provides camera data and latest snapshots (see `gov-data` → `docs/traffic-image-design-doc.md` Section 5)
  - `GET /api/cameras` — list all cameras with latest snapshot
  - `GET /api/cameras/{id}` — single camera detail + latest image
  - `GET /api/cameras/expressway/{code}` — cameras by expressway
  - `GET /api/cameras/nearby?lat=&lng=&radius=` — cameras by location
  - `GET /api/cameras/search?q=` — cameras by name
- **Claude API** — LLM vision analysis (Haiku for cost efficiency)
- **civic-frontend** — consumes this service's `/api/traffic-chat` endpoint and renders the appropriate view based on `view_type` (see `civic-frontend` → `docs/traffic-camera-ui-design.md`)
