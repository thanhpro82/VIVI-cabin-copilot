# UAT Bug Triage Board

Danh sách **duy nhất** cho mọi phát hiện từ UAT (`docs/release/mvp-demo-checklist.md`).
Một bug ở một chỗ: không mở song song ở chat nhóm, không ghi rải trong WORKLOG.

> **Ngày demo: 2026-08-16 (mai).** Chỉ còn một buổi tối. Điều đó đổi cách dùng
> board này: vòng UAT phải chạy **hôm nay**, và thứ duy nhất còn kịp sửa là P0.
> Mục nào không phải P0 thì mặc định đẩy sang sau demo — đừng sửa lặt vặt đêm
> trước demo, rủi ro làm hỏng thứ đang chạy được cao hơn giá trị của bản sửa.
>
> **Về "Jira board":** repo này không nối với Jira, nên bảng này là bản gốc.
> Nếu team dựng board Jira thật thì mỗi dòng ở đây là một issue, giữ nguyên ID
> `UAT-xxx` làm summary prefix để đối chiếu hai chiều. Đừng để hai nơi trôi khác nhau.

## Định nghĩa mức độ

| Mức | Nghĩa | Deadline | Ảnh hưởng demo |
|---|---|---|---|
| **P0** | Chặn demo. Gồm đúng ba loại: (1) **lỗi an toàn** — lệnh S2/S3 chạy mà không qua phê duyệt, chạy hai lần, hoặc chạy khi xe không đứng yên; (2) **mất kết nối WebSocket** — UI không khóa khi mất socket, hoặc không phục hồi đúng khi nối lại; (3) **hỏng chặn demo** — một luồng bắt buộc không chạy được tới cùng, hoặc chạy đúng ở backend mà màn hình không phản ánh. | **Tối nay 2026-08-15**, trước vòng UAT cuối | Còn P0 mở → **bỏ luồng đó khỏi buổi demo** |
| **P1** | Sai rõ nhưng có đường đi vòng, hoặc chỉ ảnh hưởng phần đã deferred. | Chạm luồng demo → tối nay. Chỉ chạm phần đã deferred → **sau demo** | Demo vẫn chạy, có thể phải né thao tác |
| **P2** | Lỗi nhỏ, lệch hiển thị, nợ tài liệu/comment sai. | Sau demo | Không ảnh hưởng |

Với mốc demo là mai, quy tắc quyết định gọn lại còn một câu: **sửa P0, ghi
nhận phần còn lại.** Một P1 mở không chặn demo — nó chỉ cần được biết trước để
người dẫn demo không bấm vào đúng chỗ đó.

Quy tắc phân mức: **lỗi an toàn luôn là P0 kể cả khi hiếm gặp**. Không hạ mức
vì "khó tái hiện" — khó tái hiện là lý do để điều tra thêm, không phải để hạ.

## Trạng thái

`Open` → `In progress` → `Fixed` → `Verified` (tester chạy lại đúng kịch bản đã fail) → `Closed`.
Chỉ **tester** được chuyển sang `Verified`, không phải người sửa.
`Won't fix` phải kèm một dòng lý do và tên người duyệt.

## Board

