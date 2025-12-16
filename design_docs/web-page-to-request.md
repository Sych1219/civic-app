# Web Page ➜ Gov API Registration Design

## 1. Problem & Context
Internal operations teams currently discover external government APIs by browsing public docs. Translating those docs into a structured registration (name, base URL, method, headers, parameters) is manual, slow, and inconsistent. We want a chat workflow where the user drops a URL to the API documentation. The system fetches and distills that page, feeds it to an LLM, and the LLM drafts the payload required by our `POST /api/v1/gov/apis` endpoint. The operator can review/edit, then submit to persist the contract for downstream ingestion jobs.

## 2. Goals / Non-goals
- Capture full invocation contract (URL, method, headers, query, body schemas, description) for any gov public API.
- Make registration repeatable: LLM suggestions + validation rules enforce required fields and HTTPS base URLs.
- Allow easy hand-off to downstream jobs that rely on this metadata.
- Non-goal: actually calling the external APIs or verifying credentials; this feature ends at registration.

## 3. High-level Flow
1. **User Input** – operator pastes a documentation URL into chat.
2. **Document Fetcher** – backend loads and normalizes HTML, strips scripts/noise, converts to text chunks (Readability or similar).
3. **Context Builder** – summarize/cluster chunks, extract sections like endpoint table, sample request/response, auth requirements.
4. **LLM Orchestrator** – prompt template injects:
   - Canonical contract schema (see §6)
   - Extracted doc text (truncated to fit window)
   - Guardrails (HTTPS, allowed HTTP verbs, header rules)
5. **LLM Output Parser** – JSON schema validator ensures generated payload conforms.
6. **Review UI** – show draft payload allowing manual edits.
7. **Registry Client** – submit payload to `POST /api/v1/gov/apis` (dev: `http://localhost:8080/api/v1/gov/apis`, prod host TBD but same path).
8. **Confirmation** – display success info or validation/conflict errors for operator to resolve.

## 4. Components
- **Fetcher Service**: resilient HTTP client with retry, user-agent rotation, HTML→Markdown converter (e.g., `readability-lxml`). Enforces max download size and fallback to PDF/JSON scraping if needed.
- **Text Chunker**: splits cleaned text into ~2k token segments, tags metadata (heading path, code block vs prose).
- **LLM Prompt Engine**: 
  - Base system prompt describing role: “You convert API documentation into registration payloads.”
  - Few-shot examples covering GET/POST, nested filters, headers.
  - JSON schema + instructions to respond with strict JSON.
- **Schema Validator**: uses `jsonschema` to validate fields, enforce enumerations (e.g., `httpMethod` in [`GET`,`POST`,`PUT`,`DELETE`]) and ensure `baseUrl` starts with `https://`.
- **Gov API Registry Client**: wraps REST call, handles retries on 5xx, surfaces 400 validation and 409 conflict with user-friendly explanation.
- **Storage**: reuses existing registry persistence; no new DB tables needed beyond API contract stored by backend.
- **Observability**: log prompt, truncated doc snippets, validation failures; metrics on doc fetch success/failure, LLM completion errors, registry responses.

## 5. Request / Response Contract
### Request `POST /api/v1/gov/apis`
```json
{
  "name": "US Open Data - Schools",
  "baseUrl": "https://api.data.gov/ed/schools",
  "httpMethod": "GET",
  "headers": [
    {"key": "X-API-KEY", "value": "********"},
    {"key": "Accept", "value": "application/json"}
  ],
  "queryParams": [
    {
      "key": "filters",
      "type": "OBJECT",
      "description": "Nested filter object",
      "children": [
        {"key": "state", "exampleValue": "CA", "type": "STRING", "description": "US state abbreviation"}
      ]
    },
    {"key": "per_page", "exampleValue": "50", "type": "INTEGER", "description": "Max results per page"}
  ],
  "bodyParams": [
    {"key": "payloadField", "exampleValue": "value-if-required-for-POST", "type": "STRING", "description": "Body field definition"}
  ],
  "description": "Fetch school directory from Dept of Education"
}
```

### Responses
- **201 Created**
  ```json
  {
    "id": "c0f22b44-4dfd-4e56-a0bb-293968bc0b0c",
    "name": "US Open Data - Schools",
    "status": "REGISTERED",
    "createdAt": "2024-06-20T10:05:13Z"
  }
  ```
- **400 Validation Error**
  ```json
  {
    "error": "VALIDATION_ERROR",
    "message": "baseUrl must be https://"
  }
  ```
- **409 Conflict** – returned when `name` already exists for the same `baseUrl`.

## 6. Data Model & Validation Rules
- `name`: non-empty string, unique per `baseUrl`.
- `baseUrl`: must be public HTTPS endpoint; apply regex `^https://[A-Za-z0-9.-]+.*`.
- `httpMethod`: enum GET/POST/PUT/PATCH/DELETE (LLM prompt should default to GET).
- `headers`: array of `{key,value}`; sensitive values (API keys) masked in UI logs but stored encrypted by backend.
- `queryParams` / `bodyParams` share schema: `key`, `type` (STRING, INTEGER, FLOAT, BOOLEAN, OBJECT, ARRAY), `description`, optional `exampleValue`, optional recursive `children` for nested structures.
- `description`: short summary (<200 chars) of API purpose.

## 7. Prompt Strategy
```
System: You convert government API documentation into registry payloads. 
Requirements:
- Only output valid JSON matching schema.
- baseUrl must be https://, httpMethod uppercase.
- Headers list should always include Accept if docs specify response type.
- Represent nested filters via children array.

User: <cleaned API doc text chunk(s)>
```
Use re-ranking to keep only sections mentioning endpoints, authentication, parameters, sample requests, rate limits. If docs provide multiple endpoints, prefer the one matching user intent (ask follow-up if ambiguous).

## 8. Error Handling
- **Doc fetch failure**: show actionable message and allow user to paste raw text.
- **LLM parsing failure**: re-prompt with stricter instructions or smaller chunk.
- **Validation**: highlight field-specific issues (e.g., baseUrl not https) before hitting backend.
- **Conflict 409**: surface existing registration and offer to edit/duplicate.

## 9. Testing Strategy
- Unit tests for fetcher (HTML → text), schema validator, prompt builder.
- Contract tests hitting dev endpoint (`http://localhost:8080/api/v1/gov/apis`) with mock payloads.
- E2E smoke: simulate user URL paste → confirm registry entry created.
- Manual test for conflict scenario to ensure proper UX guidance.

## 10. Open Questions
1. Which LLM (GPT-4o, Claude, internal) best balances accuracy vs cost?
2. Do we need human approval workflow for sensitive headers (API keys) before persisting?
3. Should we cache scraped doc text for faster re-prompting?
