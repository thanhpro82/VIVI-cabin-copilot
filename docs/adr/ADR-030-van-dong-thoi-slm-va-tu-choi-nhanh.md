# ADR-030: Van đồng thời cho SLM, và ba vai từ chối theo ba cách khác nhau

- Status: Accepted
- Date: 2026-08-25
- Decision owner: Sơn
- Nguồn: PM/PO review PR #257 (2026-08-24), điều kiện 1 và 2
- Bổ sung cho: [ADR-016](ADR-016-slm-fallback-gates.md) (cổng planner),
  [ADR-011](ADR-011-default-to-manual-lookup.md) (mặc định về sổ tay là fail-safe)
- Liên quan: ADR-028 (pool xe ảo, PR #259) — trần pool và van này là **hai** giới hạn

## Context

`src/agents/graph.py` gọi SLM ở ba chỗ (`slm_stage`, `classify_stage`,
`chitchat_stage`) và **không có giới hạn nào** về số lượt gọi cùng lúc. Backend nhận
bao nhiêu người dùng cũng đẩy hết xuống llama-server.

Đo trên VPS qua đúng đường HTTP mà tài xế đi
(`eval/results/luot-that-dong-thoi/20260825T050738`, `develop` @ `3e4e6a4`,
`-c 2048`, 4 rãnh, 18 mẫu mỗi mức):

| Đường | N=1 | N=2 | N=3 |
|---|---:|---:|---:|
| `dieu_khien` (không chạm SLM) | 191 ms | 378 ms | 432 ms |
| `so_tay` | 843 ms | 1 328 ms | **15 660 ms** |
| `chitchat` | 283 ms | **7 932 ms** | 8 549 ms |
| `planner` | **17 330 ms** | 25 463 ms | 39 119 ms |

Hai chuyện tách bạch trong bảng này, và chúng cần hai bản vá khác nhau:

1. **`chitchat` và `so_tay` chậm vì xếp sau `planner`**, không phải vì bản thân
   chúng nặng — timeout của `chitchat` chỉ 4 s mà lượt đo được 7,9 s. PR #257 (bọc
   `asyncio.to_thread`) sửa vế này.
2. **Không ai được báo gì cả.** Lượt quá tải chờ hết timeout rồi rơi âm thầm về sổ
   tay hoặc `clarify` — mà `clarify` (*"tôi chưa hiểu ý anh"*) **nói sai nguyên
   nhân**: tài xế tưởng mình nói khó nghe, thật ra là máy hết chỗ.

Vế 2 là thứ ADR này giải quyết.

## Decision

### 1. Một van chung, sức chứa là tham số

`slm_max_concurrent` (`src/config.py`, mặc định **2**) giới hạn số lượt được gọi
model cùng lúc. Cơ chế ở `src/agents/slm.py` (`goi_qua_van`), chính sách ở
`graph.py`.

Là tham số chứ không phải hằng số vì máy khác nhau chịu khác nhau: máy dev có GPU đo
78 tok/s, VPS 5 vCPU đo 8,44 tok/s.

**2 là số tạm, chưa phải số đo được.** Hai run `eval/results/slm-dong-thoi/*` cho
kết luận ngược nhau về mức N=2, và cả hai đều đo *trước* khi có van lẫn `to_thread`.
Chốt lại bằng `scripts/do_luot_that_dong_thoi.py` sau khi #257 lên VPS.

### 2. Van phải NHỎ HƠN trần pool xe

ADR-028 đặt `vehicle_pool_size` trần 3. Van **không được** bằng 3: tối đa 3 phiên,
mỗi tài xế nói xong mới nói tiếp, nên nhu cầu đồng thời không bao giờ vượt 3 — van
bằng 3 thì **không bao giờ đóng**, tức thoả điều kiện 2 trên giấy mà không làm gì.

Hệ quả: nếu đo lại thấy máy chịu được 3 lượt đồng thời thì kết luận đúng là **nâng
trần pool lên 4**, không phải hạ van xuống bằng pool.

