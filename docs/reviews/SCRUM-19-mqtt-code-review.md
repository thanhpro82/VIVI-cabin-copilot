# SCRUM-19 — Trả lời code review MQTT

> Ghi lại kết quả kiểm chứng ba phát hiện của code review trên PR MQTT, và
> những gì đã sửa. Mục đích là để người sau không đi "sửa" thứ vốn không hỏng,
> và biết vì sao hai chỗ khác lại được sửa dù review không nêu.

**Kết luận ngắn: không phát hiện nào đúng như mô tả.** Nhưng hai trong ba chỉ
đúng *cơ chế*, và đi theo cơ chế đó thì tìm ra hai lỗi thật ở chỗ khác. Cả hai
đã sửa.

| # | Phát hiện | Kết luận | Hành động |
|---|---|---|---|
| F1 | State mutation ở `_neutral_seat` / `initial_state` | **Không phải bug** | Không đổi. Nhưng cơ chế đúng → dẫn tới **B1** |
| F2 | Resource leak ở `AiomqttClient.abort` | **Đúng một phần, mức thấp** | **B3** — đổi tên, làm rõ hợp đồng |
| F3 | Race condition ở `_publish_and_wait` | **Không phải bug** | Không đổi. Nhưng dẫn tới **B2** |

---

## F1 — State mutation ở `_neutral_seat`

**Review nói:** *"Pydantic models are mutable. If `_neutral_seat` returns a
reference to a pre-defined object or if the deep copy logic in snapshot is
bypassed elsewhere, concurrent modifications to seat positions could leak
across instances."*

**Kết luận: không phải bug.** `_neutral_seat()` gọi constructor
`SingleSeatState(...)` nên tạo instance mới mỗi lần, không trả về object dựng
sẵn. Và `snapshot()` có deep copy thật.

Kiểm chứng:

```
hai ghe co cung object khong : False
sua ghe trai -> ghe phai      : 50   (khong bi anh huong)
snapshot() co deep copy khong : deep copy OK
```

Đây từng **là** bug thật và đã sửa trước khi commit: bản đầu tiên gán cùng một
`SingleSeatState` cho cả hai ghế. Test
`test_seat_heating_va_seat_position_deu_ghi_vao_domain_seat` chính là thứ bắt
được nó. Đã bổ sung thêm `test_hai_ghe_khong_dung_chung_object` để khẳng định
bất biến này một cách trực tiếp thay vì gián tiếp.

### Nhưng cơ chế review nêu là đúng, và có lỗ thật ở chỗ khác

Pydantic **thật sự không** copy model lồng nhau. Kiểm chứng:

```
truyen chung 1 object cho ca hai ghe -> sua ghe trai:  ghe phai = 99
```

Đi theo đó thì tìm ra: `VehicleSimulator.__init__` giữ `VehicleState` của
caller **theo tham chiếu**, không copy.

```
st = initial_state('v2')
a = VehicleSimulator('v2', st); b = VehicleSimulator('v2', st)
a.state.hvac.temperature_c = 20   ->  b.state.hvac.temperature_c == 20.0
```

**Đã sửa (B1):** `model_copy(deep=True)` trong `__init__`, đúng như `snapshot()`
vẫn làm. Test mới: `test_hai_simulator_khoi_tao_tu_cung_state_phai_doc_lap`.

---

## F2 — Resource leak ở `AiomqttClient.abort`

**Review nói:** *"the socket is shut down but the underlying paho-mqtt client
and its internal loop/threads might not be fully cleaned up… This is
specifically used in tests but could cause issues if used in a long-running
simulator process."*

**Kết luận: đúng một phần, mức độ thấp.** `abort()` được gọi từ **0 chỗ trong
`src/`** — chỉ contract test dùng, nên kịch bản "long-running simulator
process" không tồn tại hôm nay. Nhưng nó vẫn là public method trên class
production và teardown thật sự không sạch: huỷ context giữa chừng để lại vài
task nội bộ của aiomqtt, asyncio cảnh báo `Task was destroyed but it is
pending`.

**Đã sửa (B3): đổi tên `abort()` → `simulate_connection_loss()`**, docstring
nói thẳng đây là hook fault injection và không gọi trong đường chạy thật, kèm
ghi rõ hạn chế pending task.

