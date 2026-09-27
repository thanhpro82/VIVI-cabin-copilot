"""Thác chọn câu hai tầng: E5 thu hẹp, cross-encoder chấm lại.

## Vì sao là thác chứ không phải một tầng

Đo 17–18/08 trên cùng một bộ khoá, tất cả trên CPU máy dev:

| Cách chọn        | Loại        | F1  | Độ trễ |
|------------------|-------------|-----|--------|
| Luật hiện tại    | tất định    | 46% | 0 ms   |
| Qwen 3B          | sinh chữ    | 53% | 2773 ms|
| E5 một mình      | bi-encoder  | 51% | 168 ms |
| **E5 lọc 4 → bge** | **thác**  | **58%** | **1018 ms** |

Thác **tốt hơn cross-encoder chạy một mình** chứ không chỉ rẻ hơn: E5 vứt bớt câu
nhiễu trước khi mô hình đắt tiền nhìn tới. Và cả hai tầng đều là encoder — chúng chỉ
trả về **con số**, nên về cấu tạo không bịa được chữ nào. Đó là điều kiện để đường
này sống sót sau khi ADR-015 bác phương án cho SLM viết lại đoạn.

## Vì sao chấm câu chứ không chấm đoạn

Cross-encoder tốn tuyến tính theo độ dài chuỗi. Đo 18/08: một **câu** (~40 token)
tốn ~140 ms fp32, còn một **chunk** nguyên (p50 273 token, p90 476) tốn ~1386 ms.
Rerank 8 chunk mất 11 giây — quá ngân sách p50 2500 ms cả bậc độ lớn. Cùng mô hình
này chỉ chạy nổi trên CPU khi đầu vào là câu. Rerank đoạn cần GPU và là việc khác.

## int8 động

`quantize_dynamic` giảm còn ~69 ms/câu (2x) và trong phép thử đầu tiên top-2 không
đổi so với fp32. Trọng số int8 cũng chỉ chiếm ~1/4 RAM — đáng kể trên máy 7,4 GB
đang chạy sẵn backend, IVI, broker và llama-server. Mặc định BẬT; tắt được để đối
chứng khi nghi ngờ lượng tử hoá làm lệch thứ hạng.

## Điều thác này KHÔNG làm

Nó không giữ câu CẢNH BÁO. Đo 18/08 với câu hỏi *"Bánh xe bị xịt giữa đường thì xử
lý sao"*: bge xếp câu "CẢNH BÁO Không sử dụng Bộ bơm hơi… thành bên của lốp" xuống
**hạng 5**, vì cảnh báo ít trùng chữ với câu hỏi. Đây là bài toán riêng, thuộc lớp
tóm tắt/thẩm định, không phải bài toán xếp hạng.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Số câu E5 giữ lại cho cross-encoder. 4 là con số của phép đo trong bảng trên;
#: rộng hơn thì tuyến tính đắt thêm mà chưa đo được lợi.
POOL_MAC_DINH = 4

#: Số câu nói ra. Khớp `_TOI_DA_CAU` của `speech_policy` — hai chỗ phải cùng ý,
#: nhưng không import chéo vì đó là hằng của tầng nói, còn đây là hằng của tầng chọn.
TOP_MAC_DINH = 2

#: Trần token mỗi cặp (câu hỏi, câu). Câu sổ tay dài nhất đo được ~120 token, nên 512
#: là dư — giữ để một chunk lọt vào đây do lỗi gọi thì bị cắt chứ không làm treo lượt.
MAX_LENGTH = 512


class ThacChonCau:
    """`SentenceSelector` chạy hoàn toàn trong tiến trình, không gọi mạng.

    Khác `QwenSentenceSelector` ở chỗ không có llama-server để hỏng, nhưng vẫn giữ
    đúng hợp đồng "không có ý kiến": mọi lỗi trả `[]` để `speech_policy` rơi về luật
    S1. Một lượt tra sổ tay không được chết vì tầng xếp hạng.

    Lưu ý về `reason`: `speech_policy._chon_bang_slm` ghi `reason="slm"` cho mọi
    selector, kể cả thác này vốn không sinh chữ. Chuỗi ấy nghĩa là "model đã chọn",
    không phải "SLM đã viết". Không đổi tên vì nó là khoá cột trong eval cũ.
    """

    def __init__(
        self,
        model_dir: str | Path,
        embedder: Any,
        *,
        pool: int = POOL_MAC_DINH,
        top: int = TOP_MAC_DINH,
        int8: bool = True,
        max_length: int = MAX_LENGTH,
    ) -> None:
        self._model_dir = Path(model_dir)
        self._embedder = embedder
        self._pool = max(1, pool)
        self._top = max(1, top)
        self._int8 = int8
        self._max_length = max_length
        self._nap: tuple[Any, Any] | None = None

    def _mo_hinh(self) -> tuple[Any, Any]:
        """Nạp trễ. Import torch/transformers ở đây, không ở đầu tệp.

        `speech_policy` được import trên mọi đường của composer, kể cả lượt điều
        khiển không đụng sổ tay. Kéo torch vào lúc import module là bắt mọi lượt trả
        tiền cho một tầng mà phần lớn lượt không dùng.
        """
        if self._nap is None:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            tok = AutoTokenizer.from_pretrained(str(self._model_dir))
            mod = AutoModelForSequenceClassification.from_pretrained(str(self._model_dir), dtype=torch.float32).eval()
            if self._int8:
                # torch cảnh báo `torch.ao.quantization` sẽ bị gỡ ở 2.10. Khi điều đó
                # xảy ra, suy giảm về fp32 chứ đừng tắt cả tầng xếp hạng: fp32 chỉ
                # chậm gấp đôi và tốn RAM gấp bốn, còn không có thác thì mất hẳn
                # 12 điểm F1. Chậm hơn vẫn tốt hơn không có.
                try:
                    mod = torch.ao.quantization.quantize_dynamic(mod, {torch.nn.Linear}, dtype=torch.qint8)
                except Exception:
                    logger.warning("không lượng tử hoá được, dùng fp32", exc_info=True)
            self._nap = (tok, mod)
        return self._nap

    def _thu_hep(self, question: str, sentences: list[str]) -> list[int]:
        """Tầng 1: E5 giữ lại `pool` câu.

        Câu hỏi đi qua `embed_query`, câu sổ tay đi qua `embed_passages`. Bất đối
        xứng này **bắt buộc**: E5 gắn tiền tố `query:`/`passage:` khác nhau, và đo
        17/08 cho thấy dùng nhầm `embed_query` cho cả hai vế kéo F1 từ 51% xuống 42%.
        """
        vq = self._embedder.embed_query(question)
        vs = self._embedder.embed_passages(sentences)
        diem = [float(v @ vq) for v in vs]  # E5 chuẩn hoá L2 nên tích vô hướng là cosine
        return sorted(range(len(sentences)), key=lambda i: -diem[i])[: self._pool]

    def _cham(self, question: str, sentences: list[str], chi_so: list[int]) -> list[int]:
        """Tầng 2: cross-encoder chấm lại `chi_so`, trả về `top` chỉ số tốt nhất."""
        import torch

        tok, mod = self._mo_hinh()
        cap = [(question, sentences[i]) for i in chi_so]
        with torch.no_grad():
            enc = tok(cap, padding=True, truncation=True, max_length=self._max_length, return_tensors="pt")
            diem = mod(**enc).logits.squeeze(-1).reshape(-1).tolist()
        xep = sorted(range(len(chi_so)), key=lambda k: -diem[k])[: self._top]
        return [chi_so[k] for k in xep]

    def select(self, question: str, sentences: list[str]) -> list[int]:
        """Trả chỉ số câu nên nói. `[]` nghĩa là không có ý kiến."""
        if not sentences:
            return []
        # Đoạn ngắn hơn số câu sẽ nói thì không có gì để chọn. Trả hết ra thay vì `[]`
        # để `speech_policy` vẫn đi đường model — `[]` sẽ bị ghi là `slm_output_rejected`
        # và làm cột eval trông như model hỏng.
        if len(sentences) <= self._top:
            return list(range(len(sentences)))
        try:
            hep = self._thu_hep(question, sentences)
            return sorted(self._cham(question, sentences, hep))
        except Exception:
            logger.warning("thác chọn câu hỏng, rơi về luật S1", exc_info=True)
            return []
