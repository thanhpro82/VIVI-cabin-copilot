# Demo Scope

## Mục tiêu

Tài liệu này chốt phạm vi demo bắt buộc và người chịu trách nhiệm cho từng
luồng. Đây là scope demo, không phải cam kết release hay danh sách toàn bộ
tính năng đã merge.

Demo chỉ bắt đầu khi `GET /healthz` trả `status: ready` cho các dependency bắt
buộc, Driver đăng nhập được, MQTT/simulator đang chạy và trình duyệt nối được
WebSocket `/ws/ivi`.

## Mandatory flows

| Flow | Owner chịu trách nhiệm | Kịch bản demo | Evidence đạt | Gate trước demo |
|---|---|---|---|---|
| S1 voice command | Sơn | Xe dừng, nói “Bật điều hòa 24 độ”, rồi “chỉnh quạt gió mức 2”. | Transcript cuối, policy S1, `tool.result=completed`, state simulator đổi và `assistant.response`/TTS. Mức quạt trên UI đổi theo. | Không cần approval. Quạt gió (`set_hvac_fan_level`, PR #92) được phép dùng; đèn và cốp thì không — xem mục PR #92. |
| S2 approval | Nhân | Xe dừng, gear P; nói “Mở kính bên lái 30%”, xem approval card, rồi approve. | `approval.required`, decision REST, `tool.result=completed`, state version thay đổi đúng một lần. | Không approve bằng việc đóng popup hay mất WebSocket; state stale phải không thực thi. |
| RAG + TTS | Nhân | Hỏi một câu có evidence trong sổ tay VF9. | `assistant.response` có citation/section/page; `assistant.speech` phát được qua loa; câu không có evidence trả grounded refusal. | RAG index/manifest hợp lệ; không đọc câu trả lời từ trí nhớ khi không có evidence. |
| WebSocket recovery | Giáp | Khi UI đang nhận policy mở, ngắt socket rồi để client reconnect. | UI khóa ngay khi mất socket; reconnect gửi replay cursor; policy mới từ backend mới được phép mở lại UI. | ✅ Đã thoả — PR #100 merge `726ee2e`, gồm cả fail-closed cho lỗi terminal `AUTH_REQUIRED`/`FORBIDDEN` (`bbb00cc`). |
| Driver UI | Giáp | Driver dùng mic, thấy transcript/trạng thái, approval card và kết quả lệnh. | Text trạng thái vẫn readable, mic/overlay không che điều khiển sai policy, approval card hiện đúng. | ✅ Đã thoả — stack FE merge đủ: #100 `726ee2e` → #101 `746b223` → #102 `e93a590` → #110 `4d9cd1f`; recorder bị hủy khi đóng overlay (`3956767`). |

## PR #92 decision

**PR #92 — In-scope một phần: quạt gió vào demo, đèn và cốp deferred.**

PR #92 (merge `3c60331`) đã nối trọn chuỗi ở backend — `tool_registry` → args
schema (`tools/lights.py`, `tools/trunk.py`) → `policy` (cốp là S2 với
`requires_stationary`) → `router` (`_match_lights`, `_match_trunk`,
`_match_hvac_compound`) → executor trong `vehicle_sim/state.py` →
`models/vehicle.py` — kèm ADR-019, ADR-020 và test ở router, policy, simulator
và tầng L3. Defer toàn bộ với lý do "chưa có test riêng" là sai thực tế.

Ranh giới thật nằm ở Driver UI, vì demo được chấm qua màn hình:

| Tool của #92 | Quyết định | Cơ sở |
|---|---|---|
| `set_hvac_fan_level` | **In-scope**, gộp vào flow S1 | `real.ts:73` đã map `raw.hvac.fan_level` và `VehicleControlView.tsx:246-261` vẽ 4 mức — lệnh đổi state và UI phản ánh ngay. |
| `set_trunk_state` | **Deferred** | `real.ts:105` hard-code `trunk: "closed"`, chưa đọc `raw.trunk.position`. Lệnh chạy đúng nhưng UI đứng yên. |
| `set_headlight_mode`, `set_interior_light` | **Deferred** | Cùng lỗi map (`real.ts:103` hard-code `lights: false`), **và** nút ở `VehicleControlView.tsx:277` gửi `"tắt đèn pha"` trong khi `router.py:601` từ chối `headlight_off_not_permitted` theo ADR-020 (enum `headlight` cố ý không có `off`). Toggle hai trạng thái sai mô hình, phải đổi thành chọn chế độ. |

Hai comment "BE chưa gửi field lights/trunk" trong `real.ts:102-105` và
`turn/types.ts` đã lỗi thời kể từ #92 — `VehicleState` có `LightsState` và
`TrunkState` thật. Sửa chúng là điều kiện gỡ deferral, không phải việc phát sinh.

Không được dùng sự hiện diện của #92 để tuyên bố một demo flow đã đạt.

## Trình tự chạy demo

1. Preflight: kiểm `/healthz`, driver session, MQTT/simulator và WebSocket.
2. Chạy S1 voice command.
3. Chạy S2 approval khi xe dừng, gear P.
4. Chạy RAG + TTS, bao gồm một grounded refusal.
5. Chạy WebSocket recovery trong trạng thái UI đang mở rồi xác nhận fail-closed.
6. Chạy smoke Driver UI cho mic, transcript, approval card và kết quả.

Mỗi owner xác nhận flow của mình trước khi demo. Nếu một gate không đạt, bỏ
flow đó khỏi buổi demo thay vì dùng dữ liệu/claim thay thế.

## Out of scope

- S3 action khi xe đang chạy.
- SLM sentence selection và tính năng “Nghe tiếp” S1/S3 đang được tách từ PR #108.
- Đèn (`set_headlight_mode`, `set_interior_light`) và cốp (`set_trunk_state`)
  của PR #92 — lý do ở mục trên. Quạt gió **không** thuộc mục này.
- Bất kỳ claim nào dựa trên deploy, cloud service hoặc xe thật.
