# Product Brief: VIVI Cabin Copilot

## Tóm tắt một câu

Tài xế hiện phải phụ thuộc kết nối mạng hoặc thao tác màn hình để dùng trợ lý cabin, gây gián đoạn và tăng thời gian rời mắt khỏi đường; VIVI Cabin Copilot sẽ chứng minh một trải nghiệm tiếng Việt offline, grounded và có kiểm soát an toàn trên digital twin, không kết nối xe thật.

## Bối cảnh và bằng chứng

VIVI 2.0 được VinBigdata mô tả là trợ lý GenAI có hội thoại tự nhiên, điều khiển xe, thông tin–giải trí, chỉ đường và ghi nhớ thói quen. Trang hướng dẫn tương tác hiện yêu cầu kết nối Internet. Đề tài tập trung vào khoảng trống nghiên cứu: duy trì các tác vụ cabin cốt lõi khi mất mạng bằng SLM lượng tử hóa trên edge.

Nguồn:

- [VIVI 2.0 — hướng dẫn và năng lực](https://vivi.vinbigdata.com/)
- [VIVI — nhóm tính năng và cá nhân hóa](https://vinbigdata.com/vinbase/vivi)
- [VIVI trên ô tô điện VinFast](https://vinbigdata.com/case-study/tro-ly-ao-vivi-mang-den-trai-nghiem-thoai-mai-va-ly-thu-tren-o-to-dien-vf-e34.html)

Các số đo baseline nội bộ như latency, intent accuracy và task completion chưa có ở thời điểm lập kế hoạch. Tuần 1 sẽ tạo baseline để so sánh; không dùng số marketing của sản phẩm thương mại làm baseline cho prototype.

## Người dùng mục tiêu

| Người dùng | Ngữ cảnh | Nỗi đau | Cách xử lý hiện tại | Thành công trông như thế nào |
|---|---|---|---|---|
| Tài xế | Đang di chuyển hoặc đi qua vùng mạng yếu | Trợ lý gián đoạn, phải chạm màn hình, không biết câu trả lời có đúng sổ tay không | Chờ có mạng, tự tìm menu hoặc đọc PDF | Hoàn thành tác vụ bằng giọng nói, phản hồi nhanh, biết rõ khi nào hệ thống không chắc |
| Kỹ sư hệ thống | Kiểm thử IVI/edge | Khó biết stage nào chậm hoặc tool nào sai | Xem log rời rạc | Có trace, latency breakdown, model/data version và replay case |
| Người đánh giá/demo | Chấm tính hoàn thiện | Demo AI thường chỉ có happy path | Xem một số lệnh chuẩn bị trước | Thấy offline proof, lỗi an toàn, citation và evidence định lượng |

## Current workflow

1. Tài xế gọi trợ lý hoặc tìm chức năng trên màn hình.
2. Âm thanh/ý định được xử lý qua dịch vụ phụ thuộc kết nối.
3. Nếu mạng yếu, người dùng thử lại hoặc thao tác tay.
4. Với câu hỏi kỹ thuật xe, người dùng tìm sổ tay hoặc tin vào câu trả lời khó kiểm chứng.
5. Với nhiều tác vụ, người dùng phải lặp lại từng lệnh.

## Bottleneck và tác động

| Bottleneck | Baseline ban đầu | Tác động | Ưu tiên |
|---|---|---|---|
| Phụ thuộc mạng | Chưa đo; xác lập bằng offline drill | Mất khả năng phục vụ | P0 |
| Độ trễ không phân rã | Không có trace nội bộ | Không biết tối ưu stage nào | P0 |
| Điều khiển thiếu boundary | Không có policy prototype | Rủi ro thực thi sai | P0 |
| Trả lời sổ tay không grounded | Chưa có eval set | Giảm niềm tin | P0 |
| Tác vụ nhiều bước | Phải nói nhiều lệnh | Tăng tải nhận thức | P0 cho headline known pattern; mở rộng P1 |

## Product hypothesis

Nếu tài xế có thể dùng giọng nói tiếng Việt để hoàn thành các tác vụ cabin cốt lõi trong chế độ offline, với citation và xác nhận rõ ràng, thì task completion sẽ đạt ít nhất 80%, happy path cần tối đa một lần chạm và người dùng sẽ tin tưởng hơn so với một chatbot không có bằng chứng/policy.

Safety source: [ADR-006](adr/ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md) và [Safety and Human-in-the-Loop Specification](safety_and_hitl.md).

## Scope

### P0 — cam kết

- Hai vai trò và local RBAC.
- Text + push-to-talk tiếng Việt.
- Runtime offline sau khi tải model.
- Tools mô phỏng HVAC, ghế, media, cửa/kính, navigation.
- Known P0 multi-intent gồm local `search_nearby_poi` → HVAC → navigation với dependency typed; POI có exactly-one observable/effectively-once persisted outcome trước admission và empty result không tạo side effect.
- Control, Knowledge/RAG và Safety là logical subgraphs/modules trong cùng P0 `backend`, không phải autonomous hay separately deployable agents.
- MQTT digital twin và state observation.
- RAG sổ tay có citation tới tài liệu/mục/trang/`chunk_id` và bounded excerpt được chunk hỗ trợ.
- Deterministic policy cho mọi action; HITL cho S2; S3 bị chặn.
- Tối đa một pending approval/session; voice approval intent chỉ handoff để IVI commit qua REST, và invalidation không tạo side effect.
- Low-confidence clarification và error recovery.
- Safe Engineer aggregates cho stage latency, model tokens/s + RSS/profile, MQTT, groundedness/abstention, safety/approval và action audit; full trace/eval/model config là authorized/audited CLI/P1.
- Golden eval, Docker và CI.
- Hai vòng user research là evidence bắt buộc cho Verified P0 trong Week 4.

### P1 — cam kết

- Mở rộng multi-step ngoài các pattern P0 đã biết và tăng coverage cho yêu cầu hiếm/mơ hồ.
- Trip-scoped memory.
- Q4/Q8 benchmark trên cùng hardware profile.
- Tách Control/Knowledge/Safety thành separately deployable multi-agent services chỉ khi benchmark/isolation need chứng minh lợi ích; P0 vẫn giữ logical subgraphs trong modular monolith.

### P2 — stretch sau quality gate tuần 2

- Fleet dashboard nhiều xe mô phỏng.
- OTA model/config rollout và rollback mô phỏng.
- Wake word.
- Bản đồ offline giàu tương tác.

### Out of scope

- CAN hoặc xe thật.
- Chứng nhận an toàn ô tô.
- Đặt chỗ, thanh toán hoặc gọi điện thật.
- Dẫn đường turn-by-turn ngoài đời thực.
- Cloud là dependency bắt buộc.
- Fine-tune model trong bốn tuần.

## Use case ưu tiên

1. “Trong xe nóng quá.” → đề xuất HVAC S1, policy validate và thay đổi simulator.
2. “Tìm cà phê gần đây, đặt điều hòa 24 độ rồi dẫn đường.” → lập kế hoạch nhiều bước.
3. “Đèn cảnh báo áp suất lốp nghĩa là gì?” → câu trả lời grounded và citation.
4. “Mở cửa bên trái.” khi tốc độ lớn hơn 0 → policy từ chối.
5. Transcript confidence thấp → đọc lại điều hệ thống nghe được và hỏi ngắn gọn.

## Success metrics

| Metric | Baseline | Target | Cách đo |
|---|---:|---:|---|
| Intent macro-F1 | Đo tuần 1 | ≥ 0,90 | Golden text set |
| Tool + required arguments exact match | Đo tuần 1 | ≥ 90% | Planned vs expected action |
| Unauthorized actuator execution | 0 được chấp nhận | 0 | Safety suite và audit log |
| RAG citation validity | Đo tuần 1 | 100% | Citation resolver |
| RAG faithfulness | Đo tuần 1 | ≥ 95% | Evidence rubric |
| Offline P0 completion | 0 trước prototype | 100% | Network-disabled drill |
| End-of-speech → first audio p50 | Đo tuần 1 | ≤ 2.500 ms | Trace timestamps |
| End-of-speech → first audio p95 | Đo tuần 1 | ≤ 4.500 ms | Trace timestamps |
| User task completion | Vòng 1 formative, không dùng làm release baseline | ≥ 80% ở vòng 2 | Moderated integrated-offline test |
| Screen touches trên happy path | Vòng 1 khám phá workflow | ≤ 1 median ở vòng 2 | Observation |
| Critical approval/refusal comprehension | Đo formative vòng 1 | 100% observed tasks ở vòng 2 | Teach-back + task outcome |

## Go / Not Yet / No-Go

- **GO:** prototype offline trên PC/laptop với Docker resource limits.
- **NOT YET:** kết nối CAN, xe thật hoặc tuyên bố production safety.
- **NO-GO condition:** nếu đến cuối tuần 2 còn bất kỳ side effect nào bỏ qua policy hoặc bất kỳ S2 nào bỏ qua HITL, khóa P2 và chuyển toàn bộ nguồn lực sang reliability.

## User-research contract

| Round | Allocation/reuse | Focus and tasks | Measures/evidence | Exit/product gate |
|---|---|---|---|---|
| Round 1 — formative, end W2/start W3 | 4–5 participants | Prototype/workflow/speech/HITL: HVAC, coffee multi-step, citation, stationary window, moving-door refusal | Expected behavior, wording, taps/repetitions, comprehension, anonymized notes; separate consent/script/raw-measure/synthesis/decision artifacts | Chốt top ba product changes trước feature freeze; không dùng vòng này để claim integrated/offline target |
| Round 2 — confirmatory, W4 | 5–6 participants; max 2 returners, at least 3 new; total 7–9 unique | Integrated offline usability/safety plus low-confidence, approval invalidation and dependency recovery | Completion/time/taps, comprehension, trust/recovery, simulator/audit transition; separate evidence set and change log | ≥80% completion, median happy-path taps ≤1, critical approval/refusal comprehension 100%, zero unauthorized transition, no open research blocker |

Round metrics are reported separately. Returning participants are labeled only for learnability comparison; raw audio is deleted unless they explicitly opt in.

## Giả định đã chốt

- Nhóm có bốn người và bốn tuần, ưu tiên vibecode có review/test.
- Không có Jetson; CPU profile trong Docker là baseline edge mô phỏng.
- Manual và POI chạy cục bộ; dữ liệu phải có quyền sử dụng.
- UI sử dụng push-to-talk cho P0; wake word là P2.
- Raw audio không được lưu mặc định.
