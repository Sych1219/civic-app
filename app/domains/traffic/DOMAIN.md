---
name: traffic-cameras
description: traffic cameras, road conditions, congestion levels, expressway status, incidents
handler: app.domains.traffic.handler.handle
supports_request_id: false
---

## Capabilities
Connects to Singapore LTA traffic camera data. Handles:
- Current road conditions on a specified stretch
- Congestion levels on expressways
- Road incidents or abnormal events

## Example Queries
- "Is PIE congested right now?"
- "What does the CTE camera show?"
