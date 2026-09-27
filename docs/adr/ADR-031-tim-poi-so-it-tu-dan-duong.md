# ADR-031: Câu tìm địa điểm số ít tự đặt dẫn đường, kèm nghĩa vụ nói ra

- Status: Accepted
- Date: 2026-08-23
- Decision owner: Nhân (chủ nhiệm workstream agent), theo yêu cầu chốt thành acceptance
  criterion của @thanhpro82 (PM/PO review #252)
- Liên quan: ADR-010 §Scope boundary, ADR-011, spec `2026-08-23-sp5-poi-va-dan-duong-design.md`

## Context

SP-5 làm `"Tìm quán cà phê gần đây"` chạy được. Câu ấy là một yêu cầu **tìm**, nhưng
hệ thống đáp lại bằng một hành động **dẫn đường** — làm nhiều hơn điều được yêu cầu.

Đó là một quyết định về quyền tự quyết của trợ lý, không phải chi tiết cài đặt, nên nó
cần được ghi thành tiêu chí nghiệm thu chứ không nằm trong một dòng code.

Ba phương án đã cân nhắc (spec §2.1):

1. **Đọc danh sách rồi hỏi chọn cho mọi câu tìm** — an toàn nhất, nhưng tốn một lượt
   cho ca phổ biến nhất (một loại địa điểm, một chỗ gần nhất rõ ràng).
2. **Chỉ đọc, không bao giờ tự dẫn đường** — đơn giản, nhưng nghe cụt và bỏ lỡ chỗ nối
   hai ý mà chính use case đầu bài P0 đòi.
3. **Số ít thì đi, số nhiều thì hỏi** — chọn.

## Decision

**Dấu hiệu quyết định nằm trong chính câu nói: từ chỉ số nhiều.**

| Người nói | Hệ thống |
|---|---|
| *"Tìm quán cà phê gần đây"* | chọn chỗ **gần nhất**, đặt dẫn đường luôn |
| *"Tìm **các** quán cà phê gần đây"* | đọc danh sách (tối đa 3), **hỏi lại** muốn đi chỗ nào |
| dạng nghi vấn *"Quanh đây có quán cà phê nào không"* | `offer` — nêu việc sẽ làm rồi hỏi lại (ADR-011, không đổi) |
| số nhiều nhưng chỉ có **một** kết quả | dùng nhánh số ít — không hỏi khi không có gì để chọn |

Tập từ chỉ số nhiều là tập đóng: `các`, `những`, `mấy`, `bao nhiêu`.

### Vì sao chấp nhận được

`set_navigation` là **S1**: đảo ngược được bằng một câu (*"hủy chỉ đường"*), và **không
làm xe chuyển động** — nó đổi cái hiện trên bản đồ, không đổi trạng thái vật lý nào.
Khác hẳn mở cửa hay hạ kính. Rủi ro của việc làm thừa ở đây là *phiền*, không phải *nguy
hiểm*.

### Nghĩa vụ kèm theo — điều kiện của quyết định, không phải trang trí

Nhánh số ít **bắt buộc** nói đủ bốn thứ trong cùng một lượt:

1. **tên** địa điểm đã chọn,
2. **khoảng cách** (và thời gian ước tính),
3. nói rõ **đã đặt dẫn đường**,
4. **lối thoát** — cách đổi lựa chọn.

> *"Chỗ gần nhất là Cà phê Bình Minh, cách 3,65 km, khoảng 8 phút. Tôi đã chỉ đường tới
> đó. Muốn chỗ khác thì bảo tôi nhé."*

**Tự ý làm mà không nói ra mới là chỗ nguy hiểm.** Nói ra thì tài xế huỷ được bằng một
câu, và quyết định này mất tính chính đáng ngay khi vế ấy biến mất.

## Acceptance criteria

Bốn điều trên được khoá bằng test, không phải bằng lời hứa:

- `tests/test_agents/test_cau_tra_loi_poi.py` — `cau_da_chi_duong` chứa tên, khoảng cách,
  *"đã chỉ đường"*, *"chỗ khác"*.
- `tests/test_agents/test_poi_e2e.py::test_luot_9_cua_kich_ban_chay_tron` — đi trọn qua
  graph, assert cả bốn.
- `tests/test_agents/test_tim_poi.py` — ranh giới số ít / số nhiều / nghi vấn / một-kết-quả.
- `eval/datasets/agent/v3` — 8 ca dương tính + **3 ca âm tính** (*"tìm hiểu về…"*), vì
  matcher này là đường mới duy nhất biến một câu hỏi thành một lệnh.

**Cổng cứng không đổi:** ô `manual→control` = 0 trên `--mode dinh-tuyen` (đo sau SP-5:
114 ca, 101 đúng, ô = 0).

**Còn thiếu:** UAT với người ngoài nhóm — @thanhpro82 yêu cầu ở review #252 và tôi ghi
đây là điều kiện **chưa** đạt. Test tự động chứng minh câu trả lời *có* bốn thành phần;
nó không chứng minh người nghe *hiểu* rằng dẫn đường đã được đặt. Hai chuyện khác nhau,
và chỉ chuyện thứ nhất có bằng chứng hôm nay.

## Consequences

- Câu tìm địa điểm số ít không còn là S0 thuần: lượt ấy thực thi một tool S1.
- `"Đưa tôi về nhà"` nằm ngoài phạm vi (dữ liệu người dùng, thuộc `vehicle/profile`, #123).
- Nếu UAT cho thấy người dùng bất ngờ vì bị dẫn đường mà không xin phép, phương án lui
  là (1) ở trên — đọc danh sách rồi hỏi cho mọi câu tìm. Đổi một hằng số nhánh, không
  phải viết lại.
