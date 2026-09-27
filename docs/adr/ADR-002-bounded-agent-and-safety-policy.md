# ADR-002: Bounded Agent with Deterministic Safety Policy

- Status: Accepted; routing and safety-classification clauses amended by [ADR-006](./ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md)
- Date: 2026-07-30

## Context

Hệ thống cần hiểu tiếng Việt tự nhiên, RAG, tool-use và yêu cầu nhiều bước. Agent tự do có thể gọi sai tool, bỏ qua xác nhận hoặc tạo latency khó kiểm soát. Mọi actuator trong đề tài cần HITL và một số hành động phải bị chặn theo vehicle state kể cả khi user đồng ý.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Workflow/rules hoàn toàn | Deterministic, nhanh | Kém với ngôn ngữ tự nhiên và tổ hợp multi-step |
| ReAct agent tự do | Linh hoạt, ít code orchestration | Tool/safety khó bảo đảm, nhiều loop, latency cao |
| **Bounded agent + policy ngoài LLM** | Linh hoạt nhưng kiểm soát được | Cần schemas, validators và nhiều contract tests |

## Decision

**Amendment note (2026-07-31):** ADR-006 thay thế clause “SLM route mọi lệnh” bằng deterministic-first và clause “mọi actuator là S2” bằng calibrated S0–S3. Hai clause này không còn là policy active; policy hiện hành nằm trong ADR-006.

### Original decision — retained for history

Dùng LangGraph state machine. SLM route/lập `ActionPlan` theo JSON Schema; deterministic validator và safety policy phân loại S0–S3. Tool executor chỉ nhận plan đã validate và approval hợp lệ. Mọi actuator là S2; state-incompatible action là S3/default deny.

Control, knowledge và safety được trình bày như logical subgraphs, không phải autonomous agents độc lập. Số node gọi LLM tối đa bốn mỗi run.

LangGraph interrupt/checkpoint được dùng để pause/resume approval: [official interrupts documentation](https://docs.langchain.com/oss/python/langgraph/interrupts).

### Invariants still in effect

- Router/planner tạo internal typed `CandidateActionPlan`; deterministic policy materialize canonical immutable `ActionPlan`, và tool executor chỉ nhận canonical plan đã validate/classify.
- Deterministic safety policy là authority cuối, nằm ngoài SLM.
- S3/default deny không có đường bypass bằng approval.
- HITL vẫn gắn với state version, expiry và single-use; executor vẫn phải idempotent.

## Rationale

- Đáp ứng agentic fit mà vẫn giữ accountability.
- Schema/tool results cho phép exact-match eval và audit.
- Policy ngoài LLM chống prompt injection/yêu cầu “bỏ qua an toàn”.
- Bounded loop và fallback phù hợp latency edge.

## Consequences

- Tool/plan schemas là shared API cần versioning.
- Approval phải gắn state version, expiry và idempotency.
- Composer không được nói success nếu thiếu persisted ToolResult.
- Mọi tool mới phải có safety classification và tests trước khi vào registry.
- Một số câu tự nhiên sẽ bị hỏi lại thay vì đoán.

## Revisit when

- Planner exact match thấp hơn 90% dù đã áp dụng repair/fallback.
- LangGraph overhead trở thành bottleneck đáng kể so với workflow thuần.
- Phạm vi chuyển từ simulator sang hệ thống có yêu cầu chứng nhận chính thức; khi đó cần safety engineering sâu hơn, không chỉ sửa agent.
