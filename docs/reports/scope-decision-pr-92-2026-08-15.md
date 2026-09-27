# Quyết định phạm vi — PR #92 có nằm trong bản demo Sprint 4 không

> **Quyết định: INCLUDED — có điều kiện. Điều kiện đã thoả ngày 2026-08-15 (PR #121).**
>
> Mọi dữ kiện trong §1–§9 lấy trực tiếp từ git local, GitHub API và code trên `develop`
> @ `39d0309` **tại thời điểm viết, sáng 2026-08-15** — không chép lại tuyên bố của tài liệu khác.
> Chỗ nào chưa xác minh được thì ghi rõ là chưa.
>
> Người viết: Sơn (WS3). Người duyệt: PM/PO (`thanhpro82`) + Backend.

> ## Cách đọc tài liệu này
>
> **§1–§9 là ảnh chụp tại thời điểm ra quyết định, không phải mô tả hiện trạng.** Chúng được giữ
> nguyên văn vì §8 là chỗ ký nhận chính thức duy nhất của quyết định này, và §5 tồn tại để vá đúng
> cái mắt xích "ủng hộ có điều kiện ≠ phê duyệt được ghi nhận" — viết lại quá khứ sẽ xoá mất bằng
> chứng đó.
>
> **Muốn biết hôm nay hệ thống đang ở đâu thì đọc [§10](#10-trạng-thái-sau-pr-121--cập-nhật-2026-08-15).**
> Mọi việc mà §6 và §9 liệt kê như "phải làm" đều **đã xong** trong PR #121 (merge
> 2026-08-15T14:09Z); issue #115 đã CLOSED lúc 13:20Z cùng ngày. Đừng giao lại chúng cho ai.

## Kết luận một dòng

PR #92 **đã merge vào `develop` từ 2026-08-14**, nên đây là văn bản ghi nhận chính thức chứ không
phải mở lại lựa chọn; phần cần chốt thật sự là **3 tool nằm ngoài cam kết P0** (đèn, cốp) có được
lên sân khấu hay không — câu trả lời là **có với đèn, không với cốp**, và điều kiện bắt buộc là
[issue #115](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/115).

---

## 1. Vì sao "defer" không còn là lựa chọn thực tế

| | |
|---|---|
| Merge commit | `3c60331` — `Merge pull request #92 from .../feat/issue-65-control-surface` |
| Merge lúc | **2026-08-14T00:38:14Z**, bởi `thanhpro82` |
| Tác giả PR | `hason0510` |
| Quy mô | **84 file, +9.814 / −78** |
| Issue gốc | [#65](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/65) — đã CLOSED 2026-08-15T03:36:09Z |
| Nhánh | `feat/issue-65-control-surface` — đã xoá khỏi remote |

Sau `3c60331` đã có **9 PR khác merge lên trên**: #100, #101, #102, #104, #109, #110, #112, #113,
#114. Revert PR #92 sẽ kéo theo 4 schema MQTT, ADR-019, ADR-020, `coverage_matrix.md`,
`demo_runbook.md` và toàn bộ eval run đi kèm. Chi phí đó không tương xứng với bất kỳ lợi ích nào
của việc hoãn.

**Vì vậy quyết định thực chất không phải "merge hay không", mà là "diễn hay không diễn phần vượt
phạm vi".** Phần còn lại của tài liệu trả lời đúng câu đó.

---

## 2. Phần nào của PR #92 nằm ngoài P0

`docs/product_brief.md:58` cam kết đúng năm nhóm tool:

> Tools mô phỏng HVAC, ghế, media, cửa/kính, navigation.

Issue #65 thường được gọi là "5 tool", nhưng đó là **5 tính năng**, không phải 5 tool. Đối chiếu với
`src/services/tool_registry.py` sau PR:

| Tính năng | Tool thật | Trong P0? |
|---|---|:-:|
| Bài trước | `media_control` action `previous` — **tool cũ**, chỉ thêm rule router | ✅ media |
| Tất cả cửa | `set_door_state` ×4 — **tool cũ**, plan 4 bước, một phê duyệt gộp | ✅ cửa/kính |
| Quạt gió | `set_hvac_fan_level` — **tool mới** | ✅ HVAC (mở rộng trong domain) |
| Đèn | `set_headlight_mode`, `set_interior_light` — **2 tool mới**, domain `lights` mới | ❌ **ngoài P0** |
| Cốp | `set_trunk_state` — **1 tool mới**, domain `trunk` mới | ❌ **ngoài P0** |

Chỗ phạm vi nở ra đo được bằng một dòng code: `Domain` trong `src/models/vehicle.py` đi từ **7 lên
9** giá trị. Registry sau PR là **15 tool** (3×S0, 8×S1, 4×S2).

Hai ghi chú để không hiểu nhầm là "làm lố":

- **Quạt gió tuy trong domain HVAC nhưng vẫn là lật một quyết định P0.** `mqtt_spec.md` "Quyết định
  P0 số 2" từng để `fan_level` read-only và **cố ý không đặt trần**. [ADR-019](../adr/ADR-019-fan-level-becomes-controllable.md)
  lật quyết định đó và thêm `le=3`, vì đã có tool ghi thì không có trần nghĩa là `validate_assignment`
  không chặn được giá trị vô nghĩa.
- **Đèn và cốp có cơ sở chuẩn ngành, không phải tiện tay thêm.** [ADR-020](../adr/ADR-020-lights-and-trunk-domains.md)
  ghi đầy đủ: `headlight` là enum chế độ (`auto`/`low_beam`/`high_beam`) **cố ý không có `off`** theo
  UNECE R48; `set_trunk_state` chép nguyên predicate S2-khi-đứng-yên của cửa.

---

## 3. Quyết định demo

> **Điều kiện ở dòng "Đèn" đã thoả** — #115 đóng, PR #121 merge cùng ngày. Phương án lùi bên dưới
> không còn phải kích hoạt. Chi tiết ở [§10](#10-trạng-thái-sau-pr-121--cập-nhật-2026-08-15).

| Tính năng | Quyết định | Lý do |
|---|---|---|
| Quạt gió, bài trước, tất cả cửa | **Giữ** | Nằm trong cam kết P0, không cần chốt thêm |
| **Đèn** | **Giữ**, điều kiện #115 xong trước ngày demo | Đang là Màn 1 và Màn 2 của `demo_runbook.md`; Màn 2 (*"Tắt đèn pha"* → `denied / headlight_off_not_permitted`) là luận điểm an toàn mạnh, mất thì tiếc |
| **Cốp** | **Không diễn** (giữ code + test) | Không xuất hiện trong kịch bản nào; ngoài P0; bỏ đi giảm một mặt rủi ro mà không mất gì |

**Phương án lùi, phải nói trước với cả nhóm:** nếu #115 không kịp thì **cắt đèn khỏi Màn 1–2**. Vì
đèn và cốp nằm ngoài cam kết P0 nên cắt **không mất điểm ở phần chấm phạm vi** — đây là lý do phương
án lùi này rẻ, và là lý do nên chốt nó ngay bây giờ thay vì tối hôm trước buổi demo.

> **Danh sách fix cụ thể để demo được đầy đủ nằm ở [§9](#9-danh-sách-fix-để-demo-đầy-đủ-pr-92).**
> Đọc §9.4 trước khi chốt bảng trên: cốp và đèn dùng chung đúng một việc sửa, nên "giữ đèn, bỏ cốp"
> không tiết kiệm được gì về công — chỉ giảm rủi ro trên sân khấu.

---

## 4. Trạng thái kiểm thử — cái gì đã có, cái gì chưa

> **Ảnh chụp sáng 2026-08-15, trước PR #121.** Dòng "Test tay trên FE thật" và đoạn ngay dưới bảng
> đã hết đúng — xem [§10](#10-trạng-thái-sau-pr-121--cập-nhật-2026-08-15).

| Loại | Trạng thái | Bằng chứng |
|---|---|---|
| Test tự động | **Đủ** | `tests/test_agents/test_router.py` +376 dòng, `test_clarify_messages.py` +77, `test_simulator.py` +115, `test_policy.py`; `scripts/validate_mqtt_schemas.py` có case âm khẳng định `headlight="off"` bị từ chối |
| MQTT 4 tầng | **190/190** | `eval/results/mqtt-e2e/20260813T083452.464255Z` (L0 46 · L1 127 · L2 12 · L3 5) |
| Router/intent eval | `intent_accuracy 1.0000`, `tool_exact 1.0000` | `eval/results/agent-intent/20260813T084722.857202Z` |
| Routing eval | `question_recall 0.9833`, `question_to_control 0.0000` | `eval/results/agent-routing/20260813T084723.140964Z` |
| Lint | sạch | `ruff check src/ tests/` |
| **Test tay trên FE thật** | **CHƯA** | Đúng điều kiện số 3 mà PM/PO nêu ở comment PR (§5) |

**Hôm nay demo đèn thì câu lệnh chạy đúng nhưng màn hình nói sai.** `frontend/src/lib/services/turn/real.ts`
vẫn hard-code `lights: false` và `trunk: "closed"` kèm comment "BE chưa gửi field" — comment đó không
còn đúng, backend gửi cả hai. Đây là kiểu lỗi tệ nhất cho buổi demo: giao diện không im lặng, nó
**khẳng định một điều sai về chiếc xe**.

---

## 5. Dấu vết phê duyệt trên GitHub — và chỗ nó còn hở

Đọc qua GitHub API ngày 2026-08-15:

- `reviewDecision` **rỗng**, và `GET /pulls/92/reviews` trả **mảng trống** → **không có review chính
  thức nào**. Không ai bấm Approve, cũng không ai Request changes.
- Toàn bộ phản hồi nằm ở dạng issue comment. Comment của PM/PO (`thanhpro82`, **2026-08-13T07:12:46Z**)
  nêu ba điều kiện trước merge:

  1. **Bàn giao FE** — link ticket/PR FE, hoặc ghi rõ đây là BE-only handoff.
  2. **Voice UX an toàn** — chốt + thêm test cho câu ghép `chỉnh nhiệt độ và quạt ...` và câu mơ hồ
     `tắt đèn`.
  3. **Demo acceptance checklist** — checklist test tay 5 luồng mới.

  Kết: *"Khi 3 điểm trên có owner/đường dẫn rõ ràng, mình ủng hộ merge."*
- `phoenix-mentor[bot]`: *Ticket compliance 🔶 — issue #85 Partially compliant*.
- Label `Review effort 4/5`; milestone: không có; `closingIssuesReferences` **rỗng** (PR không link
  tự đóng #65 — #65 được đóng tay ngày 2026-08-15).

Merge diễn ra **~17 giờ sau** comment đó. Điều kiện 2 và 3 đã được đáp ứng trong
[báo cáo kiểm chứng](issue-65-kiem-chung-va-setup-2026-08-13.md) §2.2 và §5; **điều kiện 1 thì được
trả lời là "BE-only handoff"** qua [TASK-BE-FE-004](../tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md),
và ticket FE tương ứng chỉ ra đời sau merge (issue #115).

**Đó là mắt xích mà tài liệu này vá lại:** ủng hộ có điều kiện không phải là phê duyệt được ghi nhận.
Quyết định ở §3 cần chữ ký của PM/PO và Backend ở §8.

---

## 6. Điều kiện bắt buộc — task 20–22 = [issue #115](https://github.com/AI20K-Build-Phase-Cohort-3/P-192/issues/115)

> **Ảnh chụp sáng 2026-08-15, trước PR #121. Toàn bộ bảng dưới đây đã xong.** #115 CLOSED
> 2026-08-15T13:20Z. Bảng giữ lại để thấy phạm vi điều kiện lúc chốt, không phải danh sách việc còn
> treo — đối chiếu ở [§10](#10-trạng-thái-sau-pr-121--cập-nhật-2026-08-15).

Issue #115 (`FE: đèn/cốp hiển thị sai và nút quạt gió không hoạt động sau PR #92`) khi đó đang **OPEN
và chưa ai nhận**. Sáu chỗ phải sửa, đối chiếu trực tiếp với code trên `develop` hôm đó:

| # | Chỗ | Hiện trạng | Định nghĩa hoàn thành |
|---|---|---|---|
| 20 | `turn/real.ts`, `turn/types.ts` | hard-code `lights: false`, `trunk: "closed"`; kiểu `boolean`/`string` | Nhận object canonical `{headlight, interior}` và `{position}`; `headlight` là enum 3 giá trị |
| 21 | `VehicleControlView.tsx:251,268` | `send("tăng/giảm quạt gió")` → `clarify` | Gửi mức tuyệt đối `chỉnh quạt gió mức N`, FE tự cộng trừ trong `0..3` |
| 21 | `VehicleControlView.tsx:277` | toggle `"tắt đèn pha"` → `denied` | Bỏ nhánh tắt, hoặc chuyển sang chọn chế độ `auto`/`low_beam`/`high_beam` |
| 22 | `mock.ts` | tên tool `control_trunk`, `control_lights`; kẹp fan `0..5` | Tên canonical; kẹp `0..3`; có test Vitest khoá |
| 22 | Checklist | chưa chạy | Chạy 5 luồng ở **real mode** (`NEXT_PUBLIC_USE_MOCK_TURN/SESSION/ENGINEER=false`), dán kết quả vào #115 |

Ảnh chụp ở mock mode **không chứng minh gì** về backend — mock hiện còn lệch contract ở đúng hai chỗ
ghi trong bảng trên.

---

## 7. Hai thứ phải ghi lại để không mất dấu

### 7.1 PR sửa chính bộ dataset tripwire

`eval/datasets/agent/v3/cases.jsonl` đổi **3 case** trong cùng PR:

| Case | Trước | Sau |
|---|---|---|
| `A3-GUARD-DOOR-001` "Mở cửa xe" | `clarify` | `control`, 4 bước `set_door_state` |
| `A3-DOOR-004` "Đóng cửa" | `clarify` | `control`, 4 bước |
| `A3-DEN-003` "Mở cốp sau" | `denied`, domain `unsafe` | `control` `set_trunk_state`, domain `trunk` |

Sửa là **đúng** — hành vi đổi có chủ đích thì expected phải đổi theo. Nhưng hệ quả phải nói thẳng:
`intent_accuracy 1.0000` sau PR được đo trên bộ dữ liệu do **chính PR đó sửa**, nên tripwire không
còn khả năng bắt hồi quy ở đúng ba case này. `eval/datasets/agent/v3` vốn đã chỉ là tripwire hồi quy
do chính người viết router viết ra — **không bao giờ được trình bày như chỉ số độ chính xác trước
người dùng**.

Liên quan, và đáng giá hơn cả PR: khi thêm `_match_lights`, `question_recall` tụt **0.9833 → 0.9667**
trong khi **cả 979 test vẫn xanh**. Chỉ `--mode routing` bắt được. `_UNSUPPORTED_LIGHTS` trong
`router.py` là guard giữ chỉ số đó. **Từ nay thêm matcher nào cũng phải chạy cả hai eval**, không chỉ
pytest.

### 7.2 Bẫy vận hành: snapshot retained 7 domain

`VehicleState` nay **bắt buộc** có `lights` + `trunk`, và `fan_level` có trần `le=3`. Simulator dựng
trước PR chỉ publish 7 domain → backend mới từ chối → `GET /vehicle/state` trả **503
`no_snapshot_yet`** → agent từ chối mọi lượt. Mosquitto bật `persistence true` + named volume nên
snapshot cũ **sống qua cả `docker compose down`**; khởi động lại backend **không** chữa được.

Máy demo phải chạy đúng lệnh này trước buổi diễn:

```powershell
docker compose up -d --build --force-recreate vehicle-simulator
```

---

## 8. Ký nhận

| Vai | Người | Ngày | Ý kiến |
|---|---|---|---|
| PM/PO | Thành (`thanhpro82`) | 2026-08-13 → 2026-08-15 | **Đồng ý include.** Nêu ba điều kiện trước merge ở comment PR #92 (§5), rồi chốt lại ngày 2026-08-15: phần vượt phạm vi P0 phải xác nhận **demo được và có test** thì mới đóng task. Quyết định ở §3 và điều kiện ở §6 là cách đáp ứng yêu cầu đó |
| Backend | Sơn (`hason0510`) | 2026-08-15 | **Đồng ý include theo §3.** Chịu trách nhiệm phần backend đã merge và bằng chứng ở §4. Nêu rõ hai rủi ro chưa đóng: FE hiển thị sai `lights`/`trunk` (issue #115, chưa ai nhận) và bẫy snapshot retained ở §7.2 |

> Ghi chú về hình thức phê duyệt — cần đọc kèm §5: hai chữ ký trên **không** tương ứng với một GitHub
> approval. Trên PR #92 `reviewDecision` rỗng và `/pulls/92/reviews` trả mảng trống; ý kiến PM/PO tồn
> tại dưới dạng issue comment (2026-08-13) và trao đổi trực tiếp (2026-08-15). Bảng này là chỗ chốt
> chính thức duy nhất, và đó chính là lý do tài liệu này tồn tại.

## 9. Danh sách fix để demo đầy đủ PR #92

> **Ảnh chụp sáng 2026-08-15, trước PR #121 — đây là chẩn đoán, không phải việc đang chờ.** Cả 4 việc
> bắt buộc ở §9.3 lẫn việc 5 "nên làm" đều đã hoàn tất; mọi dấu ❌ ở §9.1 nay là ✅. Trạng thái hiện
> tại ở [§10](#10-trạng-thái-sau-pr-121--cập-nhật-2026-08-15). Giữ mục này vì chuỗi hệ quả ở §9.2
> (hai dòng hard-code → chết cả hoạt ảnh 3D) là bài học còn giá trị sau khi bug đã đóng.

Rà từng tính năng trên `develop` ngày 2026-08-15, đối chiếu trực tiếp với code.
**Backend của PR #92 chạy đúng hết; toàn bộ chỗ vỡ nằm ở frontend, và tất cả bắt nguồn từ đúng hai
dòng hard-code.**

### 9.1 Hiện trạng từng tính năng

| Tính năng | Lệnh thoại | Nút trên FE | Hiển thị / mô hình 3D |
|---|:-:|---|---|
| Bài trước / chuyển bài | ✅ | ✅ `MusicView.tsx:90,109` gửi đúng | ✅ |
| Tất cả cửa (HITL) | ✅ | ✅ | ⚠️ cửa mở nhưng **kính + tấm ốp ở lại** (đã sửa ở #121, xem §10.1 việc 5) |
| Quạt gió | ✅ *"đặt quạt gió mức 2"* | ❌ `VehicleControlView.tsx:251,268` gửi `"giảm/tăng quạt gió"` → `clarify` | ✅ `hvac.fanLevel` backend gửi thật |
| Cốp | ✅ | ✅ `VehicleControlView.tsx:190` gửi `"mở cốp"` đúng | ❌❌ badge luôn *"Đang đóng"* **và mô hình 3D không bao giờ lật cốp** |
| Đèn | ✅ *"bật đèn chiếu gần"* | ❌ `VehicleControlView.tsx:277` toggle, nửa *"tắt đèn pha"* → `denied` | ❌❌ badge luôn *"đang tắt"* **và quầng sáng không bao giờ bật** |

### 9.2 Gốc của bốn dấu ❌ ở cột cuối

```ts
// frontend/src/lib/services/turn/real.ts:103,105
lights: false,
trunk: "closed",
```

Chuỗi hệ quả, đọc thẳng từ code:

```
real.ts:103,105  (hard-code)
  ├─→ VehicleControlView.tsx:67   lightsOn  = vehicleState?.lights ?? false      → luôn false
  ├─→ VehicleControlView.tsx:186  trunkOpen = vehicleState?.trunk === "open"     → luôn false
  ├─→ Car3DViewer  animateTrunk(scene, "closed", …)   → pivot cốp không bao giờ xoay
  └─→ Car3DViewer:294  quầng đèn  opacity-0 vĩnh viễn
```

Backend gửi đủ `{"lights":{"headlight":"auto","interior":false},"trunk":{"position":"closed"}}` —
frontend vứt đi rồi thay bằng hằng số. **Điểm dễ bỏ sót nhất: `Car3DViewer` đọc `vehicleState` do
`real.ts` dựng ra, nên hai dòng hard-code không chỉ làm sai chữ trên badge mà làm chết luôn hoạt ảnh
3D.**

### 9.3 Việc phải làm

**Bắt buộc — bốn việc, đều ở frontend:**

| # | File | Sửa gì |
|---|---|---|
| 1 | `turn/real.ts:103,105` + `turn/types.ts:31,39` | Nhận object thật `{headlight, interior}` / `{position}`; `trunkOpen` đọc `trunk.position === "open"` |
| 2 | `Car3DViewer.tsx:294` | Quầng đèn đổi từ `vehicleState?.lights` (object → **luôn truthy**) sang so sánh chế độ, ví dụ `lights.headlight !== "auto"` |
| 3 | `VehicleControlView.tsx:251,268` | Gửi mức tuyệt đối `` `chỉnh quạt gió mức ${…}` ``, FE tự cộng trừ trong `0..3` |
| 4 | `VehicleControlView.tsx:277` | Bỏ nhánh *"tắt đèn pha"*; đổi thành chọn chế độ `auto`/`low_beam`/`high_beam` |

Việc 1 và 2 **phải đi cùng nhau** — làm 1 mà quên 2 thì quầng đèn bật vĩnh viễn thay vì tắt vĩnh
viễn, đổi một lỗi lấy một lỗi.

**Nên làm nếu diễn màn "mở cả bốn cửa" (Màn 3 biến thể):**

| # | File | Sửa gì |
|---|---|---|
| 5 | `Car3DViewer.tsx` — `ensureDoorPivots` | Gom `door-front-window-glass-l_18`, `door-front-interior-panel-l_14` và ba bộ còn lại vào **cùng pivot** với cửa |

**Không phải code — điều kiện môi trường:**

- `docker compose up -d --build --force-recreate vehicle-simulator` (bắt buộc, xem §7.2 của tài liệu này).
- Chạy frontend ở real mode: `NEXT_PUBLIC_USE_MOCK_TURN` / `_SESSION` / `_ENGINEER` = `false`.

**Không chặn demo:** `mock.ts` (tên tool không canonical, kẹp quạt `0..5`) chỉ ảnh hưởng mock mode.
Vẫn nên sửa để test khỏi lệch hợp đồng, nhưng không nằm trên đường demo.

### 9.4 Ảnh hưởng ngược lại tới quyết định ở §3

Cốp cần đúng **việc 1**, mà việc 1 vốn đã phải làm cho đèn. Nên:

- Làm việc 1+2 → **đèn và cốp cùng demo được**, cốp không tốn thêm gì.
- Không làm việc 1+2 → **mất cả hai**, dù backend đúng; chỉ còn quạt gió (sau việc 3), bài trước và
  tất cả cửa.

Ranh giới thật vì vậy không phải "đèn hay cốp", mà là **có làm việc 1+2 hay không**. Quyết định giữ
đèn ở §3 phụ thuộc hoàn toàn vào đó.

---

## 10. Trạng thái sau PR #121 — cập nhật 2026-08-15

**Đây là mục duy nhất mô tả hiện tại.** §1–§9 phía trên là ảnh chụp lúc ra quyết định, giữ nguyên văn.

Mốc thời gian trong ngày 2026-08-15: issue #115 **CLOSED 13:20Z** → PR #121 (*fix(fe): đọc
lights/trunk thật từ BE + nút quạt gió/đèn gửi đúng câu router hiểu*) **merge 14:09Z** vào `develop`
@ `9e0dc6d`. Bảng dưới đối chiếu với code trên đúng commit đó, không lấy từ mô tả PR.

### 10.1 Năm việc ở §9.3 — xong cả năm

| # | Việc ở §9.3 | Trạng thái | Kiểm ở đâu |
|:-:|---|:-:|---|
| 1 | `real.ts`/`types.ts` nhận object thật `{headlight, interior}` / `{position}` | ✅ | `turn/real.ts:70-71,111-112`; `turn/types.ts:34,41`. Cố ý **không** đặt giá trị mặc định phòng hờ: thiếu field là hợp đồng bị vi phạm, phải vỡ sớm chứ không im lặng nói sai về xe |
| 2 | Quầng đèn so sánh **chế độ**, không dùng object (luôn truthy) | ✅ | `Car3DViewer.tsx:284-286,310-311` — `auto` tắt, `low_beam` mờ, `high_beam` sáng |
| 3 | Nút quạt gửi mức tuyệt đối, FE tự cộng trừ trong `0..3` | ✅ | `VehicleControlView.tsx:125` gửi `đặt quạt gió mức N`; `pendingFanLevel` chống bấm nhanh liên tiếp tính trên state cũ |
| 4 | Bỏ nhánh *"tắt đèn pha"*, chuyển sang chọn chế độ | ✅ | Bộ 3 nút ở `VehicleControlView.tsx:317-335`; nút xoay vòng ở `RightPanel.tsx:45`; hằng số dùng chung ở `headlightControl.ts` |
| 5 | Gom kính + tấm ốp vào **cùng pivot** với cửa | ✅ | `car3dNodes.ts` + `car3dNodes.test.ts`. PR #121 làm thêm hai việc ngoài danh sách: hạ kính thật theo `windows[*]` (quãng tụt lấy min với khoảng trống thật trong cửa — bản đầu cho kính chui xuống gầm), và camera xoay về đúng mạn cửa vừa mở |

Kèm theo, hai thứ §9 xếp là "không chặn demo" cũng đã sửa: `mock.ts` kẹp quạt về `0..3`, nhận mức
tuyệt đối, dùng tên canonical cho `set_hvac_fan_level` / `set_headlight_mode` / `set_interior_light` /
`set_trunk_state`, và **từ chối `tắt đèn pha` y như router thật**.

### 10.2 Một thay đổi backend không có trong §9

PR #121 sửa thêm `src/agents/nodes/compose.py`: `DENIED_MESSAGES` cho từng `route_reason`, thay câu
chung *"Xin lỗi, tôi không thực hiện được yêu cầu này."* Với `headlight_off_not_permitted`, tài xế
giờ nghe được lý do **và** câu thay thế. Quyết định của router **không đổi** — `"tắt đèn pha"` vẫn
`denied`, không ánh xạ ngầm sang `auto`, có `tests/test_agents/test_denied_messages.py` khoá lại.
Điều này làm Màn 2 của runbook mạnh hơn chứ không thay thế nó.

### 10.3 Bảng §9.1 đọc lại theo hôm nay

| Tính năng | Lệnh thoại | Nút trên FE | Hiển thị / mô hình 3D |
|---|:-:|:-:|:-:|
| Bài trước / chuyển bài | ✅ | ✅ | ✅ |
| Tất cả cửa (HITL) | ✅ | ✅ | ✅ kính và tấm ốp mở theo cửa |
| Quạt gió | ✅ | ✅ mức tuyệt đối | ✅ |
| Cốp | ✅ | ✅ | ✅ badge và pivot cốp theo `trunk.position` thật |
| Đèn | ✅ | ✅ 3 chế độ | ✅ quầng sáng theo chế độ |

### 10.4 Chỗ duy nhất còn hở

**Điều kiện cuối của §6 — "chạy 5 luồng ở real mode rồi dán kết quả vào #115" — vẫn chưa có bằng
chứng công khai.** `gh issue view 115 --json comments` trả về **rỗng**: #115 bị đóng mà không có
comment nào mang kết quả test tay. PR #121 có nói tới việc test tay ngày 2026-08-15 (ba yêu cầu sản
phẩm phát sinh chính là từ đó) và có test tự động mới ở cả hai phía, nhưng **checklist 5 luồng real
mode thì không tìm thấy ở đâu**. Ai chạy buổi demo nên chạy lại và dán vào đâu đó có địa chỉ.

Một lớp test mới đáng ghi nhận vì nó đóng đúng khe hở đã cắn hai lần trong một ngày (nút khoá cửa,
nút quạt gió): `tests/test_agents/test_fe_button_commands.py` khẳng định từng chuỗi lệnh mà nút FE
dựng ra đi tới đúng tool + args ở **router thật**. Trước đó FE không import được router, còn router
không biết FE gửi gì, nên cả hai bên đều xanh trong khi nút bấm không chạy.

## Nguồn

- `git show 3c60331`, `git diff 3c60331^1...3c60331^2`
- GitHub API: `pulls/92`, `pulls/92/reviews`, `issues/92/comments`, `issues/65`, `issues/115`
- §10: `develop` @ `9e0dc6d`; `gh pr view 121`, `gh issue view 115 --json comments` (rỗng); đọc trực
  tiếp `frontend/src/{lib/services/turn,components/ivi}/` và `src/agents/nodes/compose.py`
- [`docs/product_brief.md`](../product_brief.md) §Scope · [`docs/coverage_matrix.md`](../coverage_matrix.md) · [`docs/demo_runbook.md`](../demo_runbook.md) Phần 2–3
- [ADR-019](../adr/ADR-019-fan-level-becomes-controllable.md) · [ADR-020](../adr/ADR-020-lights-and-trunk-domains.md) · [TASK-BE-FE-004](../tasks/TASK-BE-FE-004-issue-65-command-vocabulary.md)
- [Báo cáo kiểm chứng issue #65](issue-65-kiem-chung-va-setup-2026-08-13.md)
