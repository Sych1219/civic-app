# Endpoint Schema API - API Specification

## Overview
This API returns metadata for all registered API endpoints, including descriptions and parameters. Use this to discover available endpoints and understand their requirements.

---

## Endpoint Information

| Property | Value |
|----------|-------|
| **Path** | `/api/v2/gov/apis/schemas` |
| **Method** | `GET` |
| **Response-Type** | `application/json` |

---

## Request Format

### HTTP Request
```http
GET /api/v2/gov/apis/schemas HTTP/1.1
Host: api.example.com
Accept: application/json
```

### Request Headers
| Header | Required | Description |
|--------|----------|-------------|
| `Accept` | No | Should be `application/json` (default) |
| `X-Request-Id` | No | Optional request tracking ID |

### Query Parameters
None. This endpoint returns all available schemas.

---

## Response Format

### Success Response (200 OK)

Returns a list of all registered endpoint schemas with their parameters.

```json
{
  "schemas": [
    {
      "id": "e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
      "description": "Returns current air temperature readings from weather stations across Singapore. Data is updated every 5 minutes. Use this API when users ask for temperature, weather conditions, or climate data in Singapore.",
      "parameters": [
        {
          "name": "date",
          "location": "query",
          "required": true,
          "type": "string",
          "description": "Date for temperature readings. Format: YYYY-MM-DD (e.g., 2024-06-20). Use current date if user says 'today', yesterday's date if user says 'yesterday'."
        },
        {
          "name": "date_time",
          "location": "query",
          "required": false,
          "type": "string",
          "description": "Specific timestamp for readings. Format: ISO 8601 with timezone (e.g., 2024-06-20T10:00:00+08:00). Optional - only include if user specifies exact time."
        }
      ]
    },
    {
      "id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
      "description": "Creates a new resource in the system. Use this when user wants to add, create, or register new data.",
      "parameters": [
        {
          "name": "title",
          "location": "body",
          "required": true,
          "type": "string",
          "description": "Title or name of the resource. Must be 1-200 characters."
        },
        {
          "name": "description",
          "location": "body",
          "required": false,
          "type": "string",
          "description": "Optional description of the resource."
        },
        {
          "name": "active",
          "location": "body",
          "required": false,
          "type": "boolean",
          "description": "Whether resource is active. Default is true."
        }
      ]
    }
  ]
}
```

### Response Structure

#### Root Object
| Field | Type | Description |
|-------|------|-------------|
| `schemas` | Array | List of all registered endpoint schemas |

#### Schema Object
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | UUID | Yes | Unique endpoint identifier used for triggering API calls |
| `description` | String | Yes | High-level description of endpoint purpose and usage |
| `parameters` | Array | Yes | List of parameters needed to call this endpoint |

#### Parameter Object
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | String | Yes | Parameter name to use in requests |
| `location` | String | Yes | Where to place parameter: `"query"` or `"body"` |
| `required` | Boolean | Yes | Whether this parameter must be provided |
| `type` | String | Yes | Data type: `string`, `integer`, `boolean`, `number`, `array`, `object` |
| `description` | String | Yes | Detailed description including format requirements and constraints |

---

## Empty Response

When no endpoints are registered, the API returns an empty schemas array:

```json
{
  "schemas": []
}
```

**Status:** 200 OK

---

## Error Responses

### 500 Internal Server Error

When the service encounters an internal error:

```json
{
  "error": "INTERNAL_SERVER_ERROR",
  "message": "Failed to retrieve endpoint schemas",
  "timestamp": "2026-02-01T10:15:13Z",
  "requestId": "auto-generated-uuid"
}
```

---

## HTTP Status Codes

| Status Code | Description |
|-------------|-------------|
| `200 OK` | Successfully retrieved schemas (may be empty array) |
| `500 Internal Server Error` | Server error during retrieval |

---

## Parameter Locations

The `location` field indicates where to place each parameter:

| Location | Placement | Example |
|----------|-----------|----------|
| `"query"` | URL query string | `/api/endpoint?date=2024-06-20` |
| `"body"` | JSON request body | `{ "title": "New Item" }` |

**Note:** Only query and body parameters are exposed. Headers and path parameters are handled by the service.

---

## Use Cases

- **API Discovery**: List all available endpoints and their capabilities
- **Request Construction**: Build valid API requests programmatically using parameter metadata
- **Integration**: Enable automated systems to discover and call endpoints dynamically

---

## Using Schemas to Construct Requests

### Workflow

1. **Retrieve schemas**: `GET /api/v2/gov/apis/schemas`
2. **Select endpoint**: Find the endpoint ID that matches your needs
3. **Build parameters**: Create `queryParams` or `bodyParams` based on parameter `location`
4. **Execute**: Use the endpoint ID and parameters with the trigger API

### Example

**Schema:**
```json
{
  "id": "e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
  "description": "Returns air temperature readings",
  "parameters": [
    {"name": "date", "location": "query", "required": true, "type": "string"},
    {"name": "station_id", "location": "query", "required": false, "type": "string"}
  ]
}
```

**Trigger Request:**
```http
POST /api/v2/gov/apis/endpoints/e8f33c55-6def-4f67-c1dd-394a69cd2c4d/trigger

{"queryParams": {"date": "2024-06-20", "station_id": "S50"}}
```

---

## Parameter Types

| Type | JSON Value Format | Example |
|------|------------------|----------|
| `string` | Quoted text | `"title": "My Title"` |
| `integer` | Number without quotes | `"count": 25` |
| `boolean` | `true` or `false` without quotes | `"active": true` |
| `number` | Decimal without quotes | `"temperature": 28.5` |
| `array` | JSON array | `"tags": ["weather", "singapore"]` |
| `object` | JSON object | `"metadata": {"key": "value"}` |

---

## Best Practices

1. **Cache responses**: Schemas change infrequently; cache for 5-15 minutes
2. **Filter programmatically**: Search descriptions for keywords to find relevant endpoints
3. **Validate required parameters**: Check all `required: true` parameters are provided
4. **Use correct types**: Send integers as numbers, booleans as true/false (not strings)
5. **Read descriptions**: Parameter descriptions include format requirements and constraints

---

## Response Size

- **Typical size**: 10-100 KB
- **Per endpoint**: ~1-5 KB average
- **Note**: Response size grows with number of registered endpoints

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Empty `schemas` array | Normal if no endpoints are registered. Verify registration status. |
| 500 Internal Server Error | Retry after a short delay. Contact support with `requestId` if persists. |
| Missing header/path parameters | Expected behavior. Only query and body parameters are exposed. |

---

## Related APIs

| API | Endpoint | Purpose |
|-----|----------|----------|
| **Trigger API** | `POST /api/v2/gov/apis/endpoints/{id}/trigger` | Execute endpoints using IDs from schemas |
| **Registration API** | `POST /api/v2/gov/apis/openapi` | Register new endpoints via OpenAPI spec |

---

## Support

For questions or issues:
- Include the `X-Request-Id` when contacting support
- Provide endpoint IDs when reporting schema-specific issues
- Check this documentation for parameter format requirements
