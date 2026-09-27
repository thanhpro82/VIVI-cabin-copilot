# STT chép sai gần hết câu lệnh **ngắn** — đo 2026-08-26

**Cây đo:** `develop` @ `3610397` · **Máy:** máy dev của @hason0510 (Windows 11, có
`models/voice/zipformer-30m-rnnt-6000h` và `vi_VN-piper.onnx`)
**Lệnh:** `.\.venv\Scripts\python.exe scripts\do_wer_sua_chinh_ta.py`

## Vì sao có báo cáo này

Issue "STT nghe *Dừng nhạc* thành *Rừng nhạc*" chặn ở hai điều kiện: (1) một file WAV tái
hiện được, (2) một run WER **có** và **không** lớp sửa trên cùng bộ audio. Chưa có WAV
người thật, nên tôi dựng bộ audio bằng chính Piper của repo để ít nhất có (2) — và phép đo
ấy trả lời một câu hỏi **khác** với câu hỏi ban đầu.

## Kết quả chính: độ dài câu, không phải chính tả

| Nhóm | Ví dụ | STT chép ra |
|---|---|---|
| **2–3 từ** | `Dừng nhạc` | `Trương nhà` |
| | `Bật nhạc` | `Đơn nhà` |
| | `Tắt nhạc` | `Các nhà` |
| | `Mở cốp` | `Gối` |
| | `Chuyển bài` | `Truyền bài` |
| | `Tăng âm lượng` | `Theo âm lượng` |
| **6+ từ** | `Bật điều hòa hai mươi hai độ giúp mình` | **đúng nguyên câu** |
| | `Mở cửa sổ bên lái ba mươi phần trăm` | **đúng nguyên câu** |
| | `Bật đèn chiếu gần giúp mình` | **đúng nguyên câu** |
| | `Đặt âm lượng bốn mươi phần trăm` | **đúng nguyên câu** |
| | `Vivi ơi tăng âm lượng giúp tôi` | `Va tăng âm lượng giúp tôi` — **phần lệnh đúng** |

Lệnh trần 2–3 từ hỏng gần hết; cùng những lệnh ấy đặt trong câu 6+ từ thì phần lệnh chép
đúng. Đây là kết quả đáng chú ý nhất của phép đo, và nó **không** phải chuyện chính tả:
không lớp sửa từ vựng nào cứu được `Mở cốp` → `Gối`.

Giả thuyết hợp lý nhất: Zipformer cần ngữ cảnh âm học hai bên để quyết một âm tiết; câu
một hơi thở không cho nó gì cả. Chưa kiểm chứng — cần WAV người thật để tách phần này khỏi
phần "Piper đọc câu ngắn không tự nhiên".

## Lớp sửa: lãi bao nhiêu

```
WER trung bình: 0.4831 → 0.4519   (n=16, lớp sửa động vào 1 câu, 0 câu tệ đi)
```

Câu duy nhất nó sửa là đúng ca báo cáo:

```
Vivi ơi dừng nhạc giúp tôi   →  'Cây ây rừng nhạc rút tôi'  →  'Cây ây dừng nhạc rút tôi'
```

Nói cho đủ: **lớp sửa không phải lời giải cho con số 0.45**. Nó đóng đúng một lớp lỗi hẹp
(một âm tiết lệch một ký tự, cạnh một từ neo còn nguyên) và cố ý không làm gì hơn — xem
`src/services/sua_chinh_ta_thoai.py` về việc `của`/`cửa` cũng cách nhau đúng 1.

## Ba cảnh báo về chính con số này

1. **Giọng tổng hợp, không phải người thật.** Piper đọc câu ngắn kém tự nhiên hơn người,
   nên phần "câu ngắn hỏng" có thể bị thổi phồng. Không được trích 0.45 ra ngoài như WER
   của hệ thống.
2. **Piper không tất định.** Cùng câu `Tạm dừng nhạc` ra `'Sang rừng nhạc'` ở lần chạy
   trước và `'Tam rừng nhà'` ở lần sau. So hai cột trong **cùng một run** thì được; so
   giữa hai run thì không.
3. **n = 16.** Đủ để thấy một quy luật, không đủ để đặt ngưỡng.

## Bổ sung 27/08 — false-correction, và tiêu chí phát hành

