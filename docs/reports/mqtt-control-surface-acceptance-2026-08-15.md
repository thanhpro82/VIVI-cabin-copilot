# MQTT control-surface acceptance — 2026-08-15

Bằng chứng cho task *"Run MQTT control-surface acceptance tests"*: HITL cửa, mức
quạt tuyệt đối, quy tắc cốp chỉ mở khi xe đứng yên, và các chế độ đèn của PR #92
(**đã merge**, commit `3c60331`).

> **Cập nhật 2026-08-16 sau release gate của PM.** Mọi số trong tài liệu này đã được
> **đo lại** trên `03fe6cf` (nhánh đã rebase lên `develop` `e6b87c2`), và ca
> TRUNK-moving nay assert tín hiệu semantic `action.blocked` / `SAFETY_BLOCKED` qua
> WebSocket thật, kèm một **đối chứng âm** ở ca TRUNK-stationary — xem §AC2. Tên file
> giữ ngày 2026-08-15 vì `uat-precheck-backend-2026-08-15.md:69` đang trỏ vào nó.

## Môi trường

| | |
|---|---|
| Nhánh | `test/mqtt-control-surface-acceptance` @ `03fe6cf`, base `e6b87c2` (= `develop` lúc chạy, đã gồm PR #157) |
| Broker | Mosquitto thật (`docker compose up -d --wait mqtt`), `mqtt://localhost:1884` |
| Xe cho phần kiểm tay | `vehicle-acc-01` trên cổng `8299` — **không** đụng `vehicle-demo-01` của container demo đang chạy |
| Tiến trình | `python -m src.serve` và `python -m src.vehicle_sim` chạy riêng, nối qua broker thật |
| Cấu hình lại được | `ACC_APP_PORT`, `ACC_VEHICLE_ID`, `ACC_DRIVER_EMAIL`, `ACC_DRIVER_PASSWORD` |

Chọn `vehicle_id` và cổng riêng là có chủ đích: container `vehicle-simulator` của
buổi demo vẫn chạy suốt (`Up 11 hours (healthy)`), và nó publish trên topic của
`vehicle-demo-01`. Hai xe không giẫm lên nhau, nên không phải tắt gì để kiểm.

Cả bốn tham số trên đọc từ biến môi trường, và cổng có preflight: cổng bận thì script
dừng ngay kèm câu lệnh sửa, thay vì để backend chết lặng rồi script chờ hết 180 s và
báo một triệu chứng trỏ sai nguyên nhân. Credential lấy thẳng từ `DEMO_USERS`
(`src/db.py`) chứ không chép lại vào script — một bản sao thứ hai sẽ lệch im lặng đúng
vào ngày ai đó đổi seed, và triệu chứng khi đó là 401 ở bước đăng nhập.

## AC1 — MQTT contract test passes

Đo lại 2026-08-16 trên `03fe6cf`, cây làm việc **sạch**:

| Tầng | Lệnh | Kết quả |
|---|---|---|
| L2 contract | `MQTT_CONTRACT_TESTS=1 pytest tests/test_vehicle/test_contract_mosquitto.py` | **12 passed** (86,89 s) |
| L3 hai tiến trình | `MQTT_L3_TESTS=1 pytest tests/test_vehicle/test_l3_two_process.py` | **5 passed** (22,60 s) |
| Báo cáo tổng | `python scripts/report_mqtt_e2e.py --with-contract --with-l3` | **193/193 pass, 0 fail** (121,7 s) |

Run bằng chứng: **`eval/results/mqtt-e2e/20260816T073557.873233Z`** (`manifest.json`,
`metrics.json`, `case_results.jsonl`, `junit.xml`, `report.md`), với
`git_commit = 03fe6cff7f72…` và `git_dirty = false`.

**Run cũ `20260815T153212.087085Z` đã bị gỡ khỏi nhánh**, không phải để giấu một kết
quả xấu — nó cũng 193/193 — mà vì manifest của nó ghi `git_commit = 9e0dc6d`, tức
**base**, không phải commit nào của nhánh, kèm `git_dirty = true`. Một bản evidence như
thế không gắn được vào mã nguồn đang review, đúng thứ mà trường `git_dirty` sinh ra để
tố giác. Thư mục run là bất biến, nên cách sửa là **chạy lại sinh run mới**, không phải
sửa tay run cũ.

L3 **đỏ ở lần chạy đầu tiên của lượt trước** và đó là một phát hiện, không phải nhiễu —
xem mục cuối.

## AC2 — kiểm tay: cốp khi đứng yên và khi đang chạy

Chạy bằng `scripts/manual_control_surface_check.py` (tái chạy được). Nó tồn tại vì
`L3Stack` trong bộ test spawn xe ảo với `stdin=DEVNULL`, nên console điều khiển thoát
ngay và **không đổi được tốc độ giữa chừng** — mà đó chính là điều hai ca cốp cần.

**12 ca, 12 PASS, 0 FAIL.**

| Case | Kết quả | Quan sát |
|---|---|---|
| FAN-2 | PASS | `"Chỉnh quạt gió mức 2"` → `fan_level = 2` |
| FAN-3 | PASS | `"Chỉnh quạt gió mức 3"` → `fan_level = 3` |
| FAN-1 | PASS | `"Chỉnh quạt gió mức 1"` → `fan_level = 1` |
| LIGHT-high_beam | PASS | `"Bật đèn chiếu xa"` → `headlight = high_beam` |
| LIGHT-low_beam | PASS | `"Bật đèn chiếu gần"` → `headlight = low_beam` |
| LIGHT-interior | PASS | `"Bật đèn trần"` → `interior = true` |
| LIGHT-off-denied | PASS | `"Tắt đèn pha"` → không lập ActionPlan nào, `headlight` giữ `low_beam` |
| DOOR-hitl | PASS | `"Mở cửa bên lái"` (đứng yên) → `waiting_approval`, cửa vẫn `closed` |
| DOOR-approve | PASS | sau khi duyệt → cửa `open`, `state_version = 8` |
| **TRUNK-moving** | **PASS** | `speed = 30.0 km/h`, `gear = D` → `action.blocked.code = "SAFETY_BLOCKED"`, `steps = [(set_trunk_state, S3)]`, `plan_id` khớp, **không có hộp phê duyệt**, **0 bước chạy**, cốp `closed → closed` |
| **TRUNK-stationary** | **PASS** | `speed = 0`, `gear = P` → `waiting_approval`, cốp vẫn `closed`, và **không** có `action.blocked` |
| TRUNK-approve | PASS | sau khi duyệt → cốp `open`, `state_version = 11` |

Hai dòng in đậm là thứ AC2 đòi. Điểm đáng chú ý ở **TRUNK-moving**: xe đang chạy thì
lệnh bị chặn **trước** cả bước hỏi phê duyệt — không có hộp xác nhận nào hiện ra. Đó
là khác biệt giữa "hỏi rồi mới chặn" và "chặn trước khi hỏi", và nó khớp `policy.py`
(`_STATIONARY_ONLY_TOOLS` gồm `set_door_state`, `set_seat_position`, `set_trunk_state`).

### Vì sao TRUNK-moving cần tín hiệu WS, không chỉ "không có side effect"

Bản đầu của ca này assert đúng ba mệnh đề: không có approval, không có outcomes, cốp
không đổi. Cả ba đều đúng — nhưng **một no-op cũng thoả cả ba**. Nếu router không khớp
câu, hoặc STT ra chữ khác, kết quả quan sát được y hệt. Tức nó chứng minh *"không có
side effect"*, chưa chứng minh *"bị chặn **vì** safety"*. PM nêu điểm này ở release
gate, và nó đúng.

Ca này nay mở `/ws/ivi` **thật** (chào đủ `vivi.v1` + `bearer.<base64url-token>`, kèm
header `Origin` lấy theo `cors_origins`) và đòi **năm** điều kiện cùng đúng:

| # | Điều kiện | Chứng minh điều gì | Đo được |
|---|---|---|---|
| 1 | `action.blocked.code == "SAFETY_BLOCKED"` | Đã qua phân loại chính sách — event này chỉ phát ở nhánh `outcome == "blocked"` của `emit_turn_lifecycle` | `'SAFETY_BLOCKED'` |
| 2 | `action_plan.steps` có `set_trunk_state` ở **S3** | Router **đã lập** kế hoạch cho đúng tool cốp, không rơi vào tra sổ tay | `[('set_trunk_state', 'S3')]` |
| 3 | `action.blocked.plan_id == action_plan.plan_id` | Event WS thuộc **đúng lượt này**, không phải sót lại từ ca khác | khớp |
| 4 | Không `pending_approval`, `outcomes` rỗng | Chặn **trước** HITL, không bước nào chạy | 0 bước |
| 5 | `trunk.position` không đổi | Không side effect | `closed → closed` |

Điều kiện 2 và 3 đóng nốt khe hở no-op: chúng nói rằng kế hoạch **có tồn tại**, đúng
tool, đúng mức an toàn, và chính kế hoạch đó bị chặn.

**Đối chứng âm.** Assert sự *có mặt* của một event chỉ có giá trị nếu nó **vắng mặt**
khi không được phép có — một assertion luôn đúng thì không phân biệt được gì. Nên ca
TRUNK-stationary assert thêm `action.blocked is None`. Cùng câu lệnh, cùng session, chỉ
khác tốc độ, và hai ca cho hai chuỗi event khác hẳn nhau:

| Ca | Chuỗi event nhận được trên `/ws/ivi` |
|---|---|
| TRUNK-**moving** (30 km/h, D) | `plan.ready` · **`action.blocked`** · `assistant.speech` · `assistant.response` · `turn.completed` |
| TRUNK-**stationary** (0 km/h, P) | `plan.ready` · `approval.required` · `assistant.status` |

Hai chuỗi này là bằng chứng mạnh nhất trong tài liệu: chúng cho thấy hệ thống **rẽ hai
nhánh khác nhau** cho cùng một câu lệnh, và biến quyết định duy nhất là tốc độ xe.

Payload nguyên văn, ghi vào `.acc-logs/ket-qua.json` ở khoá `trunk_moving_action_blocked`:

```json
{
  "plan_id": "plan-b0aa11bd01e27f86",
  "code": "SAFETY_BLOCKED",
  "reason": "Lệnh bị chặn vì trạng thái xe hiện tại không cho phép."
}
```

`wait_for` chụp mốc dòng event **trước** khi gửi câu lệnh và chỉ quét phần sau mốc đó,
nên một event sót của ca trước không làm ca sau pass oan; nếu `action.blocked` không
tới trong 25 s thì `code` là `None` và ca ghi FAIL.

Mức quạt là **tuyệt đối**: ba lệnh liên tiếp 2 → 3 → 1 cho ra đúng ba giá trị đó, không
cộng dồn.

### Lời từ chối trên base này đã nêu lý do

PR #121 (`9e0dc6d`) đưa `DENIED_MESSAGES` vào `compose.py`, nên ba câu bị từ chối không
còn dùng câu chung nữa. Đo qua REST trên đúng base này:

| Câu | Trả lời |
|---|---|
| `"Tắt đèn pha"` | *Đèn pha không tắt thủ công được — xe có đèn chạy ban ngày nên đây là quy định an toàn. Bạn nói "chuyển đèn sang chế độ tự động" để xe tự bật tắt theo trời sáng tối nhé.* |
| `"Đặt nhiệt độ 45 độ"` | *Điều hòa chỉ đặt được từ 16 đến 30 độ.* |
| `"Chỉnh quạt gió mức 4"` | *Quạt gió chỉ đặt được từ mức 0 đến 3.* |

Điều này đóng **UAT-005** trong `docs/reports/uat-precheck-backend-2026-08-15.md`: bản
sửa mà báo cáo đó nói là "đã tồn tại trên nhánh chưa merge" nay đã ở trên `develop`.
Câu đèn pha còn nêu cả **lối ra** (`"chuyển đèn sang chế độ tự động"`), tức nó cũng gỡ
phần khó chịu nhất của UAT-003.

## AC3 — liên kết với demo checklist

`docs/release/mvp-demo-checklist.md` phủ 5 luồng bắt buộc. Ánh xạ:

| Kịch bản checklist | Ca tương ứng ở đây | Ghi chú |
|---|---|---|
| **S1-2** — "Chỉnh quạt gió mức 2" | FAN-2 | checklist đòi *"dải 4 mức sáng đúng 2 mức"* — phần UI vẫn phải kiểm tay |
| **S2-1** — mở kính, bấm Đồng ý | DOOR-hitl + DOOR-approve | cùng đường HITL, khác actuator (cửa thay vì kính) |
| **S2-5** — xe chạy, "Mở cửa bên lái" | TRUNK-moving | cùng quy tắc `requires_stationary`, actuator khác; cả hai chặn trước HITL |
| — | LIGHT-*, TRUNK-* | **ngoài checklist**: đèn và cốp đã deferred khỏi demo scope (PR #92, xem `docs/demo_scope.md`) |

Nói rõ để không ai đọc nhầm: bằng chứng này **không thay thế** vòng UAT. Nó chứng minh
backend + MQTT + xe ảo quyết định và thực thi đúng; checklist đo *thứ người dùng nhìn
thấy trên màn hình*, và hai luồng đèn/cốp thì thậm chí không nằm trong buổi demo.

## Hai phát hiện kèm theo

### 1. Test L3 đã trôi khỏi hành vi sản phẩm

`test_healthz_bao_ready_khi_ca_hai_tien_trinh_song` đỏ ở lần chạy đầu:

```
assert components["llm"] == "down"   →  thực tế: "disabled"
```

Không phải hồi quy. Issue #95 (PR #126) thêm trạng thái thứ tư `disabled` cho component
**tắt có chủ đích**, và `slm_enabled=false` là cấu hình P0 mặc định
(`src/services/health.py:199`, detail `slm_disabled`). Test còn khoá hành vi cũ vì
**tầng L3 không chạy trên CI**, nên #95 merge mà nó không đỏ.

Đã sửa trong nhánh này. Đây là lần thứ hai cùng một khuôn lỗi xuất hiện ở tầng L3 —
lần trước là header `Idempotency-Key` thiếu sau PR #44, cũng "hỏng im lặng suốt từ đó"
theo ghi chú ngay trong file test.

### 2. `status: "completed"` không có nghĩa "lệnh đã chạy"

Bản đầu của script kiểm tay ghi FAIL cho `LIGHT-off-denied` và `TRUNK-moving` vì tôi
assert `status != "completed"`. Assert sai, không phải hệ thống sai:

- `src/api/turns.py:447-455` chỉ trả `failed` cho `execution_failed`/`vehicle_state_unavailable`
  và `clarify` cho `approval_already_pending`; mọi outcome khác — kể cả `denied`,
  `blocked`, `clarify` của router — đều là `completed`, nghĩa **lượt đã kết thúc**.
- Tín hiệu thật nằm ở WS: outcome `blocked` phát `action.blocked` với
  `code = "SAFETY_BLOCKED"` trước `turn.completed` (`src/services/ivi_events.py:545`).
- FE không đọc `data.status` của REST; nó dựng UI từ event WS.

Nên hợp đồng nhất quán, nhưng cái tên dễ gây hiểu nhầm cho người mới đọc API. Ghi lại
ở đây để lần sau ai kiểm tay không mất một vòng như tôi.

**Kết luận ban đầu của mục này chưa đủ, và release gate đã bắt đúng chỗ đó.** Nó dừng ở
"cách kiểm đúng là xem ActionPlan có được lập không, có bước nào chạy không, trạng thái
xe có đổi không" — ba câu hỏi về *hệ quả*. Ba câu đó không phân biệt được "bị chặn vì
safety" với "không có gì xảy ra cả". Câu hỏi còn thiếu là câu về *nguyên nhân*, và nó
chỉ trả lời được trên WebSocket: **`action.blocked` có tới không, `code` của nó là gì,
và nó có vắng mặt ở ca lẽ ra không bị chặn không**. Xem §AC2.

### 3. Một lỗi của chính script, đáng ghi vì nó chứng minh idempotency hoạt động

Lần chạy thứ hai fail ở `FAN-2` với *"quá 20s mà quạt chưa về mức 2"*. Nguyên nhân:
`Idempotency-Key` sinh theo bộ đếm trần (`acc:fan:2`) nên trùng key của lần chạy trước;
backend replay đúng response cũ và **không gửi lệnh nào xuống xe** — đúng như hợp đồng
idempotency yêu cầu. Script đã đổi sang tiền tố theo thời điểm chạy.

## Tái chạy

```powershell
docker compose up -d --wait mqtt
$env:MQTT_CONTRACT_TESTS="1"; .\.venv\Scripts\python.exe -m pytest tests/test_vehicle/test_contract_mosquitto.py -q
$env:MQTT_L3_TESTS="1";       .\.venv\Scripts\python.exe -m pytest tests/test_vehicle/test_l3_two_process.py -q
.\.venv\Scripts\python.exe scripts\manual_control_surface_check.py
.\.venv\Scripts\python.exe scripts\report_mqtt_e2e.py --with-contract --with-l3
```

Cổng `8299` hoặc `vehicle-acc-01` đã bận trên máy bạn thì đổi, không phải sửa mã nguồn:

```powershell
$env:ACC_APP_PORT="8399"; $env:ACC_VEHICLE_ID="vehicle-acc-02"
.\.venv\Scripts\python.exe scripts\manual_control_surface_check.py
```

Script kiểm tay ghi kết quả máy đọc được vào `.acc-logs/ket-qua.json` — gồm cả payload
`action.blocked` nguyên văn ở khoá `trunk_moving_action_blocked` — và log hai tiến
trình vào `.acc-logs/backend.log` với `.acc-logs/simulator.log`.

**Sinh evidence thì chạy trên cây làm việc sạch.** `report_mqtt_e2e.py` ghi `git_dirty`
vào manifest, và bất kỳ file lạ chưa commit nào ở nơi khác cũng bật cờ đó — khiến một
bản evidence hợp lệ bị người đọc chiết khấu. Đó chính là điều đã xảy ra với run
`20260815T153212.087085Z`.