| ID | Mô tả | Kịch bản | Mức | Owner | Deadline | Trạng thái | Ghi chú |
|---|---|---|---|---|---|---|---|
| UAT-001 | `real.ts:105` hard-code `trunk: "closed"`, không đọc `raw.trunk.position`. Lệnh mở/đóng cốp chạy đúng ở backend nhưng nút cốp trên UI đứng yên. | — (biết trước UAT) | P1 | Giáp | Sau demo | Open | Cốp đã deferred khỏi demo scope nên không chặn mai. **Đừng sửa tối nay.** Thành P0 ngay nếu ai đó đưa cốp trở lại kịch bản demo. |
| UAT-002 | `real.ts:103` hard-code `lights: false`, không đọc `raw.lights.headlight` / `.interior`. Đèn đổi ở backend nhưng UI không đổi. | — (biết trước UAT) | P1 | Giáp | Sau demo | Open | Cùng gốc với UAT-001, sửa một lần cả hai. |
| UAT-003 | Nút đèn ở `VehicleControlView.tsx:277` gửi `"tắt đèn pha"`, nhưng `router.py:601` từ chối `headlight_off_not_permitted` theo ADR-020 (enum `headlight` cố ý không có `off`). Toggle hai trạng thái sai mô hình. | — (biết trước UAT) | P1 | Giáp | Sau demo | Open | **Phải sửa cùng lúc với UAT-002.** Sửa 002 mà bỏ 003 thì nút thành: bấm lần 1 được, lần 2 bị từ chối. Mai: **đừng bấm nút đèn trên màn hình**. |
| UAT-004 | Comment "BE chưa gửi field lights/trunk" ở `real.ts:102-105` và `turn/types.ts` đã sai kể từ PR #92 — `VehicleState` có `LightsState`/`TrunkState` thật. | — (biết trước UAT) | P2 | Giáp | Sau demo | Open | Comment sai dẫn người đọc sau kết luận sai về backend. |
| UAT-009 | Token bị backend vô hiệu giữa chừng (ca thường gặp nhất: **restart backend**, vì store token nằm trong RAM) làm mọi request trả `401 "token không hợp lệ hoặc đã hết hạn"`, nhưng FE chỉ nháy toast 3,2 s rồi **kẹt tại chỗ**: `getStoredSession()` vẫn tin `expiresAt` do chính client giữ (còn 12 h), nút vẫn bấm được, `/ws/ivi` reconnect vô hạn 8 s/lần với đúng token đã chết. Không có đường tự phục hồi ngoài F5 / xoá localStorage. | W-5 | P0 | Sơn | 2026-08-15 | Fixed | Sửa ở nhánh `fix/auth-token-invalid-expired`. FE: mọi 401/403 và close code 4401/4403 → `logout()` + về `/login` kèm lý do. BE: `resolve()` nay `move_to_end` (cap 256 token trước đây là FIFO nên login thứ 257 đá token **đang dùng**), và tách "hết hạn" khỏi "server vừa restart" trong `message`. Đã chạy tay đúng `W-5`: đăng nhập → restart backend → trang tự về `/login` trong ~4 s, `localStorage` sạch, banner nêu đúng lý do. **Tester phải tự chạy lại `W-5` trước khi chuyển `Verified`.** |

*(UAT-001..004 là các mục đã biết trước khi chạy UAT, ghi vào đây để board là
danh sách duy nhất. Mọi phát hiện trong lúc chạy checklist thêm từ UAT-005.)*

*(Số hiệu nhảy từ 004 sang 009 vì UAT-005…008 được mở trên các nhánh chưa vào
`develop`: 005/006 ở `docs/reports/uat-precheck-backend-2026-08-15.md`, 007/008 ở
nhánh UAT vòng 1. Giữ nguyên số đã cấp thay vì đánh lại — số trùng giữa hai nhánh
còn khó lần hơn một khoảng trống.)*

## Mẫu thêm mục mới

Copy dòng dưới, điền, đừng bỏ trống cột nào:

```
| UAT-0xx | <mô tả hiện tượng, không phải phỏng đoán nguyên nhân> | <ID kịch bản, vd S2-3> | P0/P1/P2 | <tên> | <yyyy-mm-dd> | Open | <bằng chứng: ảnh chụp / commit / run id> |
```

Ba thứ bắt buộc khi mở mục:

1. **Hiện tượng, không phải chẩn đoán.** "Bấm Đồng ý xong kính không đổi" chứ
   không phải "chắc do MQTT". Chẩn đoán sai làm người sửa đi nhầm hướng.
2. **Đúng ID kịch bản** đã fail trong checklist — để verify lại chạy đúng bước đó.
3. **Bằng chứng.** Ảnh màn hình, hoặc run id nếu có. Không có bằng chứng thì
   mục này không verify lại được.

## Tổng kết vòng triage

| Vòng UAT | Ngày | P0 mở | P1 mở | P2 mở | Đủ điều kiện demo? |
|---|---|---|---|---|---|
| | | | | | |

**Điều kiện demo:** 0 bug P0 đang mở. Không có ngoại lệ kiểu "P0 này demo né
được" — nếu né được thì nó không phải P0, hãy hạ mức và ghi lý do.

## Phân công theo vùng

Dùng khi không rõ giao cho ai (theo `docs/demo_scope.md`):

| Vùng lỗi | Owner |
|---|---|
| Voice / STT / luồng S1 | Sơn |
| HITL, approval, RAG, TTS | Nhân |
| Driver UI, WebSocket, overlay | Giáp |
| Router, policy, tool registry, simulator | Thành |