### 3. Một bể chung, nhưng thời gian chờ khác nhau theo vai

`_CHO_THEO_VAI` trong `slm.py`: `classify` 300 ms, `chitchat` 200 ms, `planner`
50 ms.

Đây là thứ tự ưu tiên, và là lý do dùng một bể chung thay vì một bể mỗi vai. Nếu ai
tới trước chiếm trước thì một lượt `planner` (17–28 s) giữ chỗ rất lâu và đá văng mọi
lượt `classify` phía sau — mà `classify` mới là vai chạy nhiều lượt nhất, vì mọi câu
trượt luật đều qua nó. Vai rẻ được chờ một chút; vai đắt hết chỗ là bỏ ngay.

### 4. Ba vai từ chối theo ba cách — và `classify` KHÔNG từ chối

| Vai | Hết chỗ thì | Vì sao |
|---|---|---|
| `planner` | Ưu tiên câu sổ tay nếu RAG đã có; không có thì `CAU_BAN`. **Không thử lại.** | Không có đường vòng nào khác. Thử lại chỉ để xin đúng cái van vừa từ chối |
| `chitchat` | `CAU_BAN`, đánh dấu `chitchat_cong="ban"` | Tách khỏi `"loi"`: quá tải tạm thời khác model hỏng |
| `classify` | **Vẫn** rơi về sổ tay, nhưng ghi `route_reason="slm_classify_ban"` | Xem dưới |

`classify` là chỗ duy nhất không từ chối tài xế, và đó là quyết định có chủ đích chứ
không phải bỏ sót.

Tra sổ tay **không dùng llama-server chút nào** — FAISS + E5 chạy trong tiến trình,
và câu trả lời là trích nguyên văn chứ không do model viết (ADR-015). Model chỉ được
hỏi một câu phụ: *"câu này là hỏi sổ tay hay tán gẫu?"*. Hết chỗ ở câu phụ đó không
có nghĩa là không trả lời được câu chính. Từ chối ở đây là **từ chối một việc hệ vẫn
làm được**, và sẽ biến mọi câu hỏi sổ tay thành lời xin lỗi đúng lúc đông người.

Điều kiện 2 của review (*"không được im lặng timeout/fallback"*) vẫn được thoả: nó
không còn im lặng, vì `slm_classify_ban` là một `route_reason` **riêng**, tách khỏi
`slm_classify_failed`, nên trace và `/metrics/summary` đếm được. "Im lặng" nghĩa là
không ai biết, không phải nghĩa là tài xế không bị làm phiền.

Cái giá đã cân: bỏ bước phân loại thì một câu tán gẫu có thể bị đem đi tra sổ tay và
trả lời trớt quớt. Chỉ ảnh hưởng câu trượt luật, và chỉ lúc quá tải.

### 5. `SlmBanError` KHÔNG kế thừa `OSError`

Ba node đều bắt `(SlmSchemaError, OSError, httpx.HTTPError)` và xử lý như "hạ tầng
hỏng". Nếu `SlmBanError` lọt vào bộ đó thì lượt **bận** đi đúng đường của lượt
**hỏng**, mất hết phần thông điệp mà điều kiện 2 đòi — và không test hành vi nào bắt
được. `tests/test_agents/test_slm_van_dong_thoi.py` khoá tính chất này riêng.

## Consequences

- Lúc quá tải, một số lượt nhận `CAU_BAN` thay vì câu trả lời. Đó là **cải thiện**
  so với chờ 26 giây rồi nhận một câu nói sai nguyên nhân.
