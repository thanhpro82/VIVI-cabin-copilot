# Smoke test payload giọng nói — run `20260817T043442.858549Z`

- Commit `82e549804616` trên `feat/evidence-voice-payload` (**cây làm việc bẩn**)
- Python 3.11.9 · Windows-10-10.0.26200-SP0
- Trần khung client: **1024 KiB** (mặc định `websockets`, không nới)

## Kết quả

| lượt | speak_text | audio | thời lượng | khung WS | % khung |
|---|---|---|---|---|---|
| `voice` | — (lượt giọng nói) | 69.0 KiB | 1.6 s | **92.4 KiB** | 9.0% |
| `rag_dai` | 237 ký tự | 487.5 KiB | 11.32 s | **650.4 KiB** | 63.5% |
| `rag_doc_tiep` | 203 ký tự | 397.0 KiB | 9.22 s | **529.7 KiB** | 51.7% |

**Client vẫn kết nối: CÓ**

Đây là vế mà một phép đo payload thuần không nói được: `max_size` để nguyên mặc định,
nên một event vượt khung sẽ đóng kết nối mã 1009 và hiện ra ở dòng trên chứ không phải
suy ra từ số byte.

## Độ trễ theo tầng (do `TraceStore` ghi, không phải đồng hồ ngoài)

`end_to_end` **nhỏ hơn** `tts` không phải lỗi: nó được chốt trước khi TTS chạy, nên
TTS cố ý không nằm trong đó (`CLAUDE.md`, mục observability). Muốn thời gian tài xế
thật sự chờ tới lúc nghe được tiếng thì cộng hai cột — nhưng con số ấy repo chưa
định nghĩa, nên tôi không tự đặt ra ở đây.

| lượt | stt | tts | end_to_end |
|---|---|---|---|
| `voice` | 48.4 | 92.3 | 82.8 |
| `rag_dai` | — | 715.1 | 41.0 |
| `rag_doc_tiep` | — | 589.0 | 8.1 |

## Điểm mù

- **giong** — Piper tổng hợp, không phải người nói — không suy ra WER từ run này.
- **mang** — loopback trên một máy; không có độ trễ mạng, không có mất gói.
- **phan_cung** — một máy Windows dev. Con số byte phụ thuộc giọng và tần số lấy mẫu.
- **so_luot** — ba lượt, không phải phân bố. Đây là smoke test, không phải benchmark.
