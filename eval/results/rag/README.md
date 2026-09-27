# Kết quả eval RAG sổ tay VF9

> Đo ngày 2026-08-07 trên `eval/datasets/manual/v1` (40 positive + 20 negative).
> Tái lập: `python -m src.rag.cli eval`

## Ingestion

| Chỉ số | Giá trị |
|---|---|
| Mục sổ tay | 58 |
| Chunk | 482 |
| Vector | 536 |
| **page_resolved_rate** | **100,0%** (cổng ≥ 95%) |
| — trong đó exact / fuzzy / derived | 482 / 0 / 0 |
| Mục kém nhất | 100,0% (cổng ≥ 80%) |
| Số trang tăng dần trong mục | 58/58 |
| Edition | `VF9_23-25_VN_VI_2.4 [New UI]` |
| **Token/cửa sổ embed** | median 282, **max 485** (trần 512) |

## Khắc phục 2 nguy cơ từ review PR #10

### #1 Token overflow — đã sửa, có mất dữ liệu trước đó

Bản đầu cắt cửa sổ theo **ký tự** (`WINDOW_CHARS = 1600`) dựa trên tỷ lệ trung
bình 3,56 ký tự/token. Đo lại cho thấy tỷ lệ thật dao động **2,41–4,21**, nên
1.600 ký tự có thể ra tới 665 token. Kết quả: **5/557 cửa sổ vượt 512 token**,
`SentenceTransformer` cắt cụt im lặng và phần đuôi biến mất khỏi index.

Đã chuyển sang cắt theo **token thật** (`Embedder.split_for_embedding` dùng
offset mapping của chính tokenizer).

| | Trước | Sau |
|---|---:|---:|
| Cửa sổ | 557 | 536 |
| Token/cửa sổ tối đa | **611** | **485** |
| Cửa sổ vượt 512 token | **5** | **0** |

Nội dung có tỷ lệ ký tự/token thấp nhất đúng là bảng thông số và danh sách số
liệu — chữ số và đơn vị tokenize rất dày. Dùng tỷ lệ trung bình là sai ngay từ
gốc; ngưỡng ký tự trong `chunker.py` từ nay chỉ còn ý nghĩa **ngữ nghĩa**.

### #2 Fragile page mapping — đã thêm bậc dự phòng và bỏ im lặng

So khớp chuỗi con chính xác vốn rất giòn. Trước khi sửa, phân bố số mồi khớp cho
thấy **3 chunk chỉ sống nhờ đúng 1/4 mồi** — lệch một ký tự là rơi thẳng xuống
`DERIVED`, mượn trang chunk trước và sinh citation sai mà không có tín hiệu nào.

Ba thay đổi:

1. Thêm bậc **`FUZZY`** (`difflib`, ngưỡng phủ 0,85) chạy khi khớp chính xác trượt.
2. Cổng chất lượng thành **hai tầng**: toàn cục ≥ 95% **và** từng mục ≥ 80%. Cổng
   toàn cục một mình cho phép một mục hỏng nấp sau 57 mục tốt.
3. `verify` liệt kê mọi chunk `FUZZY`/`DERIVED` kèm section và trang để kiểm tay.

Trên corpus hiện tại vẫn 100% `EXACT` nên bậc `FUZZY` chưa phải dùng — nó là lưới
an toàn cho lần sổ tay đổi phiên bản.

### Tác động lên retrieval: không có

Sửa cắt cụt làm đổi vector của 5 cửa sổ nên bắt buộc phải hiệu chỉnh lại. Kết quả
đo lại: **mọi chỉ số giữ nguyên**, cùng đúng một case negative trượt (`RAG-209`).
`calibrate` gợi ý `min_score = 0.840` nhưng cho kết quả **hệt như** 0.848, nên
giữ nguyên 0.848 vì chặt hơn.

## Retrieval (tầng 1 — không cần LLM)

Ngưỡng đã hiệu chỉnh: `min_score = 0.848`, `min_overlap = 0.65`.

| Chỉ số | Đo được | Mục tiêu | Kết quả |
|---|---:|---:|:--:|
| recall@k | 100,0% | — | — |
| grounded_rate | 100,0% | > 90% | ✅ |
| citation_validity | 100,0% | = 100% | ✅ |
| hallucination_rate | 5,0% | < 5% | ❌ |

**Đúng một case negative lọt: RAG-209 "Làm sao bật chế độ tàng hình cho xe?"**

## Vì sao ngưỡng đơn không đủ, và vì sao vẫn còn 5%

Thang điểm cosine của `multilingual-e5-small` rất nén: positive 0,879–0,907 còn
negative 0,779–0,872. Quét ngưỡng điểm đơn thuần cho kết quả tốt nhất là
**grounded 92,5% / hallucination 20,0%** — trượt xa mục tiêu.

Thêm điều kiện trùng từ vựng (giữ nguyên dấu thanh) kéo hallucination từ 20%
xuống 5% mà không mất positive nào. Lưu ý: bản `fold()` bỏ dấu **không dùng
được** cho việc này vì nó biến "bò" và "bỏ" thành cùng một từ.

Case còn lại không giải được ở tầng retrieval. "Làm sao bật chế độ tàng hình cho
xe" chỉ có duy nhất từ "tàng" là lạ; "bật", "chế", "độ", "hình" đều xuất hiện dày
đặc trong sổ tay. Đây là hạn chế của so khớp **đơn âm tiết** trong tiếng Việt.

Đã thử bigram: hallucination về 0% nhưng grounded tụt còn đúng 90,0% (cần **>**
90%), vì loại nhầm các câu hỏi ngắn hợp lệ như *"Nghe đài FM trên xe thế nào?"*.
Kết hợp cả ba tín hiệu cũng không tách được.

**Kết luận: chặn nốt 5% còn lại là việc của tầng generator, không phải retrieval.**
Đúng như `safety_and_hitl.md` mô tả — văn bản truy hồi là dữ liệu không đáng tin,
và phòng thủ nằm ở bộ sinh câu trả lời (tool bị disable, chỉ dùng evidence), chứ
không nằm ở bộ truy hồi.

## Điểm vận hành: vì sao chọn recall cao thay vì precision cao

Có hai điểm vận hành khả dĩ:

| Điểm | grounded | hallucination |
|---|---:|---:|
| **Đang dùng** (score 0,848 / overlap 0,65) | 100,0% | 5,0% |
| Thay thế (bigram ≥ 0,30) | 90,0% | 0,0% |

Chọn điểm đầu vì **false-accept ở tầng 1 còn cứu được** — generator được yêu cầu
từ chối khi evidence không trả lời được câu hỏi. Còn **false-reject là mất hẳn**:
evidence không bao giờ tới được generator. Tầng 1 nên ưu tiên recall, tầng 2 siết
precision.

## ⚠ Cảnh báo phương pháp

Ngưỡng được hiệu chỉnh **trên chính 60 case này**, nên con số ở trên là ước lượng
**lạc quan**. Muốn có số trung thực cần một bộ giữ riêng (held-out) chưa từng
dùng để chọn ngưỡng. Đây là việc nên làm trước khi đưa số vào báo cáo cuối.

## Chưa làm

- **Tầng 2 (generation)**: `grounded_rate`/`hallucination_rate` có LLM trong vòng
  lặp — đang chờ [ADR-005](../../docs/adr/ADR-005-model-profile-selection.md) chốt model.
- **RAGAS**: 4 metric cho báo cáo, chạy online một lần, ngoài critical path.
- **Bộ eval held-out** để khử overfit ngưỡng.
