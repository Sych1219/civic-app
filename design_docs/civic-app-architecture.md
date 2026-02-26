# Civic App — Design Documentation

> This document serves as the index for all Civic App design documentation.
> The original monolithic architecture doc has been split into focused, maintainable sub-documents.

## Documents

| Document | Description |
|----------|-------------|
| [Architecture Overview](architecture-overview.md) | System diagram, request lifecycle, component responsibilities, tech stack, project structure |
| [API Contract](api-contract.md) | REST endpoints, request/response models, error semantics, interactive docs |
| [Data Processing Strategies](data-processing-strategies.md) | GeoJSON conversion, time-series handling, detection flow, property model |
| [Chat Message Contract](chat-message-contract.md) | Chat endpoint (`POST /api/chat`), message models, LLM summary pipeline, session management |

## Related References

| File | Purpose |
|------|---------|
| `data-gov-apis-definations/` | External API specifications and integration guide |
