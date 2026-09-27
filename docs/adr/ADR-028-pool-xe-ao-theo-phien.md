# ADR-028: pool xe ảo có hạn, cấp cho từng phiên tài xế

- Status: Proposed — chờ @thanhpro82 (PM/PO)
- Date: 2026-08-23
- Decision owner: WS3 Virtual Vehicle & Router (Sơn)
- Giữ nguyên: [ADR-013](ADR-013-single-vehicle-state-source.md) (một nguồn trạng thái xe),
  [ADR-006](ADR-006-p0-modular-monolith-deterministic-routing-calibrated-hitl.md) /
  [ADR-010](ADR-010-canonical-tool-registry-with-product-vision-adapter.md) (luật đi trước),
  [ADR-014](ADR-014-ws-ivi-event-replay-and-retention.md) (thứ tự stream tài xế)
- Liên quan: [ADR-024](ADR-024-kenh-harness-dieu-khien-xe-ao.md) (kênh harness),
  `docs/api_spec.md`, `docs/mqtt_spec.md`
- Bằng chứng: `eval/results/slm-dong-thoi/20260823T120422.023604Z`,
  `eval/results/ram-nhieu-xe/20260823T102102.401634Z`,
  `eval/results/ram-phien-backend/20260823T103405.963369Z`

## Context

`vehicle_id` là một hằng số (`src/config.py`), nên **mọi người dùng chung đúng một chiếc
xe ảo**. Với một người ngồi trước máy thì không ai nhận ra. Với bản deploy công khai thì
nó không phải bất tiện mà là lỗi: cơ chế chống ghi đè theo `state_version` — vốn sinh ra
để bảo vệ một người khỏi chính mình — bị kích hoạt liên tục bởi người khác.

Ba đường hỏng, cả ba đều đã quan sát được:

| Đường | Nơi phát sinh | Người dùng thấy |
|---|---|---|
| Kế hoạch nhiều bước bị cắt giữa chừng | `nodes/execute.py` → `skipped_external_state_change` | "Lệnh chạy nửa chừng rồi thôi" |
| Phê duyệt HITL bị vô hiệu | `nodes/approval.py` → `approval_invalidated_state` | "Bấm Đồng ý mà báo xe không còn an toàn" |
| UI cả phòng bị siết | `ui_policy.py` phát `broadcast` tới **mọi** phiên | Khoá ô nhập text của người không liên quan |

Chẩn đoán ban đầu — "do mọi người dùng chung tài khoản `usr_driver_01`" — **sai về nguyên
nhân**. Mỗi trình duyệt đã có `session_id` riêng và event WS đã đẩy theo phiên. Cấp tài
khoản riêng cho từng người **không sinh ra chiếc xe thứ hai**, nên nó không sửa được gì ở
đây (nó vẫn đáng làm, vì lý do khác: truy vết và phân quyền).

## Vì sao pool **có hạn**, không phải mỗi phiên một xe

RAM không phải ràng buộc. Đo được **13 KB mỗi xe ảo** và **512 KB mỗi phiên backend**, tức
100 người đồng thời tốn ~53 MB — hai bậc độ lớn dưới chỗ trống của máy.

Ràng buộc nằm ở chỗ khác, và nó cứng hơn nhiều:

- **llama-server bão hoà quanh 3 lượt đồng thời.** Đo được: classify ở trần 3,5 s có
  0/6 lượt vượt ở N=2 nhưng **9/9 vượt ở N=3**; tải hỗn hợp còn tốt ở N=3 (0/9) và **vỡ
  hoàn toàn ở N=5**. Bốn rãnh của llama-server dùng chung một năng lực tính toán, không
  nhân nó lên.
- **STT và TTS có khoá toàn cục** (`voice.py`, `num_threads=1`) — mỗi lúc một người.

Cấp xe không giới hạn nghĩa là không có chỗ nào chặn việc một người chiếm sạch tài nguyên,
trong khi tài nguyên thật sự khan hiếm lại không phải chiếc xe. **Trần 3 là con số đo
được, không phải chọn cho tròn.**

## Decision

**1. Pool id cố định, `vehicle_id` là ô số 0.** `vehicle-demo-01` luôn được cấp trước
tiên, nên một người dùng duy nhất rơi đúng vào chiếc xe mà màn kỹ sư,
`probe_vehicle_simulator`, healthcheck của `docker-compose` và toàn bộ tài liệu đang trỏ
tới. Các ô còn lại là `vivi-xe-02`…

**2. `vehicle_pool_size = 1` nghĩa là KHÔNG cấp phát**, và đó là mặc định của repo. Với
đúng một chiếc xe thì không có gì để phân phối; bật cấp phát lên chỉ tạo ra một hệ quả
duy nhất là người thứ hai bị đẩy sang chế độ chỉ xem — **tệ hơn** hành vi hôm nay (mọi
người dùng chung, va nhau nhưng ai cũng lái được). Đây là ngoại lệ có chủ đích: nó giữ cho
việc merge không đổi hành vi của bất kỳ ai, và bật nhiều xe là lựa chọn tường minh của
người vận hành.

**3. Thuê có hạn, hết hạn phát hiện lúc đọc.** Người dùng đóng tab không báo cho server,
nên không có TTL thì mỗi lượt khách ghé qua là một chiếc xe mất vĩnh viễn. Gia hạn xảy ra
ở `session_state._touch()` — hàm đã được gọi ở mọi đường vào. Không có tác vụ nền quét,
cùng khuôn với `approval.py` và `get_session_record`: xe chỉ cần rảnh **vào lúc có người
hỏi xin**.

