"""Câu hỏi *"thế nào"* phải nhận được **các bước**, không phải câu mô tả tính năng.

## Lỗi này sống qua chín vòng tối ưu mà không ai thấy

Bộ chọn xếp hạng theo **độ liên quan chủ đề**. Câu mô tả đứng đầu một mục sổ tay bao
giờ cũng trùng chủ đề nhiều hơn câu thao tác, nên nó luôn thắng — và tài xế hỏi *"bật
đèn sương mù thế nào"* thì nghe được *đèn sương mù dùng để làm gì*.

Đo 21/08 trên 39 ca `eval/datasets/manual/v1`, đối chiếu với bản trả lời tham chiếu
viết tay:

| câu hỏi | hệ thống trả lời |
|---|---|
| Bật đèn sương mù **thế nào**? | đèn sương mù *dùng để làm gì* |
| Đèn ban ngày bật **khi nào**? | DRL có *tác dụng* gì |
| Kết nối Bluetooth **thế nào**? | mô tả tính năng, không thao tác nào |
| Làm sao **bật** sưởi ghế? | xe *có thể được trang bị* sưởi ghế |

Thước `giu_y` không bắt được lớp này: nó chia độ dài cụm chốt cho độ dài lời nói nên
**thưởng cho ngắn**, và một câu mô tả ngắn ăn điểm cao hơn một quy trình đủ bước.

## Vì sao chữa được bằng luật, không cần model

Sổ tay có dấu hiệu **cấu trúc**: bước luôn là dòng gạch đầu dòng, thường sau một dòng
`Để <việc>:`. Đó là tri thức về **định dạng tài liệu** — kiểm được bằng thuật toán, đúng
hoặc sai với mọi đầu vào. Nhận **12/39** ca và đưa `giu_y` từ **64% lên 67%**, độ dài lời
nói 220 → 214 ký tự — **không một lời gọi model nào, 0 ms**.

Nguyên mẫu đo được 69% nhưng đó là số của một bản **thiếu tính năng**: nó không trừ chỗ
cho lời mời "nghe tiếp", nên nhét được nhiều bước hơn vào cùng một trần. Bản này trừ —
`test_luot_so_tay_van_gan_loi_moi_nhu_cu` là bánh cóc bắt đúng chỗ ấy.

Một ca **hồi quy**, ghi ra chứ không giấu: `RAG-140` *"Thuê pin được quản lý như thế
nào?"* — nhánh bước nhặt danh sách *biện pháp thu hồi pin* thay vì câu về hợp đồng thuê.
Đoạn ấy là văn bản pháp lý, danh sách của nó không phải quy trình thao tác. Đổi lại được
`RAG-105` và `RAG-135`, nên net +1. Chưa thêm cổng chặn vì mọi cổng thử nghiệm đều làm
mất `RAG-135`; đây là đánh đổi có số, không phải sơ suất.

Đây là lần thứ sáu trong dự án luật thắng model ở một chỗ tưởng là việc của model; xem
`docs/adr/ADR-015`, `ADR-022`, và PR #179 (đóng).
"""

import pytest

from src.agents.nodes.speech_policy import (
    MAX_SPOKEN_CHARS,
    _cau,
    chon_buoc_thao_tac,
    chon_cau_de_noi,
    doc_tiep,
)

#: Đoạn thật `RAG-122` — hai bước, có dòng tiêu đề "Để …:" và một LƯU Ý đứng sau.
DOAN_SUONG_SAU = (
    "Chống đọng sương phía sau\n"
    "Chống đọng sương phía sau và một phần của cửa sổ phía sau có thể được chống đọng "
    "sương và hơi nước bằng cách sử dụng chức năng Chống đọng sương phía sau. "
    "Để bật Chống đọng sương phía sau:\n"
    "- Chạm vào biểu tượng Chống đọng sương phía sau trên màn hình thông tin giải trí. "
    "- Nút sẽ sáng lên để cho biết hệ thống đang hoạt động. "
    "LƯU Ý Chống đọng sương phía sau sẽ tự động tắt."
)

