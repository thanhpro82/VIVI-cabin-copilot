r"""Đo WER của STT **có** và **không** lớp sửa chính tả, trên cùng một bộ audio.

Đây là điều kiện chặn số 2 của issue "STT nghe Dừng nhạc thành Rừng nhạc": không có
hai con số cạnh nhau thì không biết lớp sửa lãi hay lỗ.

## Hai nguồn audio

- `--nguon piper` (mặc định): tổng hợp câu lệnh bằng chính Piper của repo rồi resample
  về 16 kHz mono. Chạy được ở mọi máy có model voice, **nhưng đây là giọng máy** —
  con số ra không phải WER của người thật, và không được trình bày như vậy.
- `--nguon <thư mục>`: đọc `*.wav` 16 kHz mono, mỗi file kèm một `.txt` cùng tên chứa
  câu gốc. Đây là đường dành cho WAV người thật khi có.

## Chạy

```powershell
.\.venv\Scripts\python.exe scripts\do_wer_sua_chinh_ta.py
.\.venv\Scripts\python.exe scripts\do_wer_sua_chinh_ta.py --nguon data\wav_nguoi_that
```
"""

from __future__ import annotations

import argparse
import io
import sys
import wave
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    # Cùng lý do như scripts/validate_mqtt_schemas.py: stdout là pipe trên Windows sẽ
    # dùng cp1252 và giết script vì dấu tiếng Việt.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services import voice  # noqa: E402
from src.services.sua_chinh_ta_thoai import sua_theo_cum  # noqa: E402

#: Câu lệnh dùng khi tổng hợp bằng Piper. Chọn theo bề mặt điều khiển thật
#: (`docs/coverage_matrix.md`), không phải câu ngẫu nhiên.
#:
#: **Hai nhóm, và sự khác nhau giữa chúng là kết quả chính của phép đo này.** Nhóm
#: `NGAN` là lệnh trần 2–3 từ; nhóm `TU_NHIEN` là cùng những lệnh ấy trong câu người
#: thật nói (có tiếng gọi, có đuôi lịch sự). Đo 26/08: STT chép **hỏng gần hết** nhóm
#: đầu và chép **đúng phần lệnh** ở nhóm sau — nên một bộ đo chỉ có câu trần sẽ kết
#: luận sai về cả STT lẫn lớp sửa.
NGAN: tuple[str, ...] = (
    "Dừng nhạc",
    "Bật nhạc",
    "Tắt nhạc",
    "Chuyển bài",
    "Mở cốp",
    "Tăng âm lượng",
)

TU_NHIEN: tuple[str, ...] = (
    "Vivi ơi dừng nhạc giúp tôi",
    "Vivi ơi bật nhạc giúp tôi",
    "Vivi ơi tắt nhạc giúp tôi",
    "Vivi ơi chuyển bài giúp tôi",
    "Vivi ơi mở cốp giúp tôi",
    "Vivi ơi tăng âm lượng giúp tôi",
    "Bật điều hòa hai mươi hai độ giúp mình",
    "Mở cửa sổ bên lái ba mươi phần trăm",
    "Bật đèn chiếu gần giúp mình",
    "Đặt âm lượng bốn mươi phần trăm",
)

#: Câu **hỏi sổ tay** — nhóm mà một lần sửa sai gây hại nặng nhất, và là điều kiện
#: chặn số 2 của review #317.
#:
#: Vì sao tách riêng thay vì gộp vào WER trung bình: một lệnh chép sai thì tài xế thấy
#: xe làm sai và nói lại ngay. Một câu hỏi bị lớp sửa **đổi ý** thì hệ trả về một câu
#: trả lời trông hoàn toàn hợp lý — cho một câu hỏi khác. Không ai phát hiện ra, và WER
#: trung bình còn có thể *đẹp lên* trong lúc đúng cái hại ấy xảy ra.
#:
#: Chọn câu có chứa chính những âm mà bảng sửa nhắm tới (`nhạc`, `cốp`, `cửa`, `dừng`),
#: để nếu lớp sửa quá tay thì nó lộ ra ở đây trước.
CAU_HOI: tuple[str, ...] = (
    "Xe có chức năng dừng khẩn cấp không",
    "Cốp sau mở bằng cách nào",
    "Cửa sổ trời hoạt động thế nào",
    "Nhạc từ USB có phát được không",
    "Đèn báo lốp non hơi nghĩa là gì",
    "Chế độ lái tiết kiệm khác gì chế độ thể thao",
)

CAU_MAU: tuple[str, ...] = NGAN + TU_NHIEN + CAU_HOI

#: `câu gốc -> nhóm`. Dùng để tách số liệu theo nhóm ở bảng cuối.
NHOM: dict[str, str] = {
    **{c: "ngan" for c in NGAN},
    **{c: "tu-nhien" for c in TU_NHIEN},
    **{c: "cau-hoi" for c in CAU_HOI},
}


