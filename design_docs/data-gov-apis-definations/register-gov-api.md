## Register Gov Public API – Endpoint Design

### 1. Objective
- Allow internal users to register external government public APIs that our platform will later call.
- Persist full invocation contract so downstream jobs can fetch URL, HTTP method, headers, and query/body parameters.

### 2. REST Endpoint
| Item | Value |
| --- | --- |
| Path | `/api/v1/gov/apis` |
| Method | `POST` |
| Consumes | `application/json` |
| Produces | `application/json` |

### 3. Request Model
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

Each entry in `queryParams` carries the metadata plus optional `children` so teams can model nested structures such as `filters[state]=CA`. Parent nodes use `type: OBJECT` and omit `exampleValue`; leaf nodes may provide an `exampleValue` that can be used to generate sample requests. `bodyParams` remain flat key/exampleValue definitions.

### 4. Validation Rules
- `name`, `baseUrl`, `httpMethod` required.
- `baseUrl` must be HTTPS, validated by URI parser.
- `httpMethod` enum: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`.
- `headers`, `queryParams`, `bodyParams` optional arrays; reject duplicate keys inside each array.
- `queryParams.type` enum `STRING|INTEGER|FLOAT|BOOLEAN|OBJECT`; `bodyParams.type` enum `STRING|INTEGER|FLOAT|BOOLEAN`. `description` free text for documentation (min 3 chars).
- For nested query params, parent entries (`type: OBJECT`) may include `children` arrays and must omit `exampleValue`; leaf entries may provide an `exampleValue` but it is optional.

### 5. Response Contracts
**Success 201**
```json
{
  "id": "c0f22b44-4dfd-4e56-a0bb-293968bc0b0c",
  "name": "US Open Data - Schools",
  "status": "REGISTERED",
  "createdAt": "2024-06-20T10:05:13Z"
}
```

**Validation Failure 400**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "baseUrl must be https://"
}
```

**Conflict 409**
- Occurs when a `name` already exists for same `baseUrl`.

### 6. Persistence
- Table `gov_api_registration`
  - `id` UUID PK
  - `name`, `description`
  - `base_url`, `http_method`
  - `headers_json`, `query_params_json`, `body_params_json`
  - `created_at`

### 7. Processing Steps
1. Validate payload with `@Valid` DTO + custom validators for URL, duplicates.
2. Normalize header/parameter lists into Map before persistence.
3. Save record via `GovApiRegistrationService`.

### 8. Error Handling
- Use global `@ControllerAdvice` to wrap exceptions.
- Timeouts or network failures are not expected on registration since we only store metadata.
- Include correlation id header `X-Request-Id` in responses for tracing.

### 9. Swagger / OpenAPI
- Annotate controller with `@Operation(summary = "Register government public API")`.
- Document enums and parameter schemas for generated API docs.

### 10. Future Enhancements
- Support PATCH endpoint to update registration.
- Allow uploading OpenAPI spec and auto-populate headers/parameters.