#: Đoạn thật `RAG-112` — bước thật, rồi **một danh sách gạch đầu dòng KHÁC** ngay sau.
#: Bản đầu của nhánh này nuốt luôn danh sách sau và nói "Trạng thái xe đang TẮT".
DOAN_SUONG_MU = (
    "Đèn sương mù phía sau (nếu có trang bị)\n"
    "Đèn sương mù phía sau được lắp đặt trên cản sau để cho biết vị trí của xe trên đường "
    "khi lái xe trong sương mù, tuyết hoặc các điều kiện khác mà tầm nhìn bị hạn chế. "
    "Để kích hoạt đèn sương mù phía sau:\n"
    "- Chạm vào Điều khiển đèn trong Car Control Area trên màn hình cảm ứng. "
    "- Chạm vào biểu tượng Đèn sương mù phía sau. "
    "Đèn sương mù được TẮT nếu đáp ứng bất kỳ điều kiện nào sau đây:\n"
    "- Trạng thái xe đang TẮT. "
    "- Công tắc đèn định vị đã TẮT."
)


def _ev(text: str, **kw) -> dict:
    return {"text": text, "has_variant_condition": False, "is_table": False, **kw}


# --- nhánh bước nhận đúng ca ------------------------------------------------


def test_cau_hoi_thao_tac_nhan_duoc_cac_buoc():
    ke = chon_cau_de_noi(_ev(DOAN_SUONG_SAU), "Bật chống đọng sương kính sau bằng cách nào?")
    assert ke.reason == "buoc_thao_tac"
    assert "Chạm vào biểu tượng Chống đọng sương phía sau" in ke.spoken
    assert "Nút sẽ sáng lên" in ke.spoken
    # Câu MÔ TẢ đứng đầu mục là thứ bộ xếp hạng vẫn chọn trước bản này.
    assert "có thể được chống đọng sương và hơi nước" not in ke.spoken


def test_khong_nuot_danh_sach_gach_dau_dong_khac():
    """Chuỗi bước phải **liền mạch**; gặp câu không phải thao tác thì dừng.

    Thiếu luật này thì câu trả lời cho *"bật đèn sương mù thế nào"* kết thúc bằng
    "Trạng thái xe đang TẮT" — một mục của danh sách *điều kiện tắt đèn* nằm ngay sau.
    """
    ke = chon_cau_de_noi(_ev(DOAN_SUONG_MU), "Bật đèn sương mù thế nào?")
    assert ke.reason == "buoc_thao_tac"
    assert "Chạm vào Điều khiển đèn" in ke.spoken
    assert "Trạng thái xe đang TẮT" not in ke.spoken
    assert "Công tắc đèn định vị" not in ke.spoken


def test_bo_dong_tieu_de_de_nhung_khong_cat_chuoi():
    """`Để bật …:` là khung, không phải bước — nhưng nó nằm GIỮA nên không được cắt chuỗi."""
    ke = chon_cau_de_noi(_ev(DOAN_SUONG_SAU), "Bật chống đọng sương kính sau bằng cách nào?")
    assert "Để bật Chống đọng sương phía sau" not in ke.spoken


# --- và KHÔNG nhận các ca khác ---------------------------------------------


def test_cau_hoi_khong_phai_thao_tac_thi_di_duong_cu():
    ke = chon_cau_de_noi(_ev(DOAN_SUONG_SAU), "Chống đọng sương phía sau là gì?")
    assert ke.reason != "buoc_thao_tac"


def test_mot_buoc_le_thi_khong_doi_duong():
    """Đổi đường vì **một** câu thì không mua được gì, mà mất luật xếp hạng đang chạy tốt."""
    doan = "Đèn cảnh báo nguy hiểm dùng khi xe gặp sự cố. Nhấn công tắc đèn cảnh báo nguy hiểm."
    ke = chon_cau_de_noi(_ev(doan), "Bật đèn cảnh báo nguy hiểm bằng cách nào?")
    assert ke.reason != "buoc_thao_tac"