def ve_16k_mono(wav_bytes: bytes) -> bytes:
    """Ép WAV về 16 kHz mono 16-bit — dạng duy nhất `voice._validate_audio` nhận."""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise ValueError(f"chỉ nhận WAV 16-bit, gặp {sw * 8}-bit")
    mau = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        mau = mau.reshape(-1, ch).mean(axis=1).astype(np.int16)
    if sr != 16000:
        n_moi = int(len(mau) * 16000 / sr)
        mau = np.interp(
            np.linspace(0, len(mau) - 1, n_moi), np.arange(len(mau)), mau.astype(np.float64)
        ).astype(np.int16)
    ra = io.BytesIO()
    with wave.open(ra, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(mau.tobytes())
    return ra.getvalue()


def _bo_piper() -> list[tuple[str, bytes]]:
    return [(cau, ve_16k_mono(voice.synthesize_wav(cau))) for cau in CAU_MAU]


def _bo_thu_muc(thu_muc: Path) -> list[tuple[str, bytes]]:
    bo: list[tuple[str, bytes]] = []
    for wav in sorted(thu_muc.glob("*.wav")):
        txt = wav.with_suffix(".txt")
        if not txt.is_file():
            print(f"  bỏ qua {wav.name}: thiếu {txt.name}")
            continue
        bo.append((txt.read_text(encoding="utf-8").strip(), ve_16k_mono(wav.read_bytes())))
    if not bo:
        raise SystemExit(f"không có cặp .wav/.txt nào trong {thu_muc}")
    return bo


def _nhom_cua(goc: str) -> str:
    """Nhóm của một câu. WAV người thật đọc nhãn từ `NHOM`; câu lạ vào `khac`."""
    return NHOM.get(goc, "khac")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nguon", default="piper", help="'piper' hoặc đường dẫn thư mục WAV")
    args = parser.parse_args()

    bo = _bo_piper() if args.nguon == "piper" else _bo_thu_muc(Path(args.nguon))

    tong_truoc = tong_sau = 0.0
    so_sua = 0
    # `nhóm -> [wer_truoc, wer_sau, n, sua_dung, sua_sai]`.
    #
    # `sua_sai` (false-correction) là con số phải báo **riêng** — điều kiện chặn số 2
    # của review #317. Định nghĩa: lớp sửa có động vào câu **và** WER sau cao hơn WER
    # trước. WER trung bình một mình giấu được nó: sửa đúng 5 câu và sửa sai 1 câu vẫn
    # ra một con số "cải thiện", trong khi câu bị sửa sai có thể là một câu hỏi vừa bị
    # đổi mất ý.
    theo_nhom: dict[str, list[float]] = {}
    sua_sai_chi_tiet: list[str] = []
    print(f"{'nhóm':9s} {'câu gốc':34s} {'STT thô':34s} {'sau lớp sửa':34s} {'WER':>12s}")
    print("-" * 128)
    for goc, wav in bo:
        nhom = _nhom_cua(goc)
        tho = voice.transcribe_raw(wav).text
        sau = sua_theo_cum(tho)
        w_truoc = voice.word_error_rate(goc, tho)
        w_sau = voice.word_error_rate(goc, sau)
        tong_truoc += w_truoc
        tong_sau += w_sau
        o = theo_nhom.setdefault(nhom, [0.0, 0.0, 0.0, 0.0, 0.0])
        o[0] += w_truoc
        o[1] += w_sau
        o[2] += 1
        if sau != tho:
            so_sua += 1
            if w_sau > w_truoc:
                o[4] += 1
                sua_sai_chi_tiet.append(f"  [{nhom}] {goc!r}\n      thô: {tho!r}\n      sửa: {sau!r}")
            elif w_sau < w_truoc:
                o[3] += 1
        dau = "" if w_sau == w_truoc else ("  ↓" if w_sau < w_truoc else "  ↑ TỆ ĐI")
        print(f"{nhom:9s} {goc:34s} {tho:34s} {sau:34s} {w_truoc:.2f}→{w_sau:.2f}{dau}")

    n = len(bo)
    print("-" * 128)
    print(f"{'nhóm':9s} {'n':>3s} {'WER thô':>9s} {'WER sửa':>9s} {'sửa ĐÚNG':>9s} {'sửa SAI':>8s}")
    for nhom, (t, s_sau, m, dung, sai) in sorted(theo_nhom.items()):
        print(f"{nhom:9s} {int(m):3d} {t / m:9.4f} {s_sau / m:9.4f} {int(dung):9d} {int(sai):8d}")
    print(f"\nWER trung bình: {tong_truoc / n:.4f} → {tong_sau / n:.4f}   (n={n}, lớp sửa động vào {so_sua} câu)")

    sua_sai_hoi = int(theo_nhom.get("cau-hoi", [0.0] * 5)[4])
    tong_sua_sai = sum(int(o[4]) for o in theo_nhom.values())
    print(f"FALSE-CORRECTION: {tong_sua_sai} câu, trong đó {sua_sai_hoi} là CÂU HỎI SỔ TAY")
    if sua_sai_chi_tiet:
        print("\n".join(sua_sai_chi_tiet))

    if args.nguon == "piper":
        print(
            "\nLƯU Ý: đây là giọng TỔNG HỢP (Piper), không phải người thật. Con số này chỉ"
            "\ndùng để so hai cột với nhau, KHÔNG được trích ra như WER của hệ thống."
        )

    # Ba tiêu chí bật mặc định `stt_correction_enabled` (xem `src/config.py`). Nguồn
    # `piper` **không bao giờ** đủ điều kiện 1, nên ở đó dòng này chỉ báo cáo — nó không
    # có thẩm quyền phán quyết, và viết ra như thế để không ai đọc nhầm.
    du_so = tong_sau < tong_truoc and sua_sai_hoi == 0
    print(
        f"\nTiêu chí bật mặc định: WER giảm={tong_sau < tong_truoc}  "
        f"sửa-sai-câu-hỏi=0 là {sua_sai_hoi == 0}  "
        f"WAV người thật={args.nguon != 'piper'}  -> "
        + ("ĐỦ ĐIỀU KIỆN đề nghị bật" if du_so and args.nguon != "piper" else "CHƯA đủ, giữ cờ tắt")
    )
    # Sửa sai một câu nào cũng là fail, kể cả khi WER trung bình đẹp lên.
    return 0 if tong_sau <= tong_truoc and tong_sua_sai == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
