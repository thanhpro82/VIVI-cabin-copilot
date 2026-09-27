"""Phân bố kết cục lượt trên lưu lượng **thật**, đọc qua `GET /traces`. Spec §7.

## Con số này quyết định việc gì

`docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md` §7 lấy nó làm
**cổng** cho ba mục đa lượt còn lại (#355 mục 3, #339):

    tỉ lệ lượt kết thúc ở `clarify`/`offer`  ≈1–2%  ->  DỪNG, không đáng làm
                                             ≳10%  ->  làm tiếp có cơ sở

Và một con số thứ hai, là **chi phí** của việc mở cửa sổ nghe tiếp: bao nhiêu phần trăm
lượt **bắt tự động** rơi vào `grounded_refusal` — tức xe nghe được thứ không nói với nó.

## Vì sao không đọc lại `agent/v3` hay `bao-loi-2408`

Cả hai chỉ chứa **lượt đầu**, và toàn câu trọn vẹn viết ra giấy. Mic mở thường trực
**đổi cách người ta nói** — ngắn hơn, tỉnh lược hơn. Nên con số 1–2% đo được 29/08 trên
hai bộ ấy có thể đang **đánh giá thấp**, và chính việc làm tính năng này có thể kéo nó
lên. Đó là lý do phép đo phải chạy trên lưu lượng thật, sau khi cửa sổ đã mở.

## Vì sao đọc qua HTTP chứ không gọi `get_trace_store()`

`TraceStore` là **biến toàn cục của tiến trình**. Một script chạy riêng sẽ thấy kho rỗng
dù backend vừa phục vụ hàng trăm lượt — đây là lỗi thiết kế của bản kế hoạch đầu, phát
hiện lúc thực thi.

## Phụ thuộc chưa merge, nói thẳng

`GET /traces` và kho bền `trace_spans` nằm ở nhánh **`feat/dashboard-ky-su-nhat-ky-ben`**
(commit `4a16720`, `8a76e20`), **chưa vào `develop`**. Trên `develop` hôm nay `TraceStore`
vẫn là LRU 200 bản ghi trong RAM, mất sạch khi restart — không đọc được từ ngoài.

Script này viết sẵn theo đúng hợp đồng ấy và **báo rõ** khi endpoint chưa có, thay vì
trả một con số sai. Chạy được ngay khi nhánh kia merge.

Chạy:

    .\\.venv\\Scripts\\python.exe scripts\\do_phan_bo_luot.py --gio 24
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
import urllib.error
import urllib.request

API = "http://localhost:8000/api/v1"

#: Kết cục nghĩa là **xe vừa đặt một câu hỏi và đang chờ trả lời** — tử số của phép đo §7.
CHO_TRA_LOI = ("clarify", "offer")

#: Kết cục nghĩa là **xe không tìm được gì để nói**. Trên lượt bắt tự động, đây là dấu
#: hiệu câu vừa rồi nhiều khả năng không nói với xe.
KHONG_HIEU = ("grounded_refusal",)


def _goi(duong_dan: str, token: str) -> dict:
    yeu_cau = urllib.request.Request(
        f"{API}{duong_dan}",
        headers={"Authorization": f"Bearer {token}", "X-Schema-Version": "1.0"},
    )
    with urllib.request.urlopen(yeu_cau, timeout=30) as ra:  # noqa: S310 - localhost, công cụ nội bộ
        return json.loads(ra.read())


def dang_nhap_ky_su(email: str, mat_khau: str) -> str:
    """`/traces` là route **engineer-only** (`_ENGINEER_ONLY`), nên phải là tài khoản kỹ sư."""
    than = json.dumps({"email": email, "password": mat_khau}).encode()
    yeu_cau = urllib.request.Request(
        f"{API}/auth/login", data=than, headers={"Content-Type": "application/json", "X-Schema-Version": "1.0"}
    )
    with urllib.request.urlopen(yeu_cau, timeout=30) as ra:  # noqa: S310
        return json.loads(ra.read())["data"]["access_token"]


def doc_trace(token: str, so_toi_da: int = 1000) -> list[dict]:
    """Lật trang bằng con trỏ thời gian `before`, đúng cách `list_traces` phân trang.

    Không dùng offset: nhật ký được ghi thêm liên tục, và offset sẽ trả trùng hoặc bỏ sót
    mỗi khi có lượt mới chen vào đầu danh sách.
    """
    ra: list[dict] = []
    before: str | None = None
    while len(ra) < so_toi_da:
        duong = "/traces?limit=200" + (f"&before={before}" if before else "")
        goi = _goi(duong, token)["data"]
        ra.extend(goi["items"])
        before = goi.get("next_before")
        if not before:
            break
    return ra[:so_toi_da]


def in_bang(traces: list[dict]) -> None:
    tong = len(traces)
    dem = collections.Counter(t.get("outcome") or "(trống)" for t in traces)
    print(f"n = {tong} lượt\n")
    for k, v in dem.most_common():
        danh_dau = "  <- xe đang chờ trả lời" if k in CHO_TRA_LOI else ""
        print(f"    {k:26} {v:4}  {v / tong * 100:5.1f}%{danh_dau}")

    cho = sum(dem[k] for k in CHO_TRA_LOI)
    print(f"\n    xe hỏi và chờ trả lời : {cho}/{tong} = {cho / tong * 100:.1f}%")

    tu_dong = [t for t in traces if t.get("bat_tu_dong")]
    if not tu_dong:
        print("    lượt bắt tự động      : 0 — cửa sổ nghe tiếp chưa từng bắt được lượt nào,")
        print("                            hoặc `bat_tu_dong` chưa lên tới `TraceSummary`.")
    else:
        hut = sum(1 for t in tu_dong if t.get("outcome") in KHONG_HIEU)
        print(f"    lượt bắt tự động      : {len(tu_dong)}/{tong} = {len(tu_dong) / tong * 100:.1f}%")
        print(f"    trong đó xe không hiểu: {hut}/{len(tu_dong)} = {hut / len(tu_dong) * 100:.1f}%")

    print("\n    Cổng §7:  ≈1–2% -> dừng phần đa lượt còn lại;  ≳10% -> làm tiếp có cơ sở.")
    print("    Nhắc: đây là TỈ LỆ MỖI LƯỢT. Một phiên 10 lượt ở mức 1,3% vẫn có ~12% khả")
    print("    năng vấp ít nhất một lần — tần suất thấp không đồng nghĩa hậu quả thấp.")


def main() -> int:
    p = argparse.ArgumentParser(description="Phân bố kết cục lượt trên lưu lượng thật (spec §7).")
    p.add_argument("--email", default="engineer.demo@example.com")
    p.add_argument("--mat-khau", default="DemoEngineer123!")
    p.add_argument("--so-luot", type=int, default=1000)
    args = p.parse_args()

    try:
        token = dang_nhap_ky_su(args.email, args.mat_khau)
    except urllib.error.URLError as loi:
        print(f"Không gọi được backend ở {API} — nó có đang chạy không? ({loi})")
        return 2

    try:
        traces = doc_trace(token, args.so_luot)
    except urllib.error.HTTPError as loi:
        if loi.code == 404:
            print("`GET /traces` chưa có trên nhánh này.")
            print("Nó nằm ở `feat/dashboard-ky-su-nhat-ky-ben` (4a16720, 8a76e20), chưa merge vào develop.")
            print("Trên develop, TraceStore vẫn là LRU 200 bản ghi trong RAM và không đọc được từ ngoài.")
            print("=> Phép đo §7 chờ nhánh ấy merge. Xem docstring đầu file.")
            return 3
        print(f"Lỗi HTTP {loi.code} khi đọc /traces: {loi.read()[:200]!r}")
        return 2

    if not traces:
        print("Chưa có lượt nào. Chạy vài lượt qua IVI rồi đo lại.")
        print("Lưu ý: con số chỉ có nghĩa trên lưu lượng THẬT — chạy tay vài câu do chính")
        print("mình nghĩ ra thì nó lại là một bộ đo tự viết, đúng thứ §7 sinh ra để tránh.")
        return 0

    in_bang(traces)
    return 0


if __name__ == "__main__":
    sys.exit(main())