def test_doan_co_bien_the_van_tra_cau_chi_nguon():
    """Cổng an toàn của ADR-015 đứng TRƯỚC nhánh này và không được đi vòng.

    Đoạn có điều kiện theo phiên bản thì câu nói đúng là câu **chỉ nguồn**, kể cả khi
    đoạn ấy có đủ các bước — vì bước có thể mang số của một biến thể.
    """
    doan = (
        "Áp suất lốp\n"
        "Áp suất lốp khuyến nghị được liệt kê trên nhãn gắn trên khung cửa của người lái. "
        "Để bơm lốp:\n"
        "- Mở nắp van. - Bơm tới 260 kPa. - Đóng nắp van."
    )
    ke = chon_cau_de_noi(_ev(doan, has_variant_condition=True), "Cách bơm lốp thế nào?")
    assert ke.reason == "pointer"


# --- giữ được hợp đồng của các tầng khác ------------------------------------


def test_chi_so_duoc_dien_de_doc_tiep_chay_tiep_duoc():
    """`chi_so` là thứ lượt "đọc tiếp" dựa vào. Bỏ trống thì lượt sau đọc lại y hệt."""
    ke = chon_cau_de_noi(_ev(DOAN_SUONG_MU), "Bật đèn sương mù thế nào?")
    assert ke.chi_so, "phải mang chỉ số câu đã đọc"
    assert max(ke.chi_so) < len(_cau(DOAN_SUONG_MU))
    tiep = doc_tiep(DOAN_SUONG_MU, list(ke.chi_so))
    assert tiep.spoken, "phải còn phần dư để đọc tiếp"
    assert "Chạm vào Điều khiển đèn" not in tiep.spoken, "không được đọc lại câu vừa nghe"


def test_khong_vuot_tran_noi():
    ke = chon_cau_de_noi(_ev(DOAN_SUONG_MU), "Bật đèn sương mù thế nào?")
    assert len(ke.spoken) <= MAX_SPOKEN_CHARS


@pytest.mark.parametrize(
    "q",
    [
        "Bật đèn sương mù thế nào?",
        "Làm sao bật đèn sương mù?",
        "Bật đèn sương mù bằng cách nào?",
        "Cách bật đèn sương mù",
    ],
)
def test_bon_cach_hoi_cung_ra_cac_buoc(q):
    assert chon_cau_de_noi(_ev(DOAN_SUONG_MU), q).reason == "buoc_thao_tac"


# --- RAG-140: danh sách phải có NEO, không thì không phải quy trình -----------


#: Ba đoạn dưới đây chép **nguyên văn** từ `retrieve()` trên index thật (29/08), không
#: viết lại theo trí nhớ — cùng kỷ luật với `real.citations.test.ts`: khớp một hình dạng
#: tưởng tượng thì test xanh mà hệ vẫn hỏng.
RAG_140 = [
    "Lưu ý quan trọng liên quan đến Pin",
    "Nếu khách hàng vi phạm bất kỳ nghĩa vụ nào trong Thỏa thuận cho thuê Pin (nếu có), "
    "khách hàng phải chịu các biện pháp sau:",
    "- Hạn chế mức sạc;",
    "- Sử dụng công nghệ định vị địa lý trong Pin hoặc Xe để xác định vị trí Pin nhằm mục đích thu hồi; và",
    "- Thực thi bất kỳ biện pháp khắc phục nào khác được pháp luật cho phép.",
]

RAG_105 = [
    "Khóa trẻ em",
    "Tính năng Khóa trẻ em giúp ngăn không cho mở cửa sau từ bên trong xe.",
    "Để kích hoạt khóa cửa sau trẻ em:",
    "- Vào thư viện ứng dụng .",
    "- Chọn Cài đặt > Cài đặt xe > Cửa .",
    "- Cuộn xuống phần khóa trẻ em và chọn Bật/Tắt",
]

