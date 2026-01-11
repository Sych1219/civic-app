## Trigger Gov Public API – Endpoint Design

### 1. Objective
- Enable internal callers to execute a previously registered government public API via its persisted `id`.
- Reuse stored metadata (URL, method, headers, parameter schema) to build the outbound HTTP request.
- Accept runtime parameter values, optional header overrides, and defaults logic so automation jobs can proxy the external API safely.

### 2. REST Endpoint
| Item | Value | Notes |
| --- | --- | --- |
| Path | `/api/v1/gov/apis/{apiId}/trigger` | `apiId` corresponds to `gov_api_registration.id`. |
| Method | `POST` | Always POST because it initiates a trigger action. |
| Consumes | `application/json` | Runtime payload with query/body/header overrides. |
| Produces | `application/json` | Normalized response envelope. |

### 3. Request Model
Provide runtime parameter values that align with the metadata captured at registration time.

```json
{
  "query": {
    "filters": {
      "state": "CA",
      "district": "San Francisco"
    },
    "per_page": 50
  },
  "body": {
    "payloadField": "value-if-required-for-POST"
  },
  "headerOverrides": {
    "X-Request-Id": "job-20240620-001",
    "X-Caller": "batch-process-1"
  },
  "useExampleDefaults": true
}
```

- `query`: JSON tree that mirrors the registration `queryParams` definition (OBJECT nodes contain children, leaves carry scalar values).
- `body`: Flat object whose keys match `bodyParams` metadata; values are coerced to registered types.
- `headerOverrides`: Optional key/value map to override or extend stored headers (runtime wins on conflicts).
- `useExampleDefaults`: When `true`, missing query/body keys inherit registration `exampleValue`s; when `false`, only explicitly supplied values are sent.

### 4. Validation Rules
- `apiId` must be a valid UUID; malformed ids return `400`.
- Validate runtime `query`/`body` keys against the registered schema; unknown keys are rejected (400) until future enhancement toggles.
- Coerce values to registered types (INTEGER/FLOAT/BOOLEAN) and fail fast on parsing errors.
- Enforce payload size limits for `query`, `body`, and downstream `responseBody`.
- Respect `useExampleDefaults`: only auto-fill values when flag is `true` and metadata has `exampleValue`.

### 5. Response Contracts
**Success 200**
```json
{
  "status": "SUCCESS",
  "apiId": "c0f22b44-4dfd-4e56-a0bb-293968bc0b0c",
  "externalStatus": 200,
  "invokedAt": "2024-06-20T10:15:13Z",
  "requestId": "job-20240620-001",
  "responseBody": {
    "data": [
      {
        "school_name": "Example Elementary",
        "state": "CA"
      }
    ]
  }
}
```

**Validation Failure 400**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "Unknown query parameter: invalidKey"
}
```

**Registration Not Found 404**
```json
{
  "error": "API_NOT_FOUND",
  "message": "No registration found for id c0f22b44-4dfd-4e56-a0bb-293968bc0b0c"
}
```

**External Call Failure 502**
```json
{
  "error": "UPSTREAM_ERROR",
  "message": "External API returned 500",
  "externalStatus": 500
}
```

### 6. Persistence
- This endpoint does not create new persistence records; it reads from `gov_api_registration` to resolve metadata and emits transient proxy calls.
- Since no new data is stored, indexes/foreign keys beyond the existing registration PK are `N/A`.

### 7. Processing Steps
1. **Load registration**: Fetch `gov_api_registration` by `apiId`; if missing, return 404.
2. **Prepare outbound URL**: Start from `base_url`, merge runtime query with metadata (flatten nested objects, apply defaults), and construct the query string.
3. **Prepare headers**: Combine stored headers with `headerOverrides`, then append platform headers like correlation ids.
4. **Prepare request body**: For non-GET registrations, merge runtime body with metadata defaults, coerce types, and serialize JSON.
5. **Execute outbound HTTP call**: Invoke the remote API via `WebClient` (or equivalent) with timeout/retry policies.
6. **Build trigger response**: Capture upstream status/body, wrap in normalized envelope, and return to caller.

### 8. Error Handling
- Global `@ControllerAdvice` maps validation errors to 400, missing registrations to 404, and upstream failures/timeouts to 502 with `UPSTREAM_ERROR`.
- Always include `X-Request-Id` (caller-supplied or generated) in responses for traceability.
- Log outbound request metadata (without secrets) plus truncated response payloads for observability.

### 9. Swagger / OpenAPI
- Annotate controller method with `@Operation(summary = "Trigger registered government public API")`.
- Document the `apiId` path parameter and the trigger request schema, highlighting nested `query` behavior and `useExampleDefaults`.
- Provide response examples for success, validation failure, 404, and upstream error scenarios.

### 10. Future Enhancements
- Support asynchronous triggers (return 202 + job id, process in background, persist results).
- Add projection support to request only specific response fields.
- Introduce per-API rate limiting/circuit breaking knobs.
- Allow per-request overrides for timeout/retry policies within safe bounds.
