# Taxi Spatial Q&A — Singapore MVP

A **LLM + tool-call** service that answers natural-language questions about real-time Singapore
taxi distribution. It receives a user query, uses a LangChain agent (GPT-4o-mini) to select and
invoke the right spatial query tool against PostGIS, and returns a natural-language answer.

> **This service is the LLM layer only.** Taxi data is ingested from data.gov.sg every 30 seconds
> by a separate **Java service** that writes to the shared PostGIS database.

## What it does

Answers spatial questions about available taxis in Singapore using live LTA data
updated every 30 seconds. Example queries:

- *"How many taxis are within 3 km of Changi Airport?"*
- *"Nearest 5 taxis to 1.3521, 103.8198"*
- *"How many taxis are in Tampines right now?"*

See [`design-docs/MVP-taxi-spatial-qa.md`](design-docs/MVP-taxi-spatial-qa.md) for full design details.

## Prerequisites

- Docker & Docker Compose
- OpenAI API key (GPT-4o-mini)
- Java ingestion service running and connected to the same PostgreSQL instance

## Setup

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, LTA_API_KEY, and DB_PASSWORD in .env
docker compose up
```

## Usage

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How many taxis are within 3km of Changi Airport?"}'
```

Other endpoints:

| Method | Path                      | Description              |
| ------ | ------------------------- | ------------------------ |
| GET    | `/api/v1/snapshot/latest` | Latest snapshot metadata |
| GET    | `/api/v1/health`          | Health check             |

## Data folder structure

```
data/
├── memory/
│   ├── MEMORY.md                   # Agent memory index
│   └── experience/                 # Accumulated experience entries
├── officers/                       # Officer profile data
└── sessions/
    ├── default.json                # Default session state
    ├── test.json                   # Test session state
    ├── archive/                    # Archived session records
    └── artifacts/
        ├── default/                # Artifacts for default session (JSON files per interaction)
        └── test/                   # Artifacts for test session (JSON files per interaction)
```