RAG_135 = [
    "Để sạc xe, hãy làm theo quy trình bên dưới và hướng dẫn của thiết bị sạc.",
    "Quan sát tất cả các Cảnh báo và Thận trọng.",
    "- Chuyển hộp số về chế độ Đỗ xe (P) và Kích hoạch Phanh Đỗ xe.",
    "- Kiểm tra xem thiết bị sạc có tương thích với xe không.",
    "- Mở Cửa cổng sạc và tháo nắp bảo vệ.",
]


def test_rag140_danh_sach_phap_ly_khong_phai_quy_trinh():
    """Hồi quy @thanhpro82 chặn PR #230, và anh ấy đúng.

    *"Thuê pin được quản lý như thế nào?"* nhặt danh sách **biện pháp thu hồi pin** —
    tức chế tài bên cho thuê áp lên khách hàng khi vi phạm hợp đồng — và đọc nó ra như
    một quy trình tài xế cần làm. Sai chủ đề, không đáng đổi lấy net +1 trên 39 ca.

    Ba mục ấy **là** gạch đầu dòng và **đều** mở đầu bằng động từ (`Hạn chế`, `Sử dụng`,
    `Thực thi`), nên ở mức từng mục chúng không phân biệt được với một quy trình thật.
    Dấu hiệu duy nhất nằm ở **câu dẫn**: `"Nếu khách hàng vi phạm…"` là một mệnh đề điều
    kiện, không phải một tiêu đề hướng dẫn.
    """
    assert chon_buoc_thao_tac(RAG_140, "Thuê pin được quản lý như thế nào?", 240) is None


def test_rag105_van_nhan_vi_co_tieu_de_de():
    """Đối chứng 1 — chuỗi toàn gạch đầu dòng **có** neo: ngay trên nó là `Để …:`."""
    plan = chon_buoc_thao_tac(RAG_105, "Khóa trẻ em ở cửa sau dùng thế nào?", 240)
    assert plan is not None
    assert "thư viện ứng dụng" in plan.spoken
    assert "Tính năng Khóa trẻ em giúp" not in plan.spoken


def test_rag135_van_nhan_vi_chuoi_mo_dau_bang_cau_khong_gach_dau_dong():
    """Đối chứng 2 — không có tiêu đề `Để …:` nào, nhưng chuỗi **mở đầu bằng một câu
    thao tác không phải gạch đầu dòng** (`"Quan sát tất cả các Cảnh báo…"`). Đó là bước
    thứ nhất tự đứng thành câu, và nó neo cả danh sách theo sau.

    Ca này là lý do luật neo phải có **hai** vế. Chỉ đòi `Để …:` thì mất RAG-135 — đúng
    thứ PR #230 ghi là "mọi cổng thử nghiệm đều làm mất RAG-135".
    """
    plan = chon_buoc_thao_tac(RAG_135, "Hướng dẫn sạc pin cho xe thế nào?", 240)
    assert plan is not None
    assert "Quan sát tất cả các Cảnh báo" in plan.spoken


def test_neo_khong_bi_pha_boi_dong_trong():
    """Câu dẫn và danh sách có thể cách nhau một dòng trống trong nguồn — dòng trống
    không được tính là "câu chen giữa" làm mất neo."""
    doan = [RAG_105[2], "", *RAG_105[3:]]
    assert chon_buoc_thao_tac(doan, "Khóa trẻ em dùng thế nào?", 240) is not None


# --- Hai ca cùng lớp, được sửa kèm theo -------------------------------------


RAG_112 = [
    "Đèn sương mù phía sau (nếu được trang bị)",
    "Đèn sương mù phía sau được lắp đặt trên cản sau để cho biết vị trí của xe.",
    "Để kích hoạt đèn sương mù phía sau:",
    "- Chạm vào Điều khiển đèn trong Car Control Area trên màn hình cảm ứng.",
    "- Chạm vào biểu tượng Đền sương mù phía sau .",
    "Đèn sương mù được TẮT nếu đáp ứng bất kỳ điều kiện nào sau đây:",
    "- Trạng thái xe đang TẮT.",
    "- Công tắc đèn định vị đã TẮT.",
    "- Đèn sương mù phía sau bị hủy kích hoạt khỏi cài đặt đèn.",
]

