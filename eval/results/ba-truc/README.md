# Bàn cân ba trục — nhánh sổ tay

Ba trục, không có con số tổng: **độ trễ · độ chính xác · độ tự nhiên**. Gộp lại thành
một điểm là mất đúng thứ cần thấy — sự đánh đổi.

Sinh lại: `python scripts/ban_do_ba_truc.py`

## Các run được giữ

| run | vai trò |
|---|---|
| `20260818T165614Z` | **mốc gốc** — luật S1 như trước vòng tối ưu: chính xác 46%, tự nhiên **18%** |
| `20260818T174525Z` | **quét 13 cấu hình** — nền tảng của kết luận "mọi tầng neural đều kém hơn luật" |
| `20260818T165854Z` | sau khi dọn định dạng — tự nhiên 18% → **92%**, chính xác chưa đổi |
| `20260818T174938Z` | luật đã là mặc định production, so với thác và với chỉ-E5 |
| `20260818T175702Z` | **chốt** — mặc định production: 64% / 100% / 0 ms |

## Vì sao các run khác đã bị xoá trước khi commit

Chúng chưa từng được commit, và mỗi cái chạy trên một bàn cân còn lỗi:

- các run trước `165614Z` khớp chunk bằng văn bản thô nên **39/39 ca trượt khớp**, mọi
  cờ `has_variant_condition` rơi về `False`, tức đo một hệ thống **không có cổng biến
  thể**;
- các run giữa dùng `pool=4` cho cross-encoder trong khi `top=4`, tức reranker chấm
  đúng 4 câu rồi trả cả 4 — **vô tác dụng** mà bảng vẫn in ra một con số trông như đã
  đo nó.

Giữ chúng lại là để những con số ấy sống trong repo với cùng thẩm quyền như số đúng.
