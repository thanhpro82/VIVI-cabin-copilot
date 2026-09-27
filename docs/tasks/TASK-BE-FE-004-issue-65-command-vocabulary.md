# TASK-BE-FE-004 — Vốn từ lệnh sau issue #65: FE phải đổi 2 chỗ

> Chiều ngược của [`TASK-FE-BE-002`](TASK-FE-BE-002-real-mode-control-gaps.md): lần đó FE báo BE
> những gì router thiếu; lần này BE báo FE những câu lệnh nào đã đổi.
>
> Người nhận: Giáp (WS4 frontend). Người gửi: Sơn (WS3). Ngày: 2026-08-12.

## Tóm tắt

Issue #65 nối 5 tính năng FE đã dựng UI nhưng router chưa xử lý. **Ba nút giờ chạy được mà FE
không phải sửa gì.** Hai nút còn lại **phải đổi câu gửi lên**, vì router cố ý không đoán.

Đối chiếu trực tiếp với `frontend/src/components/ivi/VehicleControlView.tsx` và `MusicView.tsx`
trên `develop` tại thời điểm viết.

## 1. Chạy được ngay, FE không phải sửa

| Nút | File | Câu FE gửi | Kết quả mới |
|---|---|---|---|
| Bài trước | `MusicView.tsx:90` | `"bài trước"` | `media_control {action: "previous"}` |
| Bài tiếp | `MusicView.tsx:109` | `"chuyển bài nhạc"` | `media_control {action: "next"}` |
| Tất cả cửa | `VehicleControlView.tsx:159` | `"mở cửa"` / `"đóng cửa"` | plan **4 bước** × `set_door_state`, **một** phê duyệt gộp |

Nút "tất cả cửa" trước đây trả `clarify` và không có câu trả lời nào thoát ra được. Giờ nó dừng
ở HITL với câu xác nhận liệt kê đủ bốn cửa.

## 2. ⚠ Quạt gió — FE **phải** đổi sang gửi mức tuyệt đối

| | Hiện tại | Phải đổi thành |
|---|---|---|
| `VehicleControlView.tsx:251` | `send("giảm quạt gió")` | `` send(`chỉnh quạt gió mức ${Math.max(0, fanLevel - 1)}`) `` |
| `VehicleControlView.tsx:268` | `send("tăng quạt gió")` | `` send(`chỉnh quạt gió mức ${Math.min(3, fanLevel + 1)}`) `` |

**Vì sao router không tự cộng trừ được:** `DeterministicControlRouter.route()` chỉ nhận một chuỗi
văn bản. Nó **không** đọc vehicle state — đó là thiết kế, không phải thiếu sót: router phải tất
định và không có side effect, còn state thì thuộc `VehicleGateway` (ADR-013). Muốn "tăng một mức"
thì phải biết mức hiện tại, mà router không có.

**Đây là mẫu FE đã dùng sẵn ở hai chỗ khác**, chỉ cần làm giống:

- Nhiệt độ — `VehicleControlView.tsx:90`: `` send(`bật điều hòa ${next} độ`) ``
- Sưởi ghế — `VehicleControlView.tsx:338`: `` send(`chỉnh sưởi ghế lái mức ${...}`) ``

Dải hợp lệ: **`0..3`**. Ngoài dải → `denied` / `fan_level_out_of_range` (không kẹp về biên).
`"tắt quạt gió"` cũng chạy, tương đương mức 0.

Nếu chưa kịp đổi: `"tăng quạt gió"` trả `clarify` / `missing_fan_level` — **không** im lặng rơi
vào RAG như trước, nên ít nhất người dùng nhận được câu hỏi lại có nghĩa.

## 3. ⚠ Đèn pha — FE **phải** đổi toggle thành bộ chọn 3 chế độ

Nút đèn hiện là **toggle hai chiều** (`VehicleControlView.tsx:277`), gửi `"bật đèn pha"` /
`"tắt đèn pha"`. Nửa "bật" chạy được; nửa "tắt" trả `denied`.

Thiết kế là **bộ chọn 3 chế độ**, không phải toggle:

| Chế độ | Câu gửi | Kết quả |
|---|---|---|
| Tự động | `"bật đèn tự động"` hoặc `"chuyển đèn sang tự động"` | `set_headlight_mode {mode: "auto"}` |
| Chiếu gần | `"bật đèn pha"` hoặc `"bật đèn chiếu gần"` | `set_headlight_mode {mode: "low_beam"}` |
| Chiếu xa | `"bật đèn chiếu xa"` | `set_headlight_mode {mode: "high_beam"}` |

Đèn trần là công tắc riêng, vẫn là toggle: `"bật đèn trần"` / `"tắt đèn trần"` →
`set_interior_light {enabled}`.

**Không có `off` cho đèn pha.** UNECE R48 quy định xe có đèn chạy ban ngày (DRL) bắt buộc có đèn
chiếu gần tự động theo ánh sáng môi trường và **không được phép có chế độ tắt thủ công**; sổ tay
VF9 cũng chỉ nói về *chế độ* đèn, không nói về công tắc nguồn. Cơ sở đầy đủ ở
[ADR-020](../adr/ADR-020-lights-and-trunk-domains.md).

