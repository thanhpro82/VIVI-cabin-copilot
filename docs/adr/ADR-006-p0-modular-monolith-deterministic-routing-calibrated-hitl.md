# ADR-006: P0 Modular Monolith, Deterministic-First Routing and Calibrated HITL

- Status: Accepted
- Date: 2026-07-31
- Decision owners: WS1, WS2, WS3, WS4
- Supersedes: Các routing và safety-classification clauses của [ADR-002](./ADR-002-bounded-agent-and-safety-policy.md)

## Context

Nhóm có bốn người và ba đến bốn tuần. [PoC report](../../eval/results/report.md) cho thấy tool exact của Qwen2.5-0.5B và Qwen2.5-3B chưa đạt gate; [ADR-005](./ADR-005-model-profile-selection.md) vì vậy vẫn chưa chọn model profile. Trong khi đó, topology bảy service tăng integration cost và policy approval cho mọi actuator tạo xác nhận thừa khi lái.

## Alternatives

1. Giữ topology bảy service và policy mọi actuator là S2.
2. Thay toàn bộ bằng kiến trúc tham khảo của thành viên nhóm.
3. Hợp nhất có chọn lọc và thu gọn còn năm service.

## Decision

1. P0 dùng năm service: `ivi-web`, `backend`, `llm`, `mqtt`, `vehicle-simulator`.
2. `backend` là modular monolith; Voice và Agent vẫn tách module/workstream.
3. Deterministic intent/slot router xử lý lệnh P0 trước SLM.
4. Router/SLM chỉ tạo internal typed `CandidateActionPlan` không có safety fields; pure/common validation chạy trước khi deterministic safety materialize canonical immutable `ActionPlan` và giữ authority cuối.
5. S0 là read-only; S1 gồm HVAC, seat heating, media và navigation; window luôn là S2; door và seat position là S2 khi xe đứng yên, chuyển thành S3 khi state không cho phép.
6. Mixed plan có S2 phải được bundled approval trước side effect đầu tiên; plan có S3 không chạy side effect.
7. FAISS và SQLite chạy embedded; llama.cpp, Mosquitto và simulator giữ service riêng.
8. `search_nearby_poi` là S0 local planning resolution: validate trước I/O; dùng stable candidate identity, plan-independent unique record và lease pinned fixture để tạo exactly-one observable/effectively-once terminal outcome; candidate lookup step được loại khỏi executable plan, còn empty result không tạo canonical plan hay side effect.
9. Mỗi session có tối đa một pending approval. Voice approval intent chỉ tạo typed handoff; REST là decision authority. Reject/expiry/state-plan-predicate invalidation tạo zero side effect.

## Rationale

Phương án ba giữ được typed contracts, grounded RAG, idempotency và state-version safety target đã được tài liệu hóa, đồng thời giảm integration overhead. Kết quả PoC ủng hộ deterministic-first vì cả hai SLM chưa đạt tool-exact gate. Calibrated HITL đáp ứng ràng buộc cửa/kính cần xác nhận nhưng tránh làm gián đoạn HVAC, media và navigation ít rủi ro.

## Consequences

- Giảm hai service và hai internal API boundary ở P0.
- Tăng trách nhiệm giữ module ports rõ trong backend.
- Giảm phụ thuộc vào tool-calling của SLM.
- Demo HITL chuyển từ HVAC sang cửa/kính.
- Manual ingestion, eval execution và model activation API chuyển P1.

## Revisit when

- Voice hoặc Agent cần scale hoặc isolation độc lập theo benchmark.
- Tool exact của SLM đạt gate đủ để thay đổi deterministic coverage.
- Nhóm kết nối hardware hoặc vehicle interface ngoài simulator.
