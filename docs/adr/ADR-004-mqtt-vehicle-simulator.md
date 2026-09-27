# ADR-004: MQTT Vehicle Digital Twin

- Status: Accepted
- Date: 2026-07-30

## Context

Đề tài cần chứng minh tool-use và quan sát trạng thái xe nhưng tuyệt đối không kết nối CAN/xe thật. Simulator phải hỗ trợ async command/result/state, lỗi broker, stale state và dashboard nhiều xe P2.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Function calls in-process | Nhanh, test đơn giản | Không mô phỏng bus/async failure và tách service kém |
| REST simulator | Quen thuộc, request-response rõ | State streaming/topic semantics kém tự nhiên |
| **MQTT broker + digital twin** | Event-driven, state topics, dễ multi-vehicle | Cần idempotency, ordering và broker config |

## Decision

Dùng Mosquitto MQTT. Tool executor publish command schema versioned tới allowlisted topics; digital twin validate invariant và publish command lifecycle + state snapshot. SQLite lưu audit/tool results, không dùng MQTT làm persistent source of truth.

Tên topic, QoS, retain, Birth/LWT và hình dạng payload cụ thể nằm ở [MQTT Transport Specification](../mqtt_spec.md) — ADR này chỉ chốt nguyên tắc.

## Rationale

- Phù hợp đề bài và minh họa bus tín hiệu xe mà không dùng CAN thật.
- Tách WS3 khỏi agent/UI qua contracts.
- Hỗ trợ fault injection và fleet simulator P2.
- Cho phép chứng minh observation thay vì optimistic success.

## Consequences

- Broker health/ACL là một phần DevOps.
- Duplicate delivery phải được deduplicate bằng idempotency key.
- State version và expected version là bắt buộc.
- Tool registry, không phải LLM, ánh xạ tool sang topic.
- Unit tests dùng in-memory adapter nhưng contract tests phải chạy Mosquitto.

## Revisit when

- Cần mô phỏng CAN frame/timing cấp thấp.
- Target edge không cho phép broker riêng.
- Simulator chuyển sang hardware-in-the-loop; khi đó cần gateway adapter mới nhưng giữ tool contract.

