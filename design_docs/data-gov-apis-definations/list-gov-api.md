## List / Search Gov Public APIs – Endpoint Design

### 1. Objective
- Provide a read-only endpoint to list registered government public APIs.
- Support exact lookup by registration `id`, and fuzzy search over `description`.
- Keep query model extensible so additional filters can be added without breaking clients.

### 2. REST Endpoint
| Item | Value | Notes |
| --- | --- | --- |
| Path | `/api/v1/gov/apis` | Same resource root as registration. |
| Method | `GET` | Retrieves existing registrations. |
| Consumes | `N/A` | No request body. |
| Produces | `application/json` | Paged list of registrations. |

### 3. Request Model
Query parameters are optional and composable. The endpoint supports:
- **Exact search**: provide `id` (UUID). When `id` is present, other filters are ignored and the response returns at most one item.
- **Fuzzy search**: provide `description` (case-insensitive `contains` match).
- **Pagination/sorting**: optional `page`, `size`, and `sort`.
- **Future filters**: optional nested `filters[...]` container to add fields later.

Example requests:
- Exact: `GET /api/v1/gov/apis?id=c0f22b44-4dfd-4e56-a0bb-293968bc0b0c`
- Fuzzy: `GET /api/v1/gov/apis?description=school&page=0&size=20`
- With future filters: `GET /api/v1/gov/apis?description=school&filters[httpMethod]=GET&sort=createdAt,desc`

### 4. Validation Rules
- `id` must be a valid UUID; invalid values return `400`.
- `description` length must be ≥ 3 when provided (mirrors registration constraint).
- When both `id` and `description` are supplied, `id` takes precedence and `description` is ignored.
- `page` must be ≥ 0; `size` must be between 1 and 100 (inclusive).
- `sort` format: `<field>,<asc|desc>`; unknown fields return `400`.
- `filters` is optional; unknown filter keys are ignored for now or rejected once enumerated (see Future Enhancements).

### 5. Response Contracts
**Success 200**
```json
{
  "items": [
    {
      "id": "c0f22b44-4dfd-4e56-a0bb-293968bc0b0c",
      "name": "US Open Data - Schools",
      "baseUrl": "https://api.data.gov/ed/schools",
      "httpMethod": "GET",
      "headers": [
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
      "description": "Fetch school directory from Dept of Education",
      "status": "REGISTERED",
      "createdAt": "2024-06-20T10:05:13Z"
    }
  ],
  "page": 0,
  "size": 20,
  "totalItems": 1,
  "totalPages": 1
}
```

**Validation Failure 400**
```json
{
  "error": "VALIDATION_ERROR",
  "message": "id must be a valid UUID"
}
```

**Domain Errors**
- `500 INTERNAL_SERVER_ERROR` for unexpected persistence failures.

### 6. Persistence
- This endpoint is read-only and does not create new records.
- Reads from table `gov_api_registration` with optional filtering by `id` or `description`.
- Indexes: rely on PK (`id`) and consider adding a full-text/GIN index on `description` if fuzzy search becomes slow.

### 7. Processing Steps
1. Validate query params (UUID, pagination, sort).
2. If `id` present, fetch a single `GovApiRegistration` by PK.
3. Else, build a dynamic query for `description` fuzzy match and any supplied `filters`.
4. Apply pagination and sorting.
5. Map entities to response items and return page envelope.

### 8. Error Handling
- Query validation errors map to `400` via global `@ControllerAdvice`.
- Missing `id` when `id` is supplied yields empty `items` with `totalItems: 0` (no 404 for list semantics).
- Always include correlation id `X-Request-Id` in response headers.

### 9. Swagger / OpenAPI
- Add controller method under `GovApiRegistrationController`:
  - `@GetMapping`
  - `@Operation(summary = "List or search registered government public APIs")`
- Document query params `id`, `description`, `page`, `size`, `sort`, and the `filters` object with example nested usage.
- Provide 200 and 400 response examples as above.

### 10. Future Enhancements
- Expand `filters` to include `status`, `httpMethod`, `name`, `createdAtFrom/To`, and `baseUrl` exact match.
- Support returning optional metadata blobs (`headers`, `queryParams`, `bodyParams`) via `include=metadata`.
- Upgrade fuzzy matching to database full-text search with ranking.
- Add cursor-based pagination for large datasets.