Review #317 (@thanhpro82) yêu cầu báo **số câu bị sửa sai**, không chỉ WER trung bình. Lý
do đúng và mạnh hơn nó nghe: WER trung bình giấu được đúng cái hại nguy hiểm nhất. Sửa
đúng 5 câu và sửa **sai** 1 câu vẫn ra một con số "cải thiện" — trong khi câu bị sửa sai
có thể là một câu hỏi vừa bị đổi mất ý, và một câu hỏi bị đổi ý thì hệ trả về một câu trả
lời trông hoàn toàn hợp lý cho một câu hỏi khác. Không ai phát hiện ra.

Nên bộ đo thêm nhóm thứ ba — **`cau-hoi`**, 6 câu hỏi sổ tay có chứa chính những âm mà
bảng sửa nhắm tới (`nhạc`, `cốp`, `cửa`, `dừng`) — và tách số theo nhóm. Chạy 27/08,
nguồn Piper, n = 22:

| nhóm | n | WER thô | WER sửa | sửa ĐÚNG | sửa SAI |
|---|---:|---:|---:|---:|---:|
| `cau-hoi` | 6 | 0.1270 | 0.1270 | 0 | **0** |
| `ngan` | 6 | 0.7222 | 0.6667 | 1 | 0 |
| `tu-nhien` | 10 | 0.2619 | 0.2619 | 0 | 0 |
| **tổng** | 22 | 0.3506 | 0.3355 | 1 | **0** |

`FALSE-CORRECTION: 0 câu, trong đó 0 là CÂU HỎI SỔ TAY`. Lớp sửa động vào đúng **1/22**
câu — vẫn là con số ở phần trên, chỉ nay có bằng chứng rằng cái giá của nó bằng 0 trên
nhóm nguy hiểm nhất. Script trả **exit code 1** nếu có bất kỳ câu nào bị sửa sai, kể cả
khi WER trung bình đẹp lên.

Bảng `cau-hoi` cũng cho thấy điều đáng chú ý hơn cả lớp sửa: WER câu hỏi (0.127) thấp hơn
**gấp năm lần** WER lệnh ngắn (0.722) trên cùng một engine. Nghĩa là vấn đề không phải
"Zipformer yếu", mà "Zipformer yếu ở phát ngôn ngắn" — đúng giả thuyết ở phần trên, giờ
có thêm một nhóm đối chứng.

### Cờ `stt_correction_enabled`, mặc định TẮT

Đường thoại thật gọi `voice.transcribe`, nhưng hàm ấy đọc cờ và mặc định `False` — nên
trên mọi checkout như-ship nó **đúng bằng** `transcribe_raw`. Có test khoá cả hai nửa:
mặc định repo phải là `False`, và chỗ gọi trong `turns.py` phải là `voice.transcribe`
(công tắc không nằm trên đường thật thì nó là code chết).

Ba điều kiện để lật cờ, phải đủ **cả ba** — ghi trong `src/config.py` cạnh chính cờ đó:

1. WAV **người thật** cho cả nhóm ngắn và nhóm tự nhiên, A/B trên đúng cùng bộ audio.
2. WER corrected < WER raw trên bộ ấy.
3. `false-correction` trên nhóm `cau-hoi` = **0**.

Hôm nay đạt (2) và (3) nhưng **không** đạt (1), nên script tự in `CHƯA đủ, giữ cờ tắt`.
Điều kiện (1) cần người thật ngồi ghi — không tự động hoá được, và đó là việc chặn duy
nhất còn lại.

## Việc tiếp theo, theo thứ tự giá trị

1. **Ghi WAV người thật** cho đúng 6 câu ngắn ở bảng trên (@hason0510). Chạy
   `scripts\do_wer_sua_chinh_ta.py --nguon <thư mục>` — script đã có sẵn đường đọc thư mục
   `.wav` + `.txt`. Đây là thứ tách được "Zipformer yếu ở câu ngắn" khỏi "Piper đọc dở".
2. Nếu quy luật đúng với người thật: hướng sửa **không** nằm ở STT mà ở IVI — gợi ý người
   dùng nói cả câu, hoặc ghép wake-phrase vào audio gửi lên STT thay vì cắt bỏ nó.
3. Lớp sửa chính tả giữ nguyên phạm vi hẹp; mở rộng bảng cụm chỉ khi có ca thật.
