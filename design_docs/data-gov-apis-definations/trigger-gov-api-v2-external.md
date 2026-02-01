# Trigger Gov API v2 - API Specification

## Overview
This API executes registered API endpoints by their ID, automatically constructing and forwarding requests to external services. Submit simplified query and body parameters; the service handles routing, validation, and execution.

---

## Endpoint Information

| Property | Value |
|----------|-------|
| **Path** | `/api/v2/gov/apis/endpoints/{endpointId}/trigger` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Response-Type** | `application/json` |

### Path Parameters
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `endpointId` | UUID | Yes | Unique identifier of the registered endpoint |

---

## Request Format

### Request Body Structure

```json
{
  "queryParams": {
    "key": "value"
  },
  "bodyParams": {
    "key": "value"
  }
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `queryParams` | Object | No | Query parameters for the endpoint (key-value pairs) |
| `bodyParams` | Object | No | Body parameters for POST/PUT/PATCH requests (key-value pairs) |

**Rules:**
- Only provide fields used by the target endpoint
- Keys must match parameter names defined in the endpoint schema
- Values are automatically validated against the endpoint's schema

### Request Examples

**GET Request (query parameters only):**
```json
{
  "queryParams": {
    "date": "2024-06-20",
    "date_time": "2024-06-20T10:00:00+08:00"
  }
}
```

**POST Request (body parameters only):**
```json
{
  "bodyParams": {
    "title": "New Resource",
    "description": "Resource description",
    "active": true
  }
}
```

**POST Request (both query and body):**
```json
{
  "queryParams": {
    "format": "json"
  },
  "bodyParams": {
    "data": "payload content"
  }
}
```

---

## Response Format

### Success Response (200 OK)

```json
{
  "status": "SUCCESS",
  "endpointId": "e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
  "externalStatus": 200,
  "invokedAt": "2026-01-31T10:15:13Z",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "responseBody": {
    "items": [
      {
        "station_id": "S50",
        "value": 28.5
      }
    ]
  }
}
```

**Response Fields:**
| Field | Type | Description |
|-------|------|-------------|
| `status` | String | Execution status: `"SUCCESS"` or `"ERROR"` |
| `endpointId` | UUID | Endpoint identifier that was triggered |
| `externalStatus` | Integer | HTTP status code from the external API |
| `invokedAt` | ISO-8601 | Timestamp when the endpoint was executed |
| `requestId` | UUID | Unique request identifier for tracking |
| `responseBody` | Object/Array | Raw response from the external API |

---

## Error Responses

### 400 Bad Request - Validation Error

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Invalid query parameter: date format must be YYYY-MM-DD",
  "validationErrors": [
    "Parameter 'date': Invalid format, expected YYYY-MM-DD",
    "Parameter 'unknown_param': Not defined in OpenAPI specification"
  ],
  "timestamp": "2026-01-31T10:15:13Z",
  "requestId": "auto-generated-uuid"
}
```

**Common Validation Errors:**
- Unknown parameter name
- Missing required parameter
- Invalid parameter type or format
- Value outside allowed range
- Body parameters on GET/DELETE request

### 400 Bad Request - Missing Required Parameters

```json
{
  "error": "VALIDATION_ERROR",
  "message": "Missing required parameters",
  "validationErrors": [
    "Required query parameter 'date' is missing",
    "Required body property 'title' is missing"
  ],
  "timestamp": "2026-01-31T10:15:13Z",
  "requestId": "auto-generated-uuid"
}
```

### 404 Not Found - Endpoint Not Found

```json
{
  "error": "ENDPOINT_NOT_FOUND",
  "message": "No endpoint found with ID: e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
  "timestamp": "2026-01-31T10:15:13Z",
  "requestId": "auto-generated-uuid"
}
```

### 502 Bad Gateway - Upstream Error

When the external API returns an error:

```json
{
  "error": "UPSTREAM_ERROR",
  "message": "External API returned 500 Internal Server Error",
  "externalStatus": 500,
  "timestamp": "2026-01-31T10:15:13Z",
  "requestId": "auto-generated-uuid"
}
```

---

## HTTP Status Codes

| Status Code | Description |
|-------------|-------------|
| `200 OK` | Endpoint executed successfully |
| `400 Bad Request` | Invalid parameters or request format |
| `404 Not Found` | Endpoint ID doesn't exist |
| `502 Bad Gateway` | External API returned an error or timed out |
| `500 Internal Server Error` | Internal service error |

