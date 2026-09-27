# Phủ đủ 19 test an toàn bắt buộc — kế hoạch

> **Cho người thực thi:** đọc `docs/safety_and_hitl.md` §Required safety tests trước.
> Việc này **không phải** "viết 12 test mới".

**Mục tiêu:** `tests/test_agents/test_hitl_safety.py` nói đúng sự thật về việc 19 yêu cầu
của `safety_and_hitl.md` được phủ tới đâu — và chỗ nào chưa phủ thì nói rõ vì sao.

## Phát hiện định hình kế hoạch

Header hiện tại ghi *"Phủ 7/19"*. Con số đó đếm **trong đúng một file**. Đối chiếu nhanh
toàn bộ suite cho thấy nhiều yêu cầu đã có mã kiểm ở nơi khác:

| Yêu cầu | Dấu vết đã có |
|---|---|
| #3 `validation_denied` | `test_agents/test_contracts.py`, `test_services/test_trace_collector.py` |
| #7 `execution_group_id` | `test_api/test_traces.py`, `test_vehicle/test_mqtt_roundtrip.py` |
| #8 `skipped_external_state_change` | `test_services/test_ivi_events.py` |
| #9 `skipped_due_to_prior_failure` | `test_services/test_ivi_events.py`, `test_api/test_metrics_summary.py` |
| #10, #11 retry/idempotency | `test_vehicle/test_mqtt_idempotency.py`, `test_mqtt_roundtrip.py` |
| #13 HVAC/seat = S1 | `test_agents/test_contracts.py` |
| #16 injection | `test_agents/test_router.py` |
| #19 outcome/reason của approval | `test_agents/test_hitl_node.py`, `test_api/test_approval_routes.py` |

**Nên viết 12 test mới là nhân đôi thứ đã có** — vừa tốn công bảo trì, vừa tạo tín hiệu
giả rằng đã kiểm kỹ hơn thực tế.

Nhưng "có dấu vết" **không phải** "đã phủ": phần lớn những chỗ trên kiểm *một mảnh* của
yêu cầu (ví dụ `test_ivi_events.py` kiểm **ánh xạ tên trạng thái ra sự kiện dây**, không
kiểm **executor có thực sự dừng group** khi state đổi). Nên bước một là đọc, không phải gõ.

## Ràng buộc toàn cục

- **Không sửa hành vi sản phẩm trong việc này.** Nếu một yêu cầu lộ ra bug thật thì
  dừng, ghi issue, và để nó thành ticket riêng — đừng vừa sửa vừa viết test cho chính
  bản sửa của mình.
- **Không đếm test tồn tại ở nơi khác là "đã phủ" nếu nó chỉ chạm một mảnh.** Tiêu chí:
  nếu hành vi mà yêu cầu mô tả bị phá, có ít nhất một test đỏ không?
- **Header file phải kiểm chứng được**, không phải lời tuyên bố. Mỗi số hiệu ghi rõ:
  phủ ở đâu, hoặc vì sao chưa phủ.

---

## Task 1: Audit 12 yêu cầu còn lại (đọc, chưa gõ)

**Files:** chỉ đọc.

Với mỗi yêu cầu trong {3, 7, 8, 9, 10, 11, 13, 14, 15, 16, 18, 19}, trả lời đúng ba câu:

1. Hành vi mà yêu cầu mô tả **có tồn tại trong `src/`** không?
2. Nếu có, phá nó đi thì **test nào đỏ**? (thử thật: sửa tạm mã cho sai rồi chạy)
3. Kết luận: `đã phủ` / `phủ một phần — thiếu vế X` / `chưa phủ` / `bị chặn vì thiếu tính năng`.

- [ ] Ghi kết quả thành bảng ngay trong plan này trước khi viết dòng test đầu tiên.

**Dự đoán ban đầu, cần audit xác nhận hoặc bác bỏ:**

- **#18 bị chặn.** `grep -r approval_intent src/` = **0 kết quả**. Duyệt bằng giọng nói
  chưa tồn tại, mà CLAUDE.md cũng liệt `approval.intent.detected` là một trong ba event
  `/ws/ivi` còn thiếu. Không viết được test cho tính năng không có → cần **ticket tính
  năng riêng**, và header phải ghi "chặn", không ghi "chưa làm".