`"tắt đèn pha"` trả `denied` / `headlight_off_not_permitted`. **Cố ý không** ánh xạ ngầm `"tắt"`
→ `"auto"`, dù trên xe thật vị trí "off" của cần gạt đúng là chế độ auto: ánh xạ ngầm là làm một
việc khác việc người dùng nói mà không báo.

`"bật đèn"` trống trả `clarify` — có hai loại đèn nên câu đó mơ hồ thật.

**Đèn không hỗ trợ** (sương mù, nháy cảnh báo, xi nhan, đèn phanh, đèn lùi, đèn đỗ, đọc sách,
ambient, chào mừng) rơi xuống tra sổ tay, **không** phải `clarify` — nên nếu FE có nút cho chúng
thì người dùng sẽ nhận câu trả lời từ sổ tay chứ không phải câu hỏi lại vô nghĩa.

## 3b. Cốp — chạy được ngay, FE không phải sửa

`VehicleControlView.tsx:190` gửi `"mở cốp"` / `"đóng cốp"` → `set_trunk_state {state}`. Cốp là
**S2 khi xe đứng yên, S3 khi đang chạy** — y hệt cửa xe, nên FE cần xử lý cả nhánh
`approval.required` lẫn nhánh bị chặn thẳng.

## 4. Khoảng trống đã biết, không phải bug

- **`"mở tất cả cửa sổ"` bắt buộc có token `tất cả`/`toàn bộ` tường minh.** Với cửa xe thì câu
  trống `"mở cửa"` đã đủ để nhắm cả bốn, nhưng với kính thì không — vì ở đó `hết` đã mang nghĩa
  khác (`"mở hết cửa sổ bên phụ"` = mở kính đó lên 100 %). Nhận nhầm sẽ biến một lệnh một-kính
  thành lệnh bốn-kính.

> **Ghi chú lịch sử (2026-08-13).** Bản đầu của mục này mô tả một khoảng trống khác: tầng sửa lỗi
> giọng nói `voice_correction.py` bẻ `"mở tất cả cửa"` thành `"mở tắt cà cửa"` — chèn `tắt`, một
> động từ điều khiển thật, vào câu người dùng không hề nói. PR này từng thêm 5 từ vào
> `COMMAND_VOCABULARY` để chữa.
>
> **Phần đó đã bị rút.** [ADR-018](../adr/ADR-018-remove-voice-correction-layer.md) gỡ hẳn tầng sửa
> lỗi khỏi pipeline sau khi ADR-017 thay PhoWhisper bằng Zipformer-30M: đo trên 50 case
> (24 synthetic + 26 giọng người thật), tầng đó **làm hại** — WER thô 9,58 % so với 13,19 % khi
> bật vocab 47 từ, hại 12 case và chỉ giúp 1.
>
> Nên khoảng trống ấy **tự biến mất**: không còn tầng nào bẻ chữ nữa, `"mở tất cả cửa"` và
> `"quay lại bài trước"` đi thẳng vào router nguyên vẹn.

## 5. ⚠ Sau khi merge, **bắt buộc dựng lại `vehicle-simulator`**

Không phải tuỳ chọn. `VehicleStateSnapshot` giờ có 9 domain và `lights`/`trunk` là **required**
trong `schemas/mqtt/vehicle_state_snapshot.schema.json`. Simulator chạy từ trước PR chỉ publish 7,
nên backend mới **từ chối** snapshot của nó:

```
WARNING src.services.vehicle_state:170 Snapshot sai schema trên
        v1/vehicles/vehicle-demo-01/state/snapshot: 2
```

Con số `2` là đúng hai field thiếu. Hậu quả dây chuyền:

| Nơi | Triệu chứng |
|---|---|
| `VehicleStateCache` | `_state` giữ `None` — snapshot bị loại ở tầng validate |
| `GET /api/v1/vehicle/state` | **503** `no_snapshot_yet` |
| Agent | `safety_node` từ chối lượt, outcome `vehicle_state_unavailable` |
| Màn hình IVI | không cập nhật gì |

Và vì `state/snapshot` là **retained**, bản 7-domain nằm lì trên broker cho tới khi simulator mới
ghi đè — tắt backend rồi bật lại **không** chữa được.

Cách chữa:

```powershell
docker compose up -d --build --force-recreate vehicle-simulator
.\.venv311\Scripts\python.exe scripts\smoke_mqtt.py
```

Chạy simulator bằng tay (`python -m src.vehicle_sim`) thì chỉ cần khởi động lại tiến trình.

> Đây là mặt trái đã biết của việc thêm domain, ghi ở [ADR-020](../adr/ADR-020-lights-and-trunk-domains.md)
> mục *Mất*. Thêm field vào `required` là **không breaking với client đọc** (`GET /vehicle/state`
> chỉ mọc thêm field), nhưng **là breaking với publisher** — mọi producer phải phát đủ.

## Cách kiểm chứng phía FE

```powershell
# BE, cửa sổ riêng
.\.venv311\Scripts\python.exe -m src.serve
```

Bật real mode (cả ba cờ về `false`), rồi bấm từng nút và đối chiếu `tool.result` trên `/ws/ivi`:

| Bấm | Tool mong đợi |
|---|---|
| Bài trước | `media_control` `{action: "previous"}` |
| Tất cả cửa | 4 × `set_door_state`, một `approval.required` |
| Quạt + / − | `set_hvac_fan_level` `{level: N}` — **sau khi đổi theo mục 2** |
