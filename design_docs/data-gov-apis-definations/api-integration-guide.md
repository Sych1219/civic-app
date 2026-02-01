# API Integration Guide - Schema Discovery & Endpoint Trigger

## Overview

This guide explains how to use the **Schema API** and **Trigger API** together to dynamically discover and execute registered endpoints. These two APIs form a complete workflow for API orchestration.

---

## API Relationship

```
┌─────────────────────────────────────────────────────────────┐
│                     Integration Workflow                     │
└─────────────────────────────────────────────────────────────┘

Step 1: Discover Available Endpoints
┌──────────────────────────────────────┐
│   GET /api/v2/gov/apis/schemas       │
│   (Schema Discovery API)             │
└──────────────────────────────────────┘
                  │
                  ▼
         Returns: Endpoint IDs + 
         Parameter Requirements
                  │
                  ▼
Step 2: Execute Specific Endpoint
┌──────────────────────────────────────┐
│   POST /api/v2/gov/apis/endpoints/   │
│        {endpointId}/trigger          │
│   (Endpoint Trigger API)             │
└──────────────────────────────────────┘
                  │
                  ▼
         Returns: Execution Results
```

---

## The Two APIs

### 1. Schema API (Discovery)
**Purpose:** Discover what endpoints are available and what parameters they need

**Endpoint:** `GET /api/v2/gov/apis/schemas`

**Returns:**
- List of all registered endpoints
- Endpoint IDs
- Parameter names and requirements
- Data types and validation rules

**Use this to:**
- Find available endpoints
- Understand parameter requirements
- Build valid trigger requests

### 2. Trigger API (Execution)
**Purpose:** Execute a specific endpoint with parameters

**Endpoint:** `POST /api/v2/gov/apis/endpoints/{endpointId}/trigger`

**Requires:**
- Endpoint ID (from Schema API)
- Parameters matching schema requirements

**Returns:**
- Execution results from external API
- Status codes and metadata

**Use this to:**
- Execute discovered endpoints
- Send validated parameters
- Get results from external APIs

---

## Complete Integration Flow

### Step 1: Discover Endpoints

Call the Schema API to get all available endpoints:

```http
GET /api/v2/gov/apis/schemas
```

**Response Example:**
```json
{
  "schemas": [
    {
      "id": "e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
      "description": "Returns air temperature readings from weather stations",
      "parameters": [
        {
          "name": "date",
          "location": "query",
          "required": true,
          "type": "string",
          "description": "Date in YYYY-MM-DD format"
        },
        {
          "name": "station_id",
          "location": "query",
          "required": false,
          "type": "string",
          "description": "Specific weather station ID"
        }
      ]
    }
  ]
}
```

### Step 2: Select Relevant Endpoint

From the schema response:
1. **Read descriptions** to find the endpoint you need
2. **Note the endpoint ID**: `e8f33c55-6def-4f67-c1dd-394a69cd2c4d`
3. **Review parameters**: Identify required vs optional parameters
4. **Check parameter types and locations**: Build your request accordingly

### Step 3: Prepare Trigger Request

Based on the schema information, construct your trigger request:

**Required from schema:**
- `date` parameter (query, required, string)

**Optional from schema:**
- `station_id` parameter (query, optional, string)

**Build request payload:**
```json
{
  "queryParams": {
    "date": "2024-06-20",
    "station_id": "S50"
  }
}
```

### Step 4: Execute Endpoint

Call the Trigger API with the endpoint ID and parameters:

```http
POST /api/v2/gov/apis/endpoints/e8f33c55-6def-4f67-c1dd-394a69cd2c4d/trigger
Content-Type: application/json

{
  "queryParams": {
    "date": "2024-06-20",
    "station_id": "S50"
  }
}
```

