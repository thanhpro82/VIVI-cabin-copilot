r"""Ghi WAV người thật cho bộ đo STT — 16 kHz mono 16-bit, đúng dạng backend nhận.

Sinh ra thư mục `<đích>/` gồm từng cặp `NN-<slug>.wav` + `NN-<slug>.txt`, đúng dạng
`scripts/do_wer_sua_chinh_ta.py --nguon <thư mục>` đọc được.

## Vì sao không ghi bằng Voice Recorder của Windows rồi convert

Ghi thẳng ở 16 kHz mono thì bỏ được một bước convert — và bước ấy là chỗ hay hỏng:
Voice Recorder xuất `.m4a`, module `wave` của Python không đọc được, còn ffmpeg thì
resample bằng thuật toán khác với `numpy.interp` trong bộ đo. Hai đường xử lý audio
khác nhau cho cùng một phép đo là cách chắc chắn để không so được kết quả.

`sounddevice` đã có sẵn trong `.venv` (dùng cho wake word), không phải cài thêm gì.

## Chạy

```powershell
cd D:\HASON\2025.2\VIN\P192\P-192
.\.venv\Scripts\python.exe scripts\ghi_wav_lenh_ngan.py --dich data\wav_nguoi_that
```

Mỗi câu: script in câu ra, đợi bạn Enter, ghi `--giay` giây (mặc định 3), rồi phát lại
để nghe thử. Gõ `l` + Enter để ghi lại câu vừa rồi, Enter trống để sang câu kế.

Xong thì đo:

```powershell
.\.venv\Scripts\python.exe scripts\do_wer_sua_chinh_ta.py --nguon data\wav_nguoi_that
```

## Ghi thế nào cho phép đo có nghĩa

- **Nói như nói với xe thật**, đừng đọc rõ từng chữ. Cả câu hỏi cần trả lời là "STT có
  chép được cách người ta nói thật không", không phải "chép được giọng đọc chuẩn không".
- Giữ khoảng cách mic **như lúc ngồi lái** — đây là biến số lớn hơn cả giọng.
- Ghi **cả hai nhóm**. Nhóm ngắn là thứ đang nghi hỏng; nhóm dài là đối chứng. Thiếu
  nhóm dài thì con số WER không nói được điều gì về giả thuyết "câu ngắn mới hỏng".
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
import wave
from pathlib import Path

import numpy as np

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SR = 16000

#: Sáu câu **ngắn** đang nghi hỏng — đo Piper 26/08 chép sai gần hết.
NGAN: tuple[str, ...] = (
    "Dừng nhạc",
    "Bật nhạc",
    "Tắt nhạc",
    "Chuyển bài",
    "Mở cốp",
    "Tăng âm lượng",
)

#: Đối chứng: cùng những lệnh ấy trong câu người thật nói. Đo Piper chép **đúng** nhóm
#: này — nếu người thật cũng vậy thì giả thuyết "STT yếu ở câu ngắn" đứng vững, và hướng
#: sửa nằm ở IVI (thu cả câu) chứ không ở STT.
DAI: tuple[str, ...] = (
    "Vivi ơi dừng nhạc giúp tôi",
    "Vivi ơi bật nhạc giúp tôi",
    "Vivi ơi tắt nhạc giúp tôi",
    "Vivi ơi chuyển bài giúp tôi",
    "Vivi ơi mở cốp giúp tôi",
    "Vivi ơi tăng âm lượng giúp tôi",
)


def _slug(text: str) -> str:
    bo_dau = "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    ).replace("đ", "d")
    return "-".join("".join(c if c.isalnum() else " " for c in bo_dau).split())


def _ghi(giay: float) -> np.ndarray:
    import sounddevice as sd

    mau = sd.rec(int(giay * SR), samplerate=SR, channels=1, dtype="int16")
    sd.wait()
    return mau.reshape(-1)


def _phat(mau: np.ndarray) -> None:
    import sounddevice as sd

    sd.play(mau, SR)
    sd.wait()


def _luu(duong_dan: Path, mau: np.ndarray) -> None:
    with wave.open(str(duong_dan), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(mau.tobytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dich", default="data/wav_nguoi_that", help="thư mục đích")
    parser.add_argument("--giay", type=float, default=3.0, help="độ dài mỗi lần ghi")
    parser.add_argument("--chi", choices=["ngan", "dai", "ca-hai"], default="ca-hai")
    args = parser.parse_args()

    try:
        import sounddevice as sd
    except Exception as exc:  # pragma: no cover - phụ thuộc máy
        print(f"Không nạp được sounddevice: {exc}")
        return 2
    print("Thiết bị thu đang dùng:", sd.query_devices(kind="input")["name"])

    cau = {"ngan": NGAN, "dai": DAI, "ca-hai": NGAN + DAI}[args.chi]
    dich = Path(args.dich)
    dich.mkdir(parents=True, exist_ok=True)

    for chi_so, text in enumerate(cau, start=1):
        ten = f"{chi_so:02d}-{_slug(text)}"
        while True:
            input(f"\n[{chi_so}/{len(cau)}] Nói: \033[1m{text}\033[0m   — Enter để bắt đầu ghi {args.giay}s ")
            print("  đang ghi...", flush=True)
            mau = _ghi(args.giay)
            dinh = int(np.abs(mau).max())
            print(f"  xong. đỉnh biên độ = {dinh} / 32767", end="")
            if dinh < 1500:
                print("  ← RẤT NHỎ, gần như chắc chắn mic không thu được")
            elif dinh > 32000:
                print("  ← VỠ TIẾNG, nói xa mic ra một chút")
            else:
                print()
            _phat(mau)
            tra_loi = input("  Enter = giữ và sang câu kế · l = ghi lại · b = bỏ câu này: ").strip().lower()
            if tra_loi == "l":
                continue
            if tra_loi == "b":
                break
            _luu(dich / f"{ten}.wav", mau)
            (dich / f"{ten}.txt").write_text(text, encoding="utf-8")
            print(f"  đã lưu {ten}.wav")
            break

    so_file = len(list(dich.glob("*.wav")))
    print(f"\nXong: {so_file} file trong {dich}")
    print("Đo bằng:")
    print(f"  .\\.venv\\Scripts\\python.exe scripts\\do_wer_sua_chinh_ta.py --nguon {dich}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
