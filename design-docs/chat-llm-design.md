# Chat & LLM Vision Analysis - MVP Design Document

## Background

This service is the LLM-powered intelligence layer of the traffic camera system. It receives natural language queries from users, determines which cameras are relevant, fetches their latest snapshots from `gov-data` (Java backend), and uses OpenAI Vision to analyze the images and return a human-readable assessment.

For overall system context, see `gov-data` → `docs/traffic-image-design-doc.md`.

---

## 1. Architecture

```
civic-frontend (Next.js)
    ↓ POST /api/chat
civic-app (Python LLM service)  ← this project
    ↓ GET /api/cameras/...
gov-data (Java backend, PostgreSQL)
```

---

## 2. API Endpoint

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Natural language query → LLM-powered response (body: `{ "message": "Is CTE jammed?" }`) |

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

## 3. Query Flow

```
User query ("Is CTE jammed?")
  → LLM resolves intent + cameras + view_type
  → Fetch latest snapshots from gov-data API
  → Send images to OpenAI Vision
  → LLM synthesizes response
  → Return text + view_type + camera data to frontend
  → Frontend renders the appropriate right-panel component based on view_type
```

---

## 4. Vision Analysis Prompt

```
You are a Singapore traffic analyst. Analyze this traffic camera image.

Camera: {camera_id} — {location_name}
Expressway: {expressway_code}
Time: {timestamp}

Provide a structured assessment:
1. Congestion: free_flow | light | moderate | heavy | standstill
2. Vehicle density: empty | sparse | normal | dense | packed
3. Incidents: Any visible accident, breakdown, or obstruction? Describe if yes.
4. Weather: clear | rain | heavy_rain | fog
5. Road surface: dry | wet | flooded | construction
6. Summary: One sentence describing what you see.

Respond in JSON format.
```

---

## 5. Supported Query Types

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

## 6. Cost Estimate

Vision analysis is **on-demand only** — triggered by user queries, not background jobs.

| | Per call | Per day (~500 queries, avg 5 cameras) |
|--|:--------:|:-------------------------------------:|
| Input tokens | ~1,500 (image + prompt) | ~3.75M |
| Output tokens | ~300 (JSON response) | ~750K |
| Cost (Haiku) | ~$0.002 | **~$5** |

---

## 7. Dependencies

- **gov-data API** — provides camera data and latest snapshots (see `gov-data` → `docs/traffic-image-design-doc.md` Section 5)
  - `GET /api/cameras` — list all cameras with latest snapshot
  - `GET /api/cameras/{id}` — single camera detail + latest image
  - `GET /api/cameras/expressway/{code}` — cameras by expressway
  - `GET /api/cameras/nearby?lat=&lng=&radius=` — cameras by location
  - `GET /api/cameras/search?q=` — cameras by name
- **Claude API** — LLM vision analysis (Haiku for cost efficiency)
- **civic-frontend** — consumes this service's `/api/chat` endpoint and renders the appropriate view based on `view_type` (see `civic-frontend` → `docs/traffic-camera-ui-design.md`)