**Không chuyển hẳn sang test.** ADR-004 chọn MQTT một phần vì *"hỗ trợ fault
injection"* — có hook cắt kết nối là thiết kế hợp lệ, không phải rác test rò
vào production. Và không có cách nào khác kiểm được Last Will: `stop()` đóng
context sạch nên gửi DISCONNECT, mà theo đặc tả MQTT thì DISCONNECT sạch khiến
broker **huỷ** Will thay vì phát nó.

Cũng không vá cảnh báo pending task bằng cách đụng vào private của aiomqtt —
ghi vào docstring như hạn chế đã biết thì trung thực hơn.

---

## F3 — Race condition ở `_publish_and_wait`

**Review nói:** *"if the MQTT broker is extremely fast… `_on_event` might be
called before `await asyncio.wait_for(waiter, …)` starts… The more critical
concern is that `_waiters` is a simple dict; if multiple commands with the same
`command_id` were somehow generated, they would overwrite each other."*

**Kết luận: không phải bug**, cả hai vế.

- **Thứ tự đúng rồi.** Waiter được đăng ký **trước** khi publish (đó là lý do
  có comment ở dòng đó). Broker nhanh đến mấy thì `set_result` trên một future
  đã tồn tại vẫn an toàn — chính review cũng thừa nhận điểm này.
- **Va chạm `command_id` không phải mối lo thực tế.** Nó là
  `uuid4().hex[:20]` — 80 bit. Và `_waiters` được pop trong `finally` nên cửa
  sổ va chạm chỉ kéo dài đúng một lần `execute()`.

### Một điểm cần nói rõ là *cố ý*, không phải lỗi

Khi retry, `command_id` được **giữ nguyên** theo đúng `data_model.md`. Nếu event
của lần thử đầu về muộn trong lúc lần hai đang chờ, waiter lần hai sẽ nhận
event đó — và điều này **đúng**: cùng `command_id` nên simulator đã dedupe,
event hợp lệ với cả hai lần thử.

### Nhưng có lỗi thật ở dạng tổng quát hơn

Không phải `_waiters` (đã pop trong `finally`), mà là `_results`:

- `VehicleSimulator._results` — key là `command_id`, **không bao giờ xoá**
- `ToolExecutor._results` — key là `idempotency_key`, cũng **không bao giờ xoá**

Process chạy lâu tích luỹ mọi lệnh từng nhận. Đây là rò bộ nhớ thật.

**Đã sửa (B2):** thêm `src/bounded_cache.py` — LRU có trần 1024, dùng cho cả
hai phía.

**Chế độ hỏng khi evict, ghi rõ để không ai phải đoán:**

- *Phía simulator:* một `command_id` bị đẩy ra rồi quay lại thì lệnh sẽ chạy
  lại. Lúc đó `expected_state_version` gần như chắc chắn đã cũ nên bị chặn bằng
  `stale_state`.
- *Phía executor:* replay cùng `plan_id:step_id` sau khi entry bị đẩy ra sẽ sinh
  `command_id` **mới**, nên simulator không dedupe được — nó thấy đây là lệnh
  lạ. Thứ chặn transition kép lúc đó **chỉ có** `expected_state_version`.

Điểm thứ hai là lý do version check là bắt buộc chứ không phải tuỳ chọn. Trần
1024 đủ lớn để một phiên demo không bao giờ chạm tới.

---

## Tổng kết thay đổi

| Mã | Nội dung | File |
|---|---|---|
| B1 | Deep-copy state trong `VehicleSimulator.__init__` | `src/vehicle_sim/state.py` |
| B2 | `BoundedCache` thay `dict` vô hạn ở cả hai phía | `src/bounded_cache.py`, `src/vehicle_sim/state.py`, `src/services/tool_executor.py` |
| B3 | `abort()` → `simulate_connection_loss()` | `src/services/mqtt_client.py` |

Test tăng từ **110 → 121**. Bổ sung:

- `test_hai_ghe_khong_dung_chung_object`
- `test_hai_simulator_khoi_tao_tu_cung_state_phai_doc_lap`
- `test_cache_idempotency_co_tran_va_day_ra_ban_cu_nhat`
- `test_trong_tran_thi_idempotency_van_nguyen_ven`
- `test_executor_cache_ket_qua_co_tran`
- `tests/test_vehicle/test_bounded_cache.py` (6 test)

Sau khi sửa: ruff sạch, 121 pass + 5 skip, 5 contract test trên Mosquitto thật
vẫn pass, schema + crosscheck đạt, `scripts/smoke_mqtt.py` vẫn đủ 3 acceptance
criteria.