**4. Hết pool KHÔNG phải lỗi.** Phiên vẫn được tạo — một phiên không phải một chiếc xe —
và vào chế độ chỉ xem: vẫn tra sổ tay, vẫn đọc trạng thái xe, chỉ lệnh điều khiển bị từ
chối với `vehicle_pool_exhausted`. Với trần 3, quá tải là chuyện **chắc chắn xảy ra**, nên
đường lui này là một phần của thiết kế chứ không phải nhánh phòng xa.

**5. Chặn lệnh ở CỔNG, không ở từng cửa nhận lệnh.** Lệnh vào hệ qua bốn cửa
(`/turns/text`, `/turns/voice`, resume sau HITL, kênh harness `/sim/motion`). Chặn ở từng
cửa nghĩa là bốn chỗ phải cùng nhớ một luật, và cửa thứ năm mọc lên sau này sẽ quên.
`ChiXemVehicleGateway` bọc cổng lại: đọc được, `execute()` bị từ chối — không có đường đi
vòng.

**6. Sức chứa có đúng một nguồn.** `VehiclePool.suc_chua()`. Màn tài xế, màn kỹ sư và
`POST /sessions` đều đọc từ đó. Cùng kỷ luật một-nguồn-sự-thật mà ADR-013 đặt cho trạng
thái xe: hai chỗ tự đếm là hai chỗ sẽ lệch nhau, và lúc đó không ai biết chỗ nào đúng.

## Vì sao điều này KHÔNG phá ADR-013

ADR-013 nói: **snapshot do simulator công bố là nguồn trạng thái xe duy nhất**, backend chỉ
forward, không map lại, không tự suy.

Điều đó **giữ nguyên từng chữ**. Mỗi chiếc xe trong pool vẫn có đúng một nguồn: simulator
của chính nó. Backend vẫn chỉ forward. Thứ đổi là phạm vi của chữ "một": từ *một chiếc xe
cho cả hệ thống* thành *một chiếc xe cho mỗi phiên*.

Ba hệ quả cụ thể của việc giữ nguyên ADR-013:

- Mỗi xe ảo giữ **kết nối MQTT riêng**, dù backend thì gộp K runtime vào một kết nối. Last
  Will gắn theo *kết nối*: gộp K xe vào một client nghĩa là cả đội chỉ có một di chúc, nên
  khi tiến trình chết thì đúng một chiếc được báo offline còn K−1 chiếc kia nằm im với
  retained health `online=true`. Mất khả năng phát hiện từng xe chết là mất đúng thứ cặp
  Birth+LWT sinh ra để có.
- Backend **buộc phải** gộp, vì lý do ngược lại: `MqttRuntime.start()` dùng
  `client_id="vivi-backend"` cố định, nên K kết nối là K client trùng id và broker đá lần
  lượt từng cái ra. `MqttRuntime.bind()` vốn được tách khỏi `start()` cho đúng kiểu dùng này.
- ACL **không phải sửa**: `config/mosquitto/acl` đã dùng wildcard `v1/vehicles/+/...`.

## Consequences

**Được**

- Ba đường hỏng ở phần Context biến mất giữa những người dùng khác nhau.
- `ui.policy` phát đúng người: xe A lăn bánh không còn siết giao diện của người đang lái
  xe B — và quan trọng hơn theo chiều ngược lại, không **nới** giao diện của người đang chạy.
- Có một con số trần để nói cho người xem demo (`pool` trong `POST /sessions`).

**Mất / phải chấp nhận**

- **B không sửa được thông lượng.** Sau ADR này, nhiều người vẫn xếp hàng ở SLM/STT/TTS.
  Nó đổi *lệnh hỏng* thành *chờ lâu* — cải thiện thật, nhưng đừng mô tả là "giải quyết
  chuyện đồng thời".
- **Đổi hợp đồng `GET /vehicle/state`**: thêm auth và tham số `session_id`. Frontend phải
  cập nhật trước khi bật pool, nếu không nó nhận `400`.
- **Quyền lái không đổi giữa chừng một cuộc hội thoại.** Cổng chốt vào graph ở lần dựng
  đầu, mà graph sống theo phiên. Một phiên bắt đầu ở chế độ chỉ xem giữ nguyên chế độ đó
  tới khi graph bị đuổi khỏi `_GRAPHS`. Chấp nhận được, và dễ hiểu hơn phương án ngược lại.
- **Console gõ tay chỉ lái ô số 0.** Nó là một kênh stdin duy nhất; thêm cú pháp chọn xe
  là mở rộng một bề mặt gõ tay mà chỉ người trình bày dùng.
- **Không chạy được trên hai worker.** Bảng thuê nằm trong bộ nhớ tiến trình. Nhưng
  `InMemorySaver` và kết nối SQLite đơn đã giả định như vậy từ trước, nên đây không phải
  ràng buộc mới.
- **Màn kỹ sư vẫn chỉ nhìn ô số 0.** Bảng đội xe là hạng mục riêng, quyết sau.

## Cách kiểm

Nghiệm thu quyết định là thủ công và không thay thế được bằng test: **hai trình duyệt khác
nhau, cùng lúc, mỗi bên ra một lệnh S1.** Trước ADR này một bên nhận
`skipped_external_state_change`; sau ADR này cả hai hoàn tất, và `ui.policy` của bên này
không siết giao diện bên kia.

Ngoài ra: `vehicle_pool_size = 1` phải cho hành vi **y hệt** bản chưa có pool — đây là lưới
an toàn để merge, và có test khoá từng phần của nó.