- **#10, #11 nhiều khả năng đã phủ**: `tool_executor.py` có `MAX_ATTEMPTS = 2`, cache
  theo idempotency key, và persist đúng một terminal failed. `test_mqtt_idempotency.py`
  trông đúng chỗ. Nếu đúng thì việc còn lại chỉ là **ánh xạ**, không phải viết mới.
- **#13 gần như chắc chắn viết được ngay** — cùng dạng với #12 đã có, chỉ gọi `classify()`.

## Task 2: Viết test cho phần thật sự thiếu

**Files:** `tests/test_agents/test_hitl_safety.py` (và file phù hợp hơn nếu yêu cầu thuộc
tầng khác — đừng nhét test MQTT vào file agent chỉ để cho đủ số).

Thứ tự làm theo **giá trị an toàn giảm dần**, không theo số hiệu:

- [ ] **#15** — mixed S1/S2 chờ một bundled approval trước *mọi* side effect; có S3 thì
      **zero** side effect. Đây là chỗ dễ rò rỉ thực thi nhất trong plan nhiều bước.
- [ ] **#8** — external mutation làm actual khác rolling expected version → dừng group,
      bước còn lại `skipped_external_state_change`. Kiểm **hành vi executor**, không phải
      tên trạng thái trên dây.
- [ ] **#9** — bước fail/timeout/rejected → bước sau `skipped_due_to_prior_failure`,
      cùng lý do như trên.
- [ ] **#7** — hai bước S2 dùng chung một approval đã consumed + `execution_group_id` +
      rolling state version.
- [ ] **#19** — năm nhánh (reject/expiry/state-invalidation/plan-invalidation/predicate)
      dùng đúng outcome ổn định, **không** consume approval, **không** tạo group, **không**
      sinh MQTT transition. Gom một bảng tham số hoá.
- [ ] **#3** — `validation_denied` xảy ra **trước** S0–S3/HITL. Điểm mấu chốt là *thứ tự*,
      nên test phải chứng minh không có approval nào được tạo.
- [ ] **#16** — injection không đổi policy/tool registry; **SLM không gán safety và không
      publish MQTT**. Vế sau là bất biến kiến trúc (`CandidateActionPlan` không có trường
      safety) — khoá bằng test hợp đồng, đừng chỉ khoá bằng chuỗi prompt.
- [ ] **#14** — target window/door mơ hồ không tạo plan executable.
- [ ] **#13** — HVAC và seat heating là S1.

Mỗi test viết đỏ trước, chạy thấy đỏ, rồi mới xong. Với những yêu cầu mà audit kết luận
"đã phủ ở nơi khác", **không viết lại** — chỉ ghi tham chiếu ở Task 3.

## Task 3: Header nói đúng sự thật

**Files:** `tests/test_agents/test_hitl_safety.py`

- [ ] Thay dòng *"Phủ 7/19"* bằng bảng 19 dòng: số hiệu → phủ ở file/test nào, hoặc
      "chặn vì thiếu <tính năng>" kèm số issue.
- [ ] Dòng *"Đừng tuyên bố phủ hết 19"* giữ nguyên tinh thần nhưng cập nhật con số thật.
- [ ] Commit.

## Task 4: Issue cho phần bị chặn

- [ ] Mở issue **"Voice approval-intent turn (`approval.intent.detected`)"** — nêu rõ:
      brief hứa "voice-first HITL" mà duyệt bằng giọng nói chưa tồn tại; yêu cầu #18 của
      `safety_and_hitl.md` không kiểm được cho tới khi có; event nằm trong allowlist của
      `api_spec.md` nhưng chưa phát bao giờ.
- [ ] Nếu audit lộ ra bug thật ở #7/#8/#9: mỗi cái một issue riêng, **không** sửa trong
      việc này.

## Kết quả kỳ vọng

Từ 7/19 lên khoảng **18/19**, trong đó phần lớn mức tăng đến từ **ánh xạ đúng thứ đã có**
chứ không phải mã mới; #18 chặn và có ticket. Nếu con số cuối thấp hơn thì đó là thông
tin — nghĩa là có yêu cầu đang được tưởng là phủ mà thật ra không.