---

## Validation Rules

### Parameter Validation
- All parameter keys must exist in the endpoint schema
- Required parameters must be provided
- Values must match expected types (string, integer, boolean, number, array, object)
- Values must meet constraints (format, min/max length, min/max value, pattern, enum)

### HTTP Method Rules
- **GET/DELETE**: Cannot include `bodyParams` (returns 400)
- **POST/PUT/PATCH**: May include both `queryParams` and `bodyParams`

### Value Types

| Type | Format | Example |
|------|--------|---------|
| `string` | Quoted text | `"date": "2024-06-20"` |
| `integer` | Number without quotes | `"count": 25` |
| `boolean` | `true` or `false` | `"active": true` |
| `number` | Decimal without quotes | `"temperature": 28.5` |
| `array` | JSON array | `"tags": ["a", "b"]` |
| `object` | JSON object | `"meta": {"key": "val"}` |

---

## Complete Workflow Example

### Step 1: Get endpoint ID from schema API
```http
GET /api/v2/gov/apis/schemas
```

Response includes endpoint ID and parameter requirements.

### Step 2: Prepare trigger request

Based on schema information:
- Endpoint ID: `e8f33c55-6def-4f67-c1dd-394a69cd2c4d`
- Required parameters: `date` (query, string, format: YYYY-MM-DD)
- Optional parameters: `date_time` (query, string, format: ISO-8601)

### Step 3: Execute trigger
```http
POST /api/v2/gov/apis/endpoints/e8f33c55-6def-4f67-c1dd-394a69cd2c4d/trigger
Content-Type: application/json

{
  "queryParams": {
    "date": "2024-06-20",
    "date_time": "2024-06-20T10:00:00+08:00"
  }
}
```

### Step 4: Process response
```json
{
  "status": "SUCCESS",
  "endpointId": "e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
  "externalStatus": 200,
  "invokedAt": "2026-01-31T10:15:13Z",
  "requestId": "550e8400-e29b-41d4-a716-446655440000",
  "responseBody": {
    "items": [...],
    "metadata": {...}
  }
}
```

The `responseBody` contains the actual data from the external API.

---

## Best Practices

1. **Use Schema API first**: Call `/api/v2/gov/apis/schemas` to discover endpoints and their parameter requirements
2. **Match parameter types**: Ensure values match expected types (e.g., integers as numbers, not strings)
3. **Handle required parameters**: Always provide all required parameters
4. **Check external status**: Examine `externalStatus` in the response to verify external API success
5. **Use request IDs**: Include `X-Request-Id` header for tracking and debugging
6. **Handle errors gracefully**: Implement retry logic for 502 errors (upstream failures)

---

## Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Content-Type` | Yes | Must be `application/json` |
| `X-Request-Id` | No | Optional tracking ID (auto-generated if not provided) |

---

## Response Time

- **Typical**: 500ms - 3s (depends on external API)
- **Timeout**: 20 seconds (returns 502 if external API doesn't respond)

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 400 "Unknown parameter" | Parameter name doesn't match schema. Check schema API for correct names. |
| 400 "Missing required parameter" | Add all required parameters. Check schema API for requirements. |
| 400 "Invalid format" | Check parameter format requirements (e.g., date must be YYYY-MM-DD). |
| 400 "Invalid type" | Ensure correct JSON types (numbers without quotes, booleans as true/false). |
| 404 "Endpoint not found" | Verify endpoint ID is correct. Check if endpoint is registered. |
| 502 "Upstream error" | External API is down or returned an error. Check `externalStatus` for details. Retry if transient. |

---

## Rate Limiting

- Rate limits may apply per endpoint
- Check response headers for rate limit information
- Implement backoff strategies for repeated requests

---

## Related APIs

| API | Endpoint | Purpose |
|-----|----------|----------|
| **Schema API** | `GET /api/v2/gov/apis/schemas` | Discover endpoints and their parameter requirements |
| **Registration API** | `POST /api/v2/gov/apis/openapi` | Register new endpoints |

---

## Support

For questions or issues:
- Include the `requestId` from error responses when contacting support
- Provide the `endpointId` for endpoint-specific issues
- Check schema API to verify parameter requirements