- **Bọc `to_thread` đổi một vấn đề lấy một vấn đề khác — đo được, không lường trước.**
  Trên `develop`, event loop bị chặn nên các lời gọi SLM **nối tiếp**: mỗi lượt planner
  được dùng model một mình, xong trong ~14 s, dưới `SLM_TIMEOUT_S=20`. Việc bị chặn vô
  tình *bảo vệ* planner. Sau bản vá chúng chồng lên nhau thật, mỗi lời gọi chậm đi, và ở
  N≥2 nhiều lượt vượt 20 s → hết giờ cả hai lần thử → không ra kế hoạch.

  Số lượt planner sinh được kế hoạch (9 mẫu mỗi mức, hai run cùng `-c 2048`):

  | | N=1 | N=2 | N=3 |
  |---|---|---|---|
  | `develop` (`20260825T050738`) | 6/9 | 6/9 | 6/9 |
  | sau bản vá (`20260825T073454`) | 5/9 | 3/9 | 1/9 |

  Đổi lại: `chitchat` ở N=2 nhanh lên 12,8×, `so_tay` ở N=3 nhanh lên 5,9×, và p50 tổng
  hợp **đạt** ngưỡng ở cả ba mức thay vì trượt ở hai mức. Đánh giá: đổi có lợi, vì
  `dieu_khien`/`so_tay`/`chitchat` chiếm phần lớn lượt thật còn `planner` là đường hiếm
  nhất và vốn đã tệ nhất — nhưng đây là **quyết định sản phẩm**, ghi ra đây để người sau
  không tưởng bản vá chỉ toàn mặt tốt.

  Cách chữa cho việc sau, **chưa làm**: cho `planner` một hạn mức đồng thời riêng bằng 1
  (nó giữ lại ~14 s của mình), hoặc nâng `SLM_TIMEOUT_S`. Không làm trong PR này để
  không trộn thêm biến vào phép đo.
- **Ở quy mô 3 người, van gần như chưa hoạt động.** Cả run N=1..3 chỉ đóng **1 lần**, ở
  `classify` — vì trong một lượt ba vai gọi *so le* nhau (`classify` nhả chỗ trước khi
  `planner` xin), nên ba lượt đồng thời hiếm khi cần quá 2 chỗ cùng lúc. Van là lưới an
  toàn cho mức cao hơn, không phải cơ chế chạy thường xuyên ở mức demo. Đừng quy cải
  thiện độ trễ đo được cho nó — công đó là của `to_thread`.
- Van **không** chữa được độ trễ: `planner` vẫn 17 s ở N=1, vì đó là chi phí sinh
  ~120 token ở 8,44 tok/s trên CPU. Van chỉ đổi "im lặng chờ" thành "được báo ngay".
- `asyncio.Semaphore` sống trong **một event loop, một tiến trình**. Chạy hai uvicorn
  worker là có hai van, sức chứa thật gấp đôi con số đã chốt. Cùng giả định mà
  `session_state._GRAPHS`, `InMemorySaver` và `vehicle_pool` đã dựa vào (ADR-028).
- Van nằm **trong backend**, nên thứ gọi thẳng `:8093` (`slm_warmup.sh`,
  `scripts/do_slm_dong_thoi.py`) đi vòng qua nó. Muốn đo tác dụng của van thì phải đo
  qua HTTP của backend — đó là lý do `scripts/do_luot_that_dong_thoi.py` tồn tại.
- Van không đụng tới STT/TTS. Cả hai có khoá toàn cục (`voice.py:97`, `:192`,
  `num_threads=1`) nên chúng vẫn nối tiếp bất kể van đặt bao nhiêu.

## Đã cân nhắc và bỏ

- **Xếp hàng có thông báo** thay vì từ chối. Review cho phép cả hai. Bỏ vì hàng đợi
  cần một kênh báo tiến độ mà `/ws/ivi` chưa có event nào cho việc đó
  (`api_spec.md` allowlist đóng), và vì với `planner` 17–28 s thì "xếp hàng" nghĩa là
  hứa một thứ tệ hơn từ chối.
- **Một bể mỗi vai.** Đơn giản hơn nhưng không giải được bài toán ưu tiên: `planner`
  vẫn chiếm trọn phần của nó và `classify` vẫn không có cách nào chen lên.
- **Van bằng trần pool cho "đồng nhất"** — xem mục 2, nó vô hiệu hoá chính cơ chế.
