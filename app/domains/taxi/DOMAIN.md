---
name: taxi
description: taxi availability, counts, distribution, hotspots, historical trends by zone or location
handler: app.domains.taxi.handler.handle
streaming_handler: app.domains.taxi.handler.handle_streaming
supports_request_id: true
---

## Capabilities
Connects to Singapore LTA DataMall real-time taxi data. Handles:
- Current taxi count near a location
- Which zone has the highest taxi density
- Taxi distribution hotspots

## Example Queries
- "How many taxis are near Orchard Road?"
- "Where are the most taxis island-wide right now?"