RAG_129 = [
    "Trợ lý giọng nói",
    "Tính năng trợ lý giọng nói được trang bị hoặc không tùy theo thị trường và phiên bản.",
    "Nếu có, để truy cập Cài đặt Trợ lý Giọng nói:",
    "- Chạm vào Thư viện ứng dụng trên màn hình cảm ứng.",
    "- Chạm vào Cài đặt > Cài đặt Trợ lý giọng nói .",
    "Tổng quan về cài đặt trợ lý giọng nói:",
    "- Từ ngữ kích hoạt - Cho phép nhận dạng từ ngữ “Hey VinFast”.",
    "- Trợ lý giọng nói chào mừng - Cho phép trợ lý chào khi khởi động xe.",
    "- Chế độ duy trì Trợ lý giọng nói - Đặt câu hỏi tiếp mà không cần lặp lại “Hey VinFast”.",
]


def test_rag112_chon_quy_trinh_ngan_chu_khong_chon_danh_sach_dieu_kien_dai_hon():
    """Luật "chuỗi liền mạch dài nhất" một mình **chọn nhầm** ở đây, và docstring cũ của
    `chon_buoc_thao_tac` tưởng tính liền mạch đã chặn — không.

    Đoạn có **hai** danh sách tách bạch: quy trình thật **2 mục** dưới `"Để kích hoạt…:"`,
    và danh sách **điều kiện tắt 3 mục** dưới `"…TẮT nếu đáp ứng bất kỳ điều kiện nào sau
    đây:"`. Dài hơn thắng, nên tài xế hỏi *"bật đèn sương mù thế nào"* lại nghe ba điều
    kiện để đèn **tắt**.

    Câu dẫn là thứ phân biệt, không phải độ dài.
    """
    plan = chon_buoc_thao_tac(RAG_112, "Bật đèn sương mù thế nào?", 240)
    assert plan is not None
    assert "Chạm vào Điều khiển đèn" in plan.spoken
    assert "Trạng thái xe đang TẮT" not in plan.spoken


def test_rag129_bo_bang_mo_ta_va_lay_quy_trinh_that():
    """Cùng lớp với RAG-112: bảng *"Tổng quan về cài đặt…"* dài hơn quy trình truy cập.

    Ca này còn là lý do phủ quyết **không** được chặn theo chữ `nếu`: câu dẫn của quy
    trình thật là `"Nếu có, để truy cập Cài đặt Trợ lý Giọng nói:"` — `nếu có` ở đó là rào
    *"tuỳ trang bị"*, không phải một mệnh đề điều kiện. Chặn theo `nếu` là mất luôn nó.
    """
    plan = chon_buoc_thao_tac(RAG_129, "Dùng trợ lý giọng nói trên xe thế nào?", 240)
    assert plan is not None
    assert "Thư viện ứng dụng" in plan.spoken
    assert "Từ ngữ kích hoạt" not in plan.spoken


def test_cau_dan_het_hieu_luc_khi_co_cau_thuong_xen_vao():
    """Câu dẫn chỉ dẫn vào danh sách **ngay dưới nó**. Một câu thường xen vào là hết —
    nếu không thì một `Để …:` ở đầu đoạn sẽ neo cho mọi danh sách phía sau, kể cả danh
    sách điều kiện, và cả cổng này mất tác dụng."""
    doan = [
        "Để kích hoạt tính năng:",
        "- Chạm vào Cài đặt .",
        "- Chọn Bật .",
        "Tính năng bị vô hiệu trong các tình huống sau.",
        "- Xe đang sạc.",
        "- Nhiệt độ pin quá thấp.",
    ]
    plan = chon_buoc_thao_tac(doan, "Bật tính năng này thế nào?", 240)
    assert plan is not None
    assert "Chạm vào Cài đặt" in plan.spoken
    assert "Xe đang sạc" not in plan.spoken
