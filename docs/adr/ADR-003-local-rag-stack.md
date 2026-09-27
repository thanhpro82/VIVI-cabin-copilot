# ADR-003: Local Grounded RAG with FAISS and SQLite Metadata

- Status: Accepted
- Date: 2026-07-30

## Context

Câu trả lời sổ tay phải grounded, có citation và chạy offline. Dataset nhỏ theo một/few manual; nhóm bốn người cần stack đơn giản, dễ version và không phải vận hành vector database service riêng.

## Alternatives

| Option | Pros | Cons |
|---|---|---|
| Full manual trong prompt | Dễ prototype | Context lớn, chậm, khó cite và không scale |
| Chroma local | Metadata/filter API tiện | Thêm service/library state và migration |
| **FAISS + SQLite metadata** | Nhẹ, local, artifact dễ version | Cần tự viết metadata filter/citation resolver |
| Cloud vector DB | Quản trị tốt | Vi phạm offline và tăng dependency |

## Decision

Dùng `multilingual-e5-small` để embed local, FAISS cho vector retrieval và SQLite/chunk store cho document/section/page/checksum. Ingestion tạo manifest/version. Query retrieve top 8, grade, giữ tối đa 5 chunks; generator chỉ dùng evidence và citation resolver validate trước response.

Model card của multilingual-e5-small mô tả multilingual support và yêu cầu prefixes cho asymmetric retrieval: [official model card](https://huggingface.co/intfloat/multilingual-e5-small).

## Rationale

- Phù hợp dataset local nhỏ và offline runtime.
- Citation metadata không bị nhét vào vector index một cách khó kiểm soát.
- Artifact có thể checksum/rebuild và so regression.
- Giảm operational scope trong bốn tuần.

## Consequences

- Nhóm phải xây citation resolver và index manifest.
- Filter theo vehicle profile/manual edition chạy ở application layer.
- Score threshold không hardcode từ trực giác; hiệu chỉnh bằng positive/negative eval.
- PDF scan/OCR chất lượng kém phải được chuẩn hóa trước ingestion.
- Chroma vẫn là phương án dự phòng nếu quản trị metadata trở thành blocker.

## Revisit when

- Có hàng nghìn manual/vehicle variants hoặc concurrent writers.
- Cần hybrid BM25/vector/reranking phức tạp.
- FAISS metadata filtering/application code trở nên khó duy trì.

