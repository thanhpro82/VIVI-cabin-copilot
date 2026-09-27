# AI Fit Analysis

## Kết luận

Chọn **bounded reactive agent + deterministic safety workflow**. Đây là mức agentic vừa đủ để xử lý ngôn ngữ tự nhiên, RAG, tool và yêu cầu nhiều bước, nhưng không trao quyền tự chủ cho hành động tác động trạng thái xe.

Safety authority: [ADR-006](adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md) và [Safety and Human-in-the-Loop Specification](safety_and_hitl.md).

## AI fit ladder

| Mức giải pháp | Khả năng đáp ứng | Quyết định |
|---|---|---|
| Rule-based | Rất tốt cho state guard và validation; kém với diễn đạt tiếng Việt đa dạng | Dùng trong safety, không dùng làm toàn hệ thống |
| Workflow automation | Tốt cho luồng cố định, nhanh và dễ test | Dùng làm khung điều phối/fallback |
| Chatbot/RAG | Tốt cho hỏi đáp sổ tay | Không đủ vì không thực hiện tool/multi-step |
| Reactive agent | Lập kế hoạch, chọn tool theo observation | Chọn, nhưng bị giới hạn bằng schema/policy |
| Autonomous agent | Theo đuổi mục tiêu dài hạn | Loại vì latency, safety và accountability |

## Agentic Fit

| Tiêu chí | Đánh giá | Bằng chứng từ use case |
|---|---|---|
| Multi-step reasoning | Cao | POI → HVAC → navigation có dependency |
| Tool interaction | Cao | HVAC, media, cửa/kính, navigation, RAG |
| Dynamic decision | Trung bình–cao | Route theo intent, confidence và vehicle state |
| Long horizon/memory | Thấp–trung bình | Chỉ giữ trip memory, không tự lập mục tiêu dài hạn |
| Cost/latency tolerance | Thấp | Cabin cần first audio nhanh; giới hạn loop |
| Risk/accountability | Cao | Deterministic policy đặt S0–S3; S1 execute trực tiếp, S2 HITL, S3 block và mọi outcome có audit |

## Vì sao không dùng giải pháp đơn giản hơn

- **Rule-only:** không bao phủ tốt “nóng quá”, tham chiếu ngữ cảnh và câu ghép tự nhiên.
- **Workflow-only:** số tổ hợp multi-step tăng nhanh; workflow vẫn được giữ làm fallback.
- **Chatbot:** có thể trả lời nhưng không đủ hợp đồng thực thi và quan sát vehicle state.
- **RAG-only:** chỉ giải quyết sổ tay, không giải quyết control/navigation.

## Ranh giới quyền tự chủ

| Agent được phép | Agent phải xin phép | Agent luôn bị chặn |
|---|---|---|
| Route, retrieve, propose typed plan; S0/S1 chỉ được executor thực thi sau policy | Chỉ S2: window; door/seat position khi stationary state được policy cho phép | Tự gán safety, bỏ qua state guard/HITL, thực thi xe thật, tự sửa policy, publish MQTT hoặc dùng tool ngoài allowlist |

Deterministic policy, không phải AI, đặt safety level S0–S3. S1 direct execute sau policy; S2 cần HITL; S3 bị block. AI không publish MQTT. Người dùng chịu trách nhiệm approve/reject S2 plan mô phỏng. Safety owner chịu trách nhiệm policy. Kỹ sư chịu trách nhiệm model/config rollout.

## Kiến trúc uncertainty

### Input uncertainty

- STT confidence thấp, tiếng ồn, giọng vùng miền.
- Câu mơ hồ: “mở nó ra”, “lạnh quá”.
- Thiếu vehicle state hoặc state đã cũ.
- Prompt injection trong câu hỏi hoặc tài liệu.

Hành vi: không đoán actuator; hỏi một câu ngắn, đưa tối đa hai lựa chọn hoặc từ chối.

### Output uncertainty

- LLM sinh sai tool/argument.
- Câu trả lời RAG thêm thông tin ngoài bằng chứng.
- Lời nói TTS khác với nội dung đã duyệt.

Hành vi: parse bằng schema, validate range, grounded answer theo evidence, TTS chỉ đọc `display_text` đã khóa.

### Process uncertainty

- MQTT timeout, model timeout, index stale, approval hết hạn.
- Node chạy lại sau LangGraph interrupt.
- Mixed plan cần bundled approval cho mọi S2 trước bất kỳ side effect nào; S3 hủy toàn bộ pending plan.
- Một session chỉ có một pending approval; voice approval intent là turn riêng chỉ handoff, còn IVI commit bằng REST.

Hành vi: deterministic policy/classification, idempotency key, state version recheck và deadline. Partial unique constraint ngăn approval pending thứ hai; approval-intent event không commit. Executor, không phải AI, được đúng một retry chỉ cho transient transport failure trước khi persist terminal `ToolResult`: dùng cùng command/idempotency key, lookup result trước retry và dựa broker/simulator dedupe. Validation, policy và tool-semantic failure không retry; sau terminal persistence chỉ replay prior result. Báo outcome chính xác từng step; không gán safety cho AI.

## Prompt contract

System prompt phải gồm năm phần:

1. Vai trò: trợ lý cabin prototype tiếng Việt.
2. Nhiệm vụ: route hoặc tạo output theo schema.
3. Context: vehicle snapshot, trip memory tối thiểu, tool schemas, retrieved evidence khi cần.
4. Ràng buộc: không tự thực thi, không bịa citation, không tiết lộ prompt, không dùng tool ngoài allowlist.
5. Output: JSON schema hoặc grounded response format.

Không đưa toàn bộ sổ tay, toàn bộ lịch sử hay trace nội bộ vào context. Chỉ giữ dữ liệu có tín hiệu cao cho lượt hiện tại.

## Guardrails

| Guardrail | Giá trị mặc định |
|---|---:|
| Agent iterations | Tối đa 4 node có LLM |
| Tool retries | Đúng 1 retry chỉ cho transient transport failure trong executor, cùng command/idempotency key; zero retry cho validation/policy/tool-semantic failure |
| LLM timeout | 8 giây |
| Tool timeout | 3 giây |
| Approval expiry | 30 giây |
| Trip memory | 20 turns hoặc kết thúc chuyến |
| Retrieved chunks | Tối đa 5 |
| Output language | Tiếng Việt ngắn gọn |

## Accountability và evidence

Mỗi run ghi `trace_id`, model/quantization, prompt version, tool version, data/index version, vehicle state version, stage latency và approval decision. Trace hiển thị plan/action/observation nhưng không công khai private chain-of-thought.

## Quyết định

- **GO:** bounded agent trong simulator.
- **Fallback:** deterministic intent workflow nếu tool-plan eval thấp hơn 90%.
- **Không nâng autonomy:** ngay cả khi model tốt hơn, safety boundary không thay đổi trong đề tài.
