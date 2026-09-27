# `cham_slm` — WAV của câu **trượt luật router**

Sinh bằng `scripts/generate_voice_wer_fixtures.py --bo cham_slm` (Piper `vi_VN`,
16 kHz mono 16-bit, 1,36–1,96 s), ngày 2026-08-25.

## Vì sao có bộ này bên cạnh `synthetic_commands/`

Cả 5 câu của `synthetic_commands/` đều **khớp luật tất định** (`"Bật điều hòa"`,
`"Mở cửa sổ bên phụ một nửa"`…). Đo đường thoại bằng chúng là đo
STT → router → executor → TTS và **không bao giờ chạm SLM** — ra một con số đẹp về
một đường không ai hỏi tới.

Điều kiện 3 của PM/PO review PR #257 đòi đo end-to-end *gồm cả STT/TTS*, mà phần đắt
nhất của lượt thật nằm ở SLM. Bộ này phủ ba đường còn lại, cùng nhãn với `CASES`
trong `scripts/do_luot_that_dong_thoi.py` để hai phép đo (text và voice) so được với
nhau theo từng đường.

| File | Nhãn | Câu |
|---|---|---|
| `cau_00.wav` | `so_tay` | Xe này sạc nhanh mất bao lâu |
| `cau_01.wav` | `so_tay` | Áp suất lốp tiêu chuẩn là bao nhiêu |
| `cau_02.wav` | `planner` | Làm cho trong xe dễ chịu hơn tí đi |
| `cau_03.wav` | `planner` | Trong xe ngột ngạt quá, xử lý giúp tôi |
| `cau_04.wav` | `chitchat` | Chào xe, hôm nay thế nào |

## STT nghe lại ra gì — đo 2026-08-25, phải đọc trước khi dùng số

Backend **không** nhận câu gốc; nó nhận thứ Zipformer nghe ra. Loopback tại chỗ
(`transcribe_raw` trên chính 5 file này, máy dev):

| File | Nghe thành | WER |
|---|---|---:|
| `cau_00` | Xe này sạc nhanh mất bao lâu | **0,000** |
| `cau_01` | Áp suất **rút** tiêu chuẩn là bao nhiêu | 0,125 |
| `cau_02` | Làm cho **chóng** xe dễ chịu hơn tí đi | 0,111 |
| `cau_03` | Trong xe ngột ngạt quá xử lý **rút tồi** | 0,222 |
| `cau_04` | Chào **sệ** hôm nay thế nào | 0,167 |

Cả 5 vẫn **rơi đúng làn** đã định: `cau_00`/`cau_01` vẫn là câu hỏi sổ tay,
`cau_02`/`cau_03` vẫn trượt luật nên xuống planner, `cau_04` vẫn là xã giao. Nên bộ
này dùng đo độ trễ được.

Nhưng hai chỗ phải nhớ khi đọc kết quả:

1. **`cau_01` mất chữ "lốp"** — RAG tra bằng câu đã méo, nên chất lượng câu trả lời
   của nó **không** so được với cùng câu ở chế độ `text`. Chỉ so độ trễ.
2. **Đây là WER của giọng tổng hợp**, không phải của người thật. Piper nói rõ ràng
   hơn người; WER người thật sẽ cao hơn. `CLAUDE.md`: *"synthetic Piper audio is not
   human-speaker WER"*.

## Đừng sinh lại nếu không cần

`PiperEngine.synthesize()` **không tất định** giữa các lần gọi. Sinh lại là đổi chính
đầu vào của mọi phép đo đã chạy với bộ này, và bảng loopback ở trên hết đúng.
