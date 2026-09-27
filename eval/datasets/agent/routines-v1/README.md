# routines-v1 — bộ đo ý định preview/chạy Routine (issue #285, outcome #274)

38 ca. Acceptance của #274 đòi *"các câu mẫu được nhận diện đúng trên eval set đã
thống nhất"* — hôm nay chưa có bộ nào, đây là bộ đầu tiên.

## Cảnh báo về nguồn — đọc trước khi trích bất kỳ con số nào

**Cả 38 ca đều `source: tu_viet`**, do chính người viết matcher soạn. Theo đúng bài học
`agent/v3` mà repo đã ghi thành kỷ luật, nghĩa là:

> Bộ này là **tripwire hồi quy**, KHÔNG phải thước đo khái quát hoá. Một con số
> 38/38 ở đây không nói gì về việc người thật sẽ nói thế nào.

Đây là cùng cái nợ mà issue #244 đang mở cho lớp chitchat, và cách đóng cũng giống:
xin mỗi người trong nhóm 7–8 câu **họ** sẽ nói để chạy/xem trước một Routine, nhập vào
với `source` riêng, rồi đo lại. Chưa có nguồn độc lập thì mọi báo cáo phải kèm dòng
cảnh báo này.

## Trường

| trường | nghĩa |
|---|---|
| `case_id` | `RT-{RUN,PRE,YES,NO,SKIP,NEG,CTX}nnn` |
| `input_text` | nguyên văn, **chưa** normalize (giữ hoa/thường và dấu câu — đó là một phần phép thử) |
| `y_dinh` | `chay` \| `xem_truoc` \| `dong_y` \| `tu_choi` \| `bo_buoc` \| `khong_phai_routine` |
| `ngu_canh` | `binh_thuong` \| `dang_xem_truoc` |
| `ten_tho` | tên Routine người nói, **chưa** phân giải (chỉ ca `chay`/`xem_truoc`) |
| `so_buoc` | số thứ tự bước cần bỏ (chỉ ca `bo_buoc`) |

## `ngu_canh` là một trường, không phải chi tiết cài đặt

Hai ca `RT-CTX*` tồn tại để khoá đúng điều này: *"Đồng ý"* và *"Chạy đi"* là **đồng ý**
khi đang có preview treo, và **không phải ý định Routine** khi không có. Cùng một chuỗi,
hai nhãn ngược nhau, phân biệt duy nhất bởi ngữ cảnh phiên.

Bỏ trường ấy đi thì matcher buộc phải chọn một trong hai — và chọn "đồng ý" nghĩa là
mỗi lần tài xế nói *"chạy đi"* giữa lúc không có gì treo, hệ đi tìm một Routine để chạy.

## Mười ca `RT-NEG*`: cổng cứng

`khong_phai_routine` → matcher **không được** trả ý định nào. Trong đó bốn ca là bẫy có
chủ đích, dùng đúng từ khoá của lớp Routine ở một nghĩa khác:

```
RT-NEG006  "Chạy nhanh quá đấy"          — "chạy" là mô tả tốc độ
RT-NEG007  "Đi làm bằng xe này mất bao lâu" — "đi làm" là tên một Routine, nhưng đây là câu hỏi
RT-NEG008  "Về nhà đường nào gần nhất"   — "về nhà" cũng vậy
RT-NEG001  "Bật điều hòa 22 độ"          — lệnh thường, phải để router luật bắt
```

`RT-NEG007`/`RT-NEG008` là lớp nguy hiểm nhất: tên Routine mặc định (*Đi làm*, *Về nhà*)
trùng với những cụm tiếng Việt cực kỳ thông dụng. Nhận nhầm ở đây nghĩa là một câu hỏi
sổ tay biến thành một chuỗi 4 hành động lên xe.

## Chạy

Chưa nối vào `src/agents/eval.py` — matcher còn đang viết. Hiện đo bằng
`tests/test_agents/test_routines_intent.py`, chạy trực tiếp trên `cases.jsonl` nên
thêm ca vào file là test tự phủ theo.
