# 📦 BMAD Product Artifacts (Họ A)

> ⚠️ **LƯU Ý (PRODUCT VISION / HIGH-LEVEL PRD — HỌ A)**:
> Thư mục này chứa toàn bộ tài liệu ý tưởng sản phẩm, PRD, User Stories và Market Research được tạo ra theo quy trình BMAD.
> **KHÔNG dùng các tài liệu trong thư mục này làm spec kỹ thuật để lập trình/implement.**
> 
> Mọi hoạt động lập trình, định nghĩa API, Database Schema, Agent Routing và Safety Control Flow bắt buộc tham chiếu theo bộ **Canonical Engineering Specs (Họ B)** tại:
> - [`docs/technical_spec.md`](../docs/technical_spec.md) (Chính)
> - [`docs/api_spec.md`](../docs/api_spec.md)
> - [`docs/agent_spec.md`](../docs/agent_spec.md)
> - [`docs/data_model.md`](../docs/data_model.md)
> - [`docs/safety_and_hitl.md`](../docs/safety_and_hitl.md)
> - [`docs/mqtt_spec.md`](../docs/mqtt_spec.md)

## Điểm lệch đã biết: MQTT topic

`ADR.md`, `PRD.md` và `product-brief.md` trong thư mục này mô tả xe ảo qua **2 topic** `vivi/vehicle/control` và `vivi/vehicle/status`. **Đó là bản cũ, không implement theo.**

Quy ước đang dùng là **5 topic** `v1/vehicles/{id}/...` theo [`docs/data_model.md`](../docs/data_model.md#mqtt-topics), [ADR-004](../docs/adr/ADR-004-mqtt-vehicle-simulator.md) và [`docs/mqtt_spec.md`](../docs/mqtt_spec.md).

Lý do: bản 2 topic không biểu diễn được vòng đời lệnh (accepted/rejected/completed), heartbeat, hay `state_version` — trong khi ADR-004 bắt buộc "state version và expected version là bắt buộc".

Giữ nguyên nội dung 3 file trên làm bản ghi lịch sử, không sửa.
