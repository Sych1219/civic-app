## Gov API Registration LangGraph

This project turns government API documentation text (pasted from web pages, blogs, or PDFs) into structured registrations for the `POST /api/v1/gov/apis` endpoint using LangGraph and LangSmith.

### Setup

1. Create a virtualenv and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Export credentials for OpenAI and LangSmith (update values as needed):
   ```bash
   export OPENAI_API_KEY=sk-...
   export LANGCHAIN_TRACING_V2=true
   export LANGCHAIN_API_KEY=ls-...
   export LANGCHAIN_PROJECT=civic-app
   ```

### Usage

```python
from app import create_gov_api_graph

graph = create_gov_api_graph()
result = graph.invoke(
    {
        "source_text": \"\"\"
        GET https://developer.nrel.gov/api/alt-fuel-stations/v1.json

        Query parameters:
          - api_key (required)
          - state (optional)
          - limit (optional, default 50)

        Headers:
          Accept: application/json
        \"\"\",
        "auto_register": False,  # review before submitting
    },
    config={
        "run_name": "Gov API Draft",
        "dry_run": True,
    },
)
print(result["contract"])
```

Key steps handled by the graph:

1. Normalize the pasted API-related text.
2. Split content into context chunks.
3. Prompt GPT-4o via LangChain/LangGraph with guardrails + schema derived from `GovApiContract`.
4. Validate the JSON payload before optionally submitting it through `GovApiRegistryClient`.
5. When `auto_register=True`, the payload is POSTed to `http://localhost:8080/api/v1/gov/apis`; otherwise the workflow stops after validation so an operator can review/edit.

LangSmith captures traces for each node (`gov.normalize_text`, `gov.chunk_context`, etc.) to simplify debugging and prompt tuning. Set `config={"dry_run": True}` or `auto_register=False` to avoid calling the registry endpoint while iterating locally.
