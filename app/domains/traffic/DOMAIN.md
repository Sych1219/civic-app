---
name: traffic-cameras
description: traffic cameras, road conditions, congestion levels, expressway status, incidents
handler: app.domains.traffic.handler.handle
supports_request_id: false
---

## 能力说明
对接新加坡 LTA 交通摄像头数据，可回答：
- 指定路段当前路况
- 某高速公路拥堵情况
- 路面事故或异常事件

## 示例 Query
- "PIE 现在堵吗？"
- "CTE 摄像头情况怎么样？"
