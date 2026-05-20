---
name: taxi
description: taxi availability, counts, distribution, hotspots, historical trends by zone or location
handler: app.domains.taxi.handler.handle
streaming_handler: app.domains.taxi.handler.handle_streaming
supports_request_id: true
---

## 能力说明
对接新加坡 LTA DataMall 实时出租车数据，可回答：
- 某地点附近当前有多少辆出租车
- 哪个区域出租车密度最高
- 出租车分布热点

## 示例 Query
- "Orchard Road 附近有多少辆出租车？"
- "现在全岛出租车最多的地方在哪？"
