"""Chấm câu nói bằng **đáp án khoá** — thay chấm tay từng vòng bằng chấm tay một lần.

## Vì sao

Vòng chấm tay đầu (13/08, `graded_speech.jsonl`) lộ ra một giới hạn của chính phương
pháp: ranh giới giữa *một phần* và *không trúng* là câu hỏi **"nghe tiếp có tới câu
trả lời không?"**, mà trả lời được câu đó thì người chấm phải biết đoạn sổ tay còn gì
ở phía sau. Người chấm không có đoạn nguồn trước mắt. Nên ranh giới ấy thành phỏng
đoán, và một baseline dựng trên phỏng đoán thì đem so S1 với S2 không có nghĩa.

Cách sửa không phải là chấm cẩn thận hơn, mà là **dời phán đoán ra khỏi vòng chấm**:
với mỗi câu hỏi, đọc đoạn nguồn một lần và ghi ra câu nào thật sự trả lời
(`eval/datasets/manual/v1/answer_keys.jsonl`). Sau đó chấm là thao tác máy.

Hai tính chất khiến việc này không phải là tự chấm điểm cho mình:

- Khoá được quyết **trước khi nhìn đầu ra** của bất kỳ phiên bản nào, và nó là thuộc
  tính của *câu hỏi cộng đoạn sổ tay*, không phải của hệ thống.
- Cùng một khoá áp cho S1 và S2. Sai lệch nếu có thì rơi vào **cả hai**, nên phần
  chênh lệch — thứ thật sự dùng để quyết định — gần như không bị nó chi phối.

## Nó không đo cái gì

Nó đo *"câu nói có chạm tới câu trả lời trong đoạn không"*. Nó **không** đo *"tài xế
nghe xong có thấy thoả mãn không"* — thứ mà vòng chấm tay đo, và vẫn giữ nguyên trong
`graded_speech.jsonl`. Hai con số khác nhau; đừng trích cái này rồi gọi tên cái kia.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.rag.evaluate import uoc_giay_doc

#: Khoá dựng từ index thật ngày 14/08. Mỗi dòng là một case `supported`.
DAP_AN_KHOA = Path("eval/datasets/manual/v1/answer_keys.jsonl")

#: Số ký tự đầu của **câu nói** dùng để hỏi "câu này có lấy chữ từ đoạn không".
#: Chỉ phục vụ luật 2 (phân biệt câu khung fail-closed), không phục vụ luật 1.
KY_TU_KHOP = 40

_MUC = ("yes", "partial", "no")


@dataclass(frozen=True)
class DapAnKhoa:
    case_id: str
    question: str
    doan_co_cau_tra_loi: bool
    cum_tra_loi: list[str]
    #: Nguyên văn cả đoạn. Có mặt để (a) phân biệt câu khung fail-closed với câu
    #: trích từ đoạn, và (b) người rà lại khoá không cần dựng index mới kiểm được.
    doan: str = ""


def doc_dap_an_khoa(path: Path = DAP_AN_KHOA) -> dict[str, DapAnKhoa]:
    khoa: dict[str, DapAnKhoa] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        khoa[r["case_id"]] = DapAnKhoa(
            case_id=r["case_id"],
            question=r["question"],
            doan_co_cau_tra_loi=bool(r["doan_co_cau_tra_loi"]),
            cum_tra_loi=list(r["cum_tra_loi"]),
            doan=r.get("doan", ""),
        )
    return khoa


def _cham_toi(spoken: str, cum_tra_loi: list[str]) -> bool:
    """Câu nói có chứa **cụm mang câu trả lời** không.

    Khoá vào cụm chứ không vào cả câu, và đây là chỗ bản đầu của tôi sai đủ để thổi
    phồng điểm. Hai cách hỏng gặp thật khi đối chiếu với vòng chấm tay 13/08:

    - **Khớp trúng tiêu đề mục.** RAG-123 nói *"Hệ thống theo dõi áp suất lốp — Là một
      tính năng an toàn bổ sung, xe đã được trang bị (TPMS)"* rồi bị trần cắt **trước**
      mệnh đề mang nghĩa (*"để chiếu sáng báo hiệu áp suất lốp thấp"*). Khớp 40 ký tự
      đầu của câu thì trúng, mà tài xế chưa nghe được gì.
    - **Nhận câu chỉ nguồn hoặc câu điều kiện làm đáp án.** RAG-108 nói mỗi *"Tham khảo
      > Điều khiển điều hòa"*; RAG-107 mới nói tới điều kiện *"mang chìa khóa trong
      phạm vi 1m"* chứ chưa tới thao tác mở cửa.

    Cả hai đều lệch **về phía rộng tay** — tức về phía làm hệ thống trông tốt hơn thật.
    """
    return any(c and c in spoken for c in cum_tra_loi)


def cham_mot_cau(spoken: str, khoa: DapAnKhoa, *, doan: str | None = None) -> str:
    """Chấm một câu nói theo bốn luật, xét đúng thứ tự này.

    1. Chạm được **cụm mang câu trả lời** → **yes**.
    2. Không lấy chữ nào từ đoạn → **no**. Đây là câu khung `variant_fallback`: một
       lời **từ chối**, không phải một phần câu trả lời. Xếp nó vào "một phần" là
       thưởng điểm cho việc không trả lời.
    3. Đoạn vốn không chứa câu trả lời → **no**. Nghe tiếp cũng không cứu được — đó
       mới là "không trúng" đúng nghĩa, và đó chính là ranh giới người chấm không tự
       quyết được nếu không cầm đoạn nguồn.
    4. Còn lại → **partial**: đúng đoạn, câu trả lời nằm phía sau, lời mời "nghe tiếp
       nguyên văn" là đường tới.

    `doan` chỉ dùng cho luật 2. Thiếu nó thì luật 2 bỏ qua — chấm vẫn chạy, nhưng câu
    khung sẽ rơi vào luật 3/4. Call site thật luôn truyền.
    """
    if not spoken.strip():
        return "no"
    if _cham_toi(spoken, khoa.cum_tra_loi):
        return "yes"
    if doan is not None and not _lay_chu_tu_doan(spoken, doan):
        return "no"
    if not khoa.doan_co_cau_tra_loi:
        return "no"
    return "partial"


def _lay_chu_tu_doan(spoken: str, doan: str) -> bool:
    """Câu nói có lấy chữ nguyên văn từ đoạn không.

    So bằng cụm 40 ký tự đầu của câu nói — nó luôn là phần đầu một câu của đoạn ở cả
    S1 lẫn S2, trừ khi là câu khung.
    """
    dau = spoken.strip()[:KY_TU_KHOP]
    return bool(dau) and dau in doan


@dataclass(frozen=True)
class DuongToiDapAn:
    """Chi phí tài xế phải trả để nghe được câu trả lời.

    `luot` là số lượt nói, `giay` là tổng audio đã nghe. `luot is None` nghĩa là đoạn
    không chứa câu trả lời — nghe hết cũng không tới, và `giay` khi đó là thời gian
    **đã tiêu phí**, vẫn phải tính vào.
    """

    luot: int | None
    giay: float


#: Trần số lượt mô phỏng. Đoạn dài nhất trong bộ (2.416 ký tự) chia trần 240 ra ~12
#: lát; 20 là dư an toàn, và chạm trần nghĩa là có bug vòng lặp chứ không phải đoạn dài.
_MAX_LUOT = 20


def so_luot_toi_dap_an(spoken_dau: str, doan: str, khoa: DapAnKhoa) -> DuongToiDapAn:
    """Mô phỏng tài xế nói "nghe tiếp" tới khi nghe được câu trả lời.

    Với S3, "một phần" thôi không còn là một mức điểm — nó là một **khoảng cách**. Đo
    khoảng cách ấy bằng số lượt và số giây, chứ không quy về trúng/không-trúng, vì hai
    câu cùng "một phần" mà một câu tới sau 1 lượt còn câu kia sau 5 lượt là hai trải
    nghiệm khác hẳn nhau.

    Dùng đúng `doc_tiep` và `vi_tri_doc_toi` của production — mô phỏng bằng một bản
    sao thì con số nói về bản sao.
    """
    from src.agents.nodes.speech_policy import doc_tiep

    giay = uoc_giay_doc(spoken_dau)
    if _cham_toi(spoken_dau, khoa.cum_tra_loi):
        return DuongToiDapAn(luot=1, giay=giay)

    from src.agents.nodes.speech_policy import _cau

    # Cau nao da phat o luot dau: so chuoi voi tung cau cua doan. Doi voi cau khung
    # fail-closed thi khong cau nao khop -> da_doc rong -> "nghe tiep" doc tu dau, dung
    # hanh vi mong muon.
    da_doc = [i for i, c in enumerate(_cau(doan)) if c[:40] and c[:40] in spoken_dau]
    for luot in range(2, _MAX_LUOT + 1):
        ke_hoach = doc_tiep(doan, da_doc)
        if not ke_hoach.spoken:
            return DuongToiDapAn(luot=None, giay=round(giay, 2))
        giay += uoc_giay_doc(ke_hoach.spoken)
        if _cham_toi(ke_hoach.spoken, khoa.cum_tra_loi):
            return DuongToiDapAn(luot=luot, giay=round(giay, 2))
        da_doc = sorted(set(da_doc) | set(ke_hoach.chi_so))
    return DuongToiDapAn(luot=None, giay=round(giay, 2))


def cham_run(outcomes: list[dict], khoa: dict[str, DapAnKhoa]) -> dict:
    """Chấm cả một run. `outcomes` là `case_results.jsonl` đã parse.

    Chỉ chấm ca `supported` **và** có trả lời — cùng tập với khung chấm tay, để hai
    con số đặt cạnh nhau được.
    """
    diem: dict[str, str] = {}
    thieu_khoa: list[str] = []
    for o in outcomes:
        if not o.get("supported") or not o.get("answered") or not o.get("spoken_text"):
            continue
        k = khoa.get(o["case_id"])
        if k is None:
            thieu_khoa.append(o["case_id"])
            continue
        diem[o["case_id"]] = cham_mot_cau(o["spoken_text"], k, doan=k.doan or None)
    # --- Duong toi dap an voi S3 ---
    # Voi S3, "mot phan" khong con la mot muc diem ma la mot KHOANG CACH: cau tra loi
    # nam trong doan tai xe dang nghe, va tai xe toi duoc bang cach noi "nghe tiep".
    duong: dict[str, DuongToiDapAn] = {}
    for o in outcomes:
        k = khoa.get(o.get("case_id", ""))
        if k is None or o["case_id"] not in diem:
            continue
        duong[o["case_id"]] = so_luot_toi_dap_an(o["spoken_text"], k.doan, k)
    toi = {c: d for c, d in duong.items() if d.luot is not None}
    lu = sorted(d.luot for d in toi.values())
    gi = sorted(d.giay for d in toi.values())

    n = len(diem)
    dem = {m: sum(1 for v in diem.values() if v == m) for m in _MUC}
    return {
        "s3_toi_duoc": len(toi),
        "s3_ty_le_toi_duoc": len(toi) / n if n else 0.0,
        "s3_khong_toi_duoc": sorted(c for c, d in duong.items() if d.luot is None),
        "s3_luot_p50": lu[len(lu) // 2] if lu else None,
        "s3_luot_p95": lu[max(0, int(len(lu) * 0.95) - 1)] if lu else None,
        "s3_giay_p50": gi[len(gi) // 2] if gi else None,
        "s3_giay_p95": gi[max(0, int(len(gi) * 0.95) - 1)] if gi else None,
        "diem": diem,
        "dem": dem,
        "mau_so": n,
        "trung": dem["yes"] / n if n else 0.0,
        "trung_hoac_mot_phan": (dem["yes"] + dem["partial"]) / n if n else 0.0,
        "thieu_khoa": sorted(thieu_khoa),
    }