**Response Example:**
```json
{
  "status": "SUCCESS",
  "endpointId": "e8f33c55-6def-4f67-c1dd-394a69cd2c4d",
  "externalStatus": 200,
  "invokedAt": "2026-02-01T10:15:13Z",
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

---

## Parameter Location Mapping

The Schema API tells you **where** each parameter goes. The Trigger API expects parameters in the corresponding location.

| Schema `location` | Trigger Request Field | Example |
|-------------------|----------------------|---------|
| `"query"` | `queryParams` | `{"queryParams": {"date": "2024-06-20"}}` |
| `"body"` | `bodyParams` | `{"bodyParams": {"title": "New Item"}}` |

### Example: Mixed Parameters

**Schema Response:**
```json
{
  "id": "abc-123",
  "parameters": [
    {"name": "format", "location": "query", "type": "string"},
    {"name": "title", "location": "body", "type": "string"},
    {"name": "active", "location": "body", "type": "boolean"}
  ]
}
```

**Trigger Request:**
```json
{
  "queryParams": {
    "format": "json"
  },
  "bodyParams": {
    "title": "New Resource",
    "active": true
  }
}
```

---

## Key Integration Points

### 1. Endpoint ID
- **Schema API** provides the endpoint ID
- **Trigger API** requires the endpoint ID in the URL path
- IDs are UUIDs and uniquely identify each endpoint

### 2. Parameter Names
- **Schema API** lists exact parameter names
- **Trigger API** validates that parameter names match the schema
- Use the exact names from the schema (case-sensitive)

### 3. Parameter Types
- **Schema API** specifies data types (string, integer, boolean, etc.)
- **Trigger API** validates parameter types
- Ensure values match expected types (e.g., numbers without quotes)

### 4. Required Parameters
- **Schema API** indicates which parameters are required
- **Trigger API** returns 400 error if required parameters are missing
- Always provide all required parameters

### 5. Parameter Locations
- **Schema API** specifies location: "query" or "body"
- **Trigger API** expects parameters in corresponding fields
- Map correctly: query → queryParams, body → bodyParams

---

## Error Handling Across Both APIs

### Schema API Errors

| Error | Meaning | Action |
|-------|---------|--------|
| 500 Internal Server Error | Service error | Retry after delay |
| Empty schemas array | No endpoints registered | Register endpoints first |

### Trigger API Errors

| Error | Meaning | Action |
|-------|---------|--------|
| 400 Validation Error | Parameters don't match schema | Check schema API for requirements |
| 404 Not Found | Invalid endpoint ID | Verify ID from schema API |
| 502 Bad Gateway | External API failed | Check externalStatus, retry if appropriate |

---

## Best Practices

### 1. Schema-First Approach
- Always call Schema API before first Trigger API call
- Cache schema responses to reduce API calls
- Refresh schema periodically or when endpoints change

### 2. Parameter Validation
- Validate parameters against schema before triggering
- Check required parameters are provided
- Ensure parameter types match schema expectations

### 3. Error Recovery
- Handle 404 errors by re-fetching schemas (endpoint may have been removed)
- Implement retry logic for 502 errors (transient external API failures)
- Parse validation errors to guide users on fixing inputs

### 4. Performance Optimization
- Cache schema responses (TTL: 5-15 minutes)
- Batch schema lookups if triggering multiple endpoints
- Use request IDs for tracking and debugging

### 5. Type Safety
- Use schema information to enforce type constraints
- Convert string inputs to correct types (integer, boolean) before triggering
- Validate formats (dates, emails) before sending

---

## Quick Reference

### When to Use Schema API
- ✅ On application startup (to discover available endpoints)
- ✅ When users need to select from available endpoints
- ✅ To validate inputs before triggering
- ✅ When endpoint registration changes
- ✅ To build dynamic forms or UIs

### When to Use Trigger API
- ✅ After selecting an endpoint from schemas
- ✅ When you have all required parameters
- ✅ To execute and get results from external APIs
- ✅ After validating inputs against schema requirements

### API Call Sequence
```
1. GET /api/v2/gov/apis/schemas (once or cached)
2. Process schemas, select endpoint
3. POST /api/v2/gov/apis/endpoints/{id}/trigger (as needed)
4. Process results
5. Repeat step 3 for additional executions
```

---

## Related Documentation

- **Schema API Specification**: `endpoint-schema-api-external.md`
- **Trigger API Specification**: `trigger-gov-api-v2-external.md`
- **Registration API**: For adding new endpoints to the system

---

## Support

For integration questions:
- Review schema responses to understand parameter requirements
- Use request IDs from both APIs for debugging
- Check parameter types and locations match between APIs
- Verify endpoint IDs are valid UUIDs from schema responses
