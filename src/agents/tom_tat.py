"""Tóm tắt câu sổ tay cho kênh nói — và bốn cổng cứng chặn nó bịa.

## Hợp đồng

> **Bỏ các từ nối ra khỏi bản tóm tắt, phần còn lại phải là DÃY CON của đoạn nguồn.**

Nó cho model làm hai việc, và cấm ba việc:

| được | cấm |
|---|---|
| xoá chữ | thêm từ **nội dung** mới |
| chèn **từ nối** trong một tập đóng | đảo thứ tự nội dung |
| | đổi số lượng từ phủ định |

Đây là bản chặt hơn phép xoá thuần trong kế hoạch 18/08. Xoá thuần không chèn được
`"và"`, `"sau đó"`, `"nếu"` nên câu ghép từ hai mẩu nghe cụt; cho phép từ nối thì câu
mượt hơn hẳn mà **không nới một chút nào** về mặt dữ kiện: mọi từ mang nghĩa vẫn phải
đến từ sổ tay, đúng thứ tự sổ tay.

## Vì sao là cổng cấu tạo, không phải model chấm model

Ba bằng chứng, tất cả đo trên chính dự án này:

1. SPIKE-004 cho SLM viết lại tự do: **3/40** câu gây hiểu lầm theo thước hẹp — ngang
   4/40 mà ADR-015 đã bác. Lớp luật bề mặt chỉ bắt được **1/13** ca hỏng.
2. Đo 19/08 ở vai **câu dẫn** — vai được thiết kế để *không mang dữ kiện nào* — Qwen
   0.5B vẫn bịa số ở **8%** số lượt: *"Áp suất lốp khuyến nghị của xe là 200 kPa"*
   (thật là 260/270). Model bịa cả ở chỗ không có gì để bịa.
3. Bộ dò ảo giác hậu kiểm không cứu được: HHEM-2.1-Open không có tiếng Việt, và trên
   FaithBench thì balanced accuracy của SOTA vẫn quanh 55%.

Nên an toàn ở đây phải là **tính chất kiểm được bằng thuật toán**, không phải một con
số thống kê. Bốn cổng dưới đây đúng hoặc sai với mọi đầu vào.

## Cổng thứ tư tồn tại vì ba cổng đầu không đủ

Dãy con **không** chặn được việc xoá đúng chữ phủ định: *"không được dùng"* xoá thành
*"được dùng"* vẫn là một dãy con hợp lệ. Và slide 46 của `Day 18 — Production RAG` ghi
thẳng rằng embedding **mù phủ định** (*"Approved"* và *"Not approved"* có cosine cao),
nên cổng ấy phải là phép đếm từ vựng, tuyệt đối không phải NLI hay similarity.
"""

from __future__ import annotations

import re

from src.rag.textnorm import _tokens

#: Từ nối được phép chèn. Tập **đóng**, và cố ý nhỏ.
#:
#: Mỗi từ thêm vào đây là một chỗ model được nói thứ không đến từ sổ tay. Nên chỉ nhận
#: từ **thuần chức năng**: nối vế, chỉ thứ tự, chỉ điều kiện. Không nhận danh từ, động
#: từ, tính từ — chúng mang nghĩa, và nghĩa thì phải có nguồn.
#:
#: `không` KHÔNG nằm ở đây dù nó là hư từ: thêm một chữ `không` là đảo nghĩa cả câu.
TU_NOI = frozenset(_tokens("và các những này đó ấy nó cũng vẫn đã sẽ hãy một"))

#: `là` và `mà` đã BỎ khỏi tập trên vì chúng đồng thời nằm trong `TU_QUAN_HE` — hai tập
#: mâu thuẫn nhau thì cổng phụ thuộc vào thứ tự kiểm, tức phụ thuộc vào một chi tiết
#: cài đặt. Nay chúng chỉ nằm ở một chỗ, và chỗ ấy là tập bị cấm chèn.

#: **ĐÃ BỎ khỏi tập trên, và lý do là một ca thật.**
#:
#: Bản đầu xếp cả giới từ vào đây: `trong`, `ngoài`, `trên`, `dưới`, `sau`, `trước`,
#: `đến`, `từ`, `tại`, `theo`, `về`, `do`, `vì`, `bằng`, `với`, `cho`, `của`, `để`,
#: `khi`, `nếu`, `rồi`, `sau đó`.
#:
#: RAG-118 cho thấy sai ở đâu. Nguồn: *"thay thế lọc gió điều hòa **trong khoảng thời
#: gian** bảo trì quy định"*. Bản tóm: *"thay thế lọc gió điều hòa **sau** bảo trì quy
#: định"*. Nó đổi nghĩa một chỉ dẫn bảo dưỡng — và **qua cả bốn cổng**, vì mọi từ mang
#: nghĩa đều lấy từ nguồn đúng thứ tự; chỉ có chữ `sau` là chèn thêm, mà `sau` khi ấy
#: nằm trong tập từ nối.
#:
#: Giới từ **mang quan hệ**, không phải chất kết dính. Chèn một giới từ là phát biểu
#: một quan hệ mà sổ tay không nói. Cũng bỏ `hoặc` (đổi "và" thành "hoặc" là đổi hội
#: thành tuyển) và `được`/`bị` (trong tiếng Việt hai chữ này gắn kết quả tốt/xấu).
#:
#: Chúng vẫn dùng được bình thường khi CÓ SẴN trong nguồn — tập này chỉ nói model được
#: **chèn thêm** chữ gì.

#: Số từ hiếm nhất của **chính đoạn nguồn** phải được giữ lại.
#:
#: Xếp hạng, không phải ngưỡng tuyệt đối. Bản đầu dùng ngưỡng cố định (df ≤ 12) và nó
#: hỏng ngay ở ca thứ nhất: phân bố df trên 482 chunk lệch mạnh (p50=4, p75=20), nên
#: mỗi câu có "mức hiếm" riêng. Câu *"Bình chứa nước rửa kính đặt dưới nắp ca-pô"* có
#: từ hiếm nhất là `pô:14` — trên ngưỡng, nên cổng cho qua tất cả; còn câu về gai lốp
#: có `mười:1, sáu:3, inch:3, mm:4` nên gần như từ nào cũng bị coi là mang tin.
#:
#: Lấy k từ hiếm nhất thì thước tự co giãn theo câu, và nó luôn trỏ đúng vào những từ
#: **phân biệt câu trả lời này với mọi câu trả lời khác** trong sổ tay.
TOP_MANG_TIN = 5

#: Từ chỉ **quan hệ**. Chèn thêm một từ ở đây là phát biểu một quan hệ sổ tay không nói,
#: nên nó **không bao giờ** được dung sai bỏ qua — kể cả khi `dung_sai` lớn.
#:
#: Chấm tay 19/08 trên 15 bản tóm được nhận (`eval/results/cham-tay/`): **2 ca sai lệch,
#: cả hai mức nặng, và cả hai lọt qua đúng vì dung sai k=1**:
#:
#: - RAG-101 — nguồn *"CẢNH BÁO Trong quá trình khởi tạo, cửa sổ điện không có chức năng
#:   cảm biến chống kẹp."* thành *"**Nếu** trong quá trình khởi tạo, …"*. Một khẳng định
#:   chắc chắn biến thành một giả định, và mệnh đề kết quả biến mất.
#: - RAG-126 — sổ tay liệt kê ba cách truy cập nối bằng **HOẶC**; bản tóm nối chúng bằng
#:   *"**rồi**"* thành một chuỗi thao tác. Tài xế được bảo làm A rồi B, trong khi sổ tay
#:   nói làm A **hoặc** B.
#:
#: Cả hai chữ lọt vào — `nếu` và `rồi` — đều KHÔNG phải từ đồng nghĩa. Dung sai vốn mở
#: ra cho đồng nghĩa ("chặn" thay "ngăn") đã bị từ quan hệ chiếm mất. Nên dung sai phải
#: phân biệt loại từ, không chỉ đếm số từ.
TU_QUAN_HE = frozenset(
    _tokens(
        "nếu thì rồi khi sau trước trong ngoài trên dưới để vì nên do hoặc mà "
        "tuy nhưng bằng theo về từ đến tại với của cho bởi tức là gồm ngay chỉ"
    )
)

#: Từ chỉ **điều kiện**. Xoá mất một từ ở đây là biến một câu có điều kiện thành một
#: khẳng định — cùng hạng nguy hiểm với việc xoá chữ phủ định, và cùng lớp lỗi mà
#: ADR-015 đo được 4/40.
#:
#: Đối xứng với `TU_QUAN_HE`: tập kia chặn **chèn thêm**, tập này chặn **xoá đi**. Chấm
#: tay 19/08 cho thấy cần cả hai chiều. Hai ca ngắn-mà-sai đều là xoá điều kiện:
#:
#: - RAG-110 — bỏ *"Nếu được trang bị"*. Tài xế hỏi *"Ghế xe có chức năng massage
#:   không?"* và được trả lời như thể xe chắc chắn có.
#: - RAG-140 — *"**Nếu** khách hàng chọn thuê pin (**nếu có**)…"* thành *"Khách hàng
#:   chọn phương án thuê pin **và** phải ký…"*, tức điều kiện thành khẳng định.
#:
#: Đếm số lượng, đòi **không giảm**. Cho phép tăng vì thêm điều kiện là thu hẹp phạm vi,
#: mà thu hẹp thì an toàn — còn cổng `chen_tu_quan_he` vẫn chặn việc chèn bừa.
TU_DIEU_KIEN = frozenset(_tokens("nếu khi chỉ trừ miễn giả_sử trường_hợp tuỳ tùy"))

#: Từ phủ định. Đếm **số lượng**, không hỏi có hay không.
PHU_DINH = frozenset({"không", "chưa", "đừng", "chớ", "cấm", "chẳng", "tránh", "khỏi"})

#: Số kèm hoặc không kèm đơn vị. Mọi con số trong bản tóm tắt phải có trong nguồn.
_SO = re.compile(r"\d+(?:[.,]\d+)?")

_HE_CHU_LATIN = ("LATIN", "COMMON", "INHERITED")


def _bo_tu_noi(toks: list[str]) -> list[str]:
    return [t for t in toks if t not in TU_NOI]


def la_day_con_bo_tu_noi(goc: str, tom: str) -> bool:
    """Bỏ từ nối rồi, `tom` có phải dãy con theo token của `goc` không.

    Hai con trỏ, O(n). Không thống kê — đúng hoặc sai với mọi đầu vào, và đó là toàn
    bộ lý do tầng tóm tắt được phép tồn tại sau khi ADR-015 bác việc viết lại đoạn.

    Nó giết **theo cấu tạo** bốn lớp lỗi SPIKE-004 đo được, vì không lớp nào dựng lên
    được nếu không chèn được từ nội dung mới hoặc không đảo được thứ tự:

    - bịa quan hệ nhân quả (RAG-117, RAG-119)
    - gộp hai cơ chế (RAG-103)
    - thay thế quy trình (RAG-104)
    - đảo bước cuối thành *"đóng cổng sạc **và tháo** nắp bảo vệ"* (RAG-135)
    """
    a, b = _bo_tu_noi(_tokens(goc)), _bo_tu_noi(_tokens(tom))
    i = 0
    for t in a:
        if i < len(b) and b[i] == t:
            i += 1
    return i == len(b)


def so_tu_khong_khop(goc: str, tom: str) -> int:
    """Số từ **nội dung** trong `tom` không khớp được vào `goc` theo đúng thứ tự.

    Dùng dãy con chung dài nhất trên phần đã bỏ từ nối. `0` nghĩa là bản tóm là dãy
    con thuần; `k > 0` nghĩa là model đã thay hoặc thêm `k` từ mang nghĩa.

    ## Vì sao có dung sai, và vì sao nó là một CON SỐ chứ không phải một cờ

    Vòng nén 19/08 bác 62% số lượt, và khi soi ra thì phần lớn là **suýt đạt**:
    RAG-102 lệch đúng chữ *"chặn"* thay cho *"ngăn"*; RAG-104 nói *"Điều khiển cửa
    sổ: kéo lên đóng, nhấn xuống mở"* — nghe hay hơn hẳn nguồn — và bị bác vì hai chữ
    *"điều khiển"*. Bác những bản ấy là bác nhầm.

    Nhưng nới vô hạn thì mở lại đúng cánh cửa ADR-015 đã đóng: SPIKE-004 có ca *"nên
    hết sức thận trọng"* biến thành *"chỉ dùng khi…"* — cũng là thay từ, và nó đổi
    nghĩa hẳn. Không có phép kiểm máy nào phân biệt được hai loại thay từ ấy.

    Nên dung sai là một **núm vặn có số**: nhóm chọn `k`, bàn cân in cái giá của từng
    `k`, và quyết định nằm ở chỗ nhìn thấy được. Thứ tự thì **không** nới — đảo bước
    của một quy trình là lớp lỗi khác hẳn, và RAG-135 đã cho thấy nó nguy hiểm.
    """
    a, b = _bo_tu_noi(_tokens(goc)), _bo_tu_noi(_tokens(tom))
    if not b:
        return 0
    # LCS. n, m ≤ vài chục token nên O(n·m) là thoải mái.
    truoc = [0] * (len(a) + 1)
    for tb in b:
        hien = [0]
        for j, ta in enumerate(a):
            hien.append(truoc[j] + 1 if ta == tb else max(truoc[j + 1], hien[j]))
        truoc = hien
    return len(b) - truoc[-1]


def giu_phan_cuc(goc: str, tom: str) -> bool:
    """Số token phủ định phải **bằng nhau** hai bên.

    Lớp lỗi duy nhất `la_day_con_bo_tu_noi` không chặn được. Đếm số lượng chứ không
    hỏi có mặt hay không: một câu hai mệnh đề có thể mất đúng một chữ `không` mà vẫn
    còn một chữ khác, và phép kiểm có-hay-không sẽ cho qua đúng ca nguy hiểm nhất.
    """
    dem = lambda s: sum(1 for t in _tokens(s) if t in PHU_DINH)  # noqa: E731
    return dem(goc) == dem(tom)


def so_deu_co_trong_nguon(goc: str, tom: str) -> bool:
    """Mọi con số trong bản tóm tắt phải xuất hiện trong nguồn.

    Thừa về lý thuyết — dãy con đã bao hàm — nhưng giữ vì nó là **bất biến của cả
    thiết kế** và vì lớp lỗi này đã xảy ra thật hai lần: RAG-130 bịa `32 psi`, và câu
    dẫn của Qwen 0.5B bịa `200 kPa` cùng `10mm`. Một phép kiểm rẻ cho lớp lỗi đắt nhất
    thì đáng giữ kể cả khi nó dư.
    """
    return set(_SO.findall(tom)) <= set(_SO.findall(goc))


def chi_chu_viet(tom: str) -> bool:
    """Không có ký tự chữ thuộc hệ chữ ngoài Latin.

    RAG-105 gặp thật: model xen nguyên một câu tiếng Trung vào câu trả lời tiếng Việt.
    """
    import unicodedata

    for c in tom:
        if c.isalpha() and not any(unicodedata.name(c, "").startswith(h) for h in _HE_CHU_LATIN):
            return False
    return True


#: Sàn giữ lại: bản tóm phải còn ít nhất chừng này phần từ nội dung của nguồn.
#:
#: Đo 19/08 với Qwen3-4B ở k=1, trên các ca ĐƯỢC NHẬN:
#:   ca giữ được `đạt`  — nén còn **75%**
#:   ca mất `đạt`       — nén còn **64%**
#: RAG-125 nén còn 45% và đánh rơi "Car Control Area", tức đánh rơi chính câu trả lời.
#:
#: Nén quá tay là cách bản tóm đánh mất cụm chốt, và tỷ lệ nén thì **đo được lúc chạy**
#: — không cần khoá đáp án. Nên đây là cổng dùng được thật, khác với việc chấm bằng khoá.
SAN_GIU_LAI = 0.70


#: Từ nối **mang nghĩa**: bỏ chúng đi là mất một quan hệ, không chỉ mất chữ. Số lượng
#: không được giảm — xem cổng `mat_tu_noi_mang_nghia`.
#:
#: - `hoặc` — chọn một trong hai. "tại nhà hoặc văn phòng" khác "tại nhà và văn phòng".
#: - `nên` — vừa là nhân quả ("A nên B") vừa là khuyến nghị ("nên được thay sớm"). Đếm
#:   được ở cả hai nghĩa, vì cổng chỉ nổ khi số lượng **giảm**: mất nghĩa nhân quả là
#:   rơi mối liên hệ, mất nghĩa khuyến nghị là biến lời khuyên thành lời mô tả.
#:
#: Cố ý KHÔNG có `hay`: nó mang ba nghĩa rời nhau (liên từ chọn, tính từ "phim hay",
#: phó từ tần suất "hay quên"), nên đếm nó là bác nhầm mọi bản nén xoá một tính từ.
#: Cổng này thà hụt một lớp ca còn hơn sinh ra một lớp bác vô cớ — bác nhiều quá thì
#: cả tầng nén thành vô dụng, đúng cái bẫy SPIKE-004 đã chỉ.
TU_NOI_MANG_NGHIA = frozenset(_tokens("hoặc nên"))


#: Dấu câu treo lơ lửng ở cuối bản nén. `_tokens` bóc hết dấu nên phải xét riêng trên
#: chuỗi thô.
_DAU_TREO = ",;:-–—/&+"


#: Từ **không thể đứng cuối câu**. Hẹp hơn `TU_QUAN_HE` một cách có chủ đích.
#:
#: `TU_QUAN_HE` chứa `sau, trước, trong, ngoài, trên, dưới` vì chúng làm giới từ. Nhưng
#: trong tiếng Việt chúng đồng thời là **danh/tính từ chỉ vị trí**, và kết câu bằng
#: chúng là hoàn toàn bình thường: *"hàng ghế sau"*, *"xoay ra ngoài"*, *"phía trước"*.
#:
#: Chấm tay 20/08 trên 39 ca: **4 trên 8** lần `cau_cut` nổ là **bác oan** đúng vì lớp
#: từ này — một nửa số ca của cổng nổ nhiều nhất. Bốn ca còn lại kết bằng `và`, tức cụt
#: thật. Nên tách tập riêng thay vì dùng lại `TU_QUAN_HE`.
#:
#: Cổng `chen_tu_quan_he` **vẫn** dùng `TU_QUAN_HE` đầy đủ: ở đó câu hỏi là "có chèn
#: thêm không", và chèn một từ vị trí mà nguồn không có cũng là khẳng định một quan hệ
#: sổ tay không nói. Hai cổng hỏi hai câu khác nhau nên dùng hai tập khác nhau.
_TU_KHONG_KET_CAU = TU_NOI | frozenset(
    _tokens("nếu thì rồi khi để vì nên do hoặc mà tuy nhưng bằng theo về từ đến tại với của cho bởi tức là gồm")
)


def ket_lung_chung(tom: str) -> bool:
    """Bản nén kết thúc bằng chữ nối, chữ quan hệ, hoặc dấu câu treo.

    ## Ca thật sinh ra cổng này

    Nguồn: *"Hệ thống kiểm soát hành trình thích ứng (ACC) là một hệ thống hỗ trợ người
    lái xe tiên tiến, tự động điều chỉnh tốc độ xe để duy trì khoảng cách an toàn với
    các xe khác phía trước."*

    Bản nén: *"ACC là hệ thống hỗ trợ người lái xe tiên tiến và"*

    Model xoá vế sau rồi bỏ lại chữ `và` mà nó đã chèn để nối hai vế. Mọi cổng khác đều
    cho qua, và đúng ra phải cho qua: bản nén **là** dãy con hợp lệ, không bịa số, không
    mất phủ định, không mất điều kiện. Nó chỉ *chưa nói xong*.

    Đó là lớp lỗi mà tập `TU_NOI` mở ra: cho phép chèn `và` để nối hai vế thì cũng cho
    phép để lại một `và` không nối gì. Cổng này đóng đúng nửa ấy, và đóng bằng một tính
    chất cấu trúc chứ không bằng phán đoán.

    ## Vì sao cấm vô điều kiện, kể cả khi nguồn cũng cụt

    Đoạn nguồn bị cắt giữa chừng thì bản nén phản chiếu trung thực cái cụt ấy — nghe có
    vẻ oan. Nhưng thứ đi ra loa là bản nén, và một câu đọc lên kết thúc bằng `và` thì
    hỏng bất kể nguồn thế nào. Bị bác ở đây chỉ có nghĩa là rơi về nguyên văn, tức về
    đúng hành vi của hôm qua — giá của việc bác nhầm bằng không.

    ## Vì sao tập hẹp hơn `TU_QUAN_HE`

    Xem `_TU_KHONG_KET_CAU`: `sau`/`trước`/`ngoài` kết câu được trong tiếng Việt, và
    dùng nguyên `TU_QUAN_HE` ở đây đã bác oan 4 trên 8 ca.

    ## Vì sao KHÔNG tính từ phủ định

    `"…thì không"` là câu tiếng Việt hoàn chỉnh trong nhiều ngữ cảnh. Đưa `PHU_DINH` vào
    đây là đổi một cổng cấu trúc đúng-sai rạch ròi lấy một phép đoán ngữ pháp.
    """
    t = (tom or "").strip().rstrip(".!?…\"'“”) ").strip()
    if not t:
        return True
    if t[-1] in _DAU_TREO:
        return True
    tok = _tokens(t)
    return bool(tok) and tok[-1] in _TU_KHONG_KET_CAU


def sua_ngoac_lung(tom: str) -> str:
    """Bỏ phần phụ chú mở ngoặc mà không đóng. Chỉ XOÁ, không thêm gì.

    ## Vì sao SỬA chứ không BÁC

    Mọi cổng khác đều là phán quyết đúng-sai rồi rơi về nguyên văn. Cổng này thì bác là
    lãng phí, vì lỗi sửa được một cách an toàn tuyệt đối:

        model ra   "...là chiều rộng của lốp (cạnh thành lốp sang"
        bác     -> rơi về nguyên văn 100%, mất trọn phần nén
        sửa     -> "...là chiều rộng của lốp."

    Và bản sửa đúng bằng thứ người đọc thấy dễ hiểu hơn cả bản gốc — phụ chú
    "(cạnh thành lốp sang cạnh khác)" vốn làm câu rối thêm.

    ## Ranh giới: chỉ sửa ở chỗ dấu câu TỰ TUYÊN BỐ phần bị bỏ là phụ

    Ngoặc đơn nghĩa là "phần thêm vào", nên bỏ một phụ chú dở dang chỉ mất phần thêm.
    `cau_cut` **không** được sửa theo kiểu ấy: *"Nhấn công tắc để"* mà cắt chữ `để`
    thành *"Nhấn công tắc."* là mất luôn mục đích — giấu một mất mát thật sau một câu
    trông lành lặn. Ở đó bác mới đúng.

    Chỉ xoá nên tính dãy con không thể hỏng thêm; và `qua_cong` vẫn chạy trên chuỗi ĐÃ
    sửa, nên không có gì đi vòng qua hợp đồng.
    """
    t = tom or ""
    sau = -1
    do = 0
    for i, c in enumerate(t):
        if c == "(":
            if do == 0:
                sau = i
            do += 1
        elif c == ")" and do:
            do -= 1
    if do <= 0 or sau < 0:
        return t
    return t[:sau].rstrip(" ,;:-–—") or t


def qua_cong(
    goc: str,
    tom: str,
    dung_sai: int = 0,
    san_giu: float = 0.0,
    top_mang_tin: int = TOP_MANG_TIN,
) -> tuple[bool, str]:
    """Các cổng, theo thứ tự rẻ dần. Trả `(qua, tên cổng đã bác)`.

    Trả về **tên cổng** chứ không phải một cờ boolean: mỗi cổng bác vì một lý do khác
    nhau, và gộp lại thì bàn cân không biết nên chỉnh prompt hay chỉnh luật.
    """
    t = (tom or "").strip()
    if not t:
        return False, "rong"
    if not chi_chu_viet(t):
        return False, "he_chu_la"
    if ket_lung_chung(t):
        return False, "cau_cut"
    if not so_deu_co_trong_nguon(goc, t):
        return False, "so_khong_co_nguon"
    if top_mang_tin and giu_du_tu_mang_tin(goc, t, top_mang_tin):
        return False, "mat_tu_mang_tin"
    n_goc, n_tom = len(_bo_tu_noi(_tokens(goc))), len(_bo_tu_noi(_tokens(t)))
    if san_giu and n_goc and n_tom / n_goc < san_giu:
        return False, "nen_qua_tay"
    # Từ quan hệ chèn thêm là bác NGAY, không qua dung sai. Xem `TU_QUAN_HE`.
    them = set(_bo_tu_noi(_tokens(t))) - set(_tokens(goc))
    if them & TU_QUAN_HE:
        return False, "chen_tu_quan_he"
    lech = so_tu_khong_khop(goc, t)
    if lech > dung_sai:
        return False, "khong_phai_day_con"
    if not giu_phan_cuc(goc, t):
        return False, "lech_phan_cuc"
    dem_dk = lambda x: sum(1 for w in _tokens(x) if w in TU_DIEU_KIEN)  # noqa: E731
    if dem_dk(t) < dem_dk(goc):
        return False, "mat_dieu_kien"
    # Mất từ nối mang nghĩa. Đây là lỗ mà `TU_NOI` mở ra và không cổng nào khác đóng:
    # xoá chữ thì không giới hạn, chèn `và` thì được phép, nên model đổi được
    # "hoặc" thành "và" mà vẫn là một dãy con hợp lệ.
    #
    # Ca thật, đo trên backend 19/08:
    #   nguồn  "Có thể lắp bộ sạc tại nhà hoặc văn phòng"
    #   nén    "Có thể lắp bộ sạc tại nhà và văn phòng"
    # Một bên là chọn một, một bên là cả hai. Với hướng dẫn lắp đặt thì đó là hai
    # việc khác nhau, và tài xế không có cách nào biết câu mình nghe đã bị đổi.
    dem_noi = lambda x: sum(1 for w in _tokens(x) if w in TU_NOI_MANG_NGHIA)  # noqa: E731
    if dem_noi(t) < dem_noi(goc):
        return False, "mat_tu_noi_mang_nghia"
    return True, ""


#: Prompt. Nêu hợp đồng bằng chính lời của hợp đồng, và nêu **ba điều cấm** trước.
#:
#: Không kỳ vọng prompt thi hành được hợp đồng — đó là việc của cổng. Prompt chỉ để tỷ
#: lệ bác đừng cao tới mức tầng này thành vô dụng. SPIKE-004 đã chỉ ra cái bẫy: một bộ
#: luật bác 90% cho "sai = 0%" rất đẹp trong khi chẳng bao giờ dùng model.
#: ## Nhật ký phiên bản prompt
#:
#: Đánh số vì prompt là **cần rẻ nhất mà lâu nay dùng ít nhất**: suốt loạt tối ưu này
#: tôi với tay tới cổng, ngưỡng và tham số, còn prompt chỉ sửa đúng một lần — và lần ấy
#: là bị ép sửa vì nó nói ngược cổng, không phải vì chủ động cải tiến. Mỗi bản dưới đây
#: ghi **đổi gì** và **đo được gì**, để lần sau không ai phải đoán bản nào tốt hơn.
#:
#: - **v1** — hợp đồng dãy-con, sáu điều cấm. Kéo tỷ lệ bác 62% xuống 15% khi được sửa
#:   cho khớp cổng. Điểm yếu: tỷ lệ **sáu điều cấm trên một chỉ dẫn mơ hồ** ("rút gọn
#:   thành câu ngắn"), nên model biết rõ cái gì không được làm mà không biết phải GIỮ
#:   cái gì — kết quả là nó biên tập nhẹ tay thay vì cắt tới xương.
#: - **v2** — đảo tỷ lệ ấy: nêu mục tiêu trước, gộp sáu điều cấm còn bốn, và đưa **câu
#:   hỏi của tài xế** vào. Xem khối ngay dưới. **Đo được:** khi nén được thì cắt 53%
#:   (v1: 16%) — đúng mục tiêu — nhưng bác 82% (v1: 49%), nên trung bình chẳng ngắn hơn.
#: - **v4** — nói rõ KHI NÀO được dùng `và` (danh sách/nối tiếp: được; thay cho vế giải
#:   thích: không). **Không chữa được ca nào**, và làm model rụt tay: cắt trung bình 6%
#:   (v1: 14%), số ca nén >=10% tụt 11 -> 4.
#: - **v5** — v4 cộng đòi hỏi "đọc lại như chưa từng thấy đoạn gốc, câu phải tự đứng
#:   được". Cũng **không chữa được ca nào**; cắt 9%, nén>=10% được 7.
#:
#: **Kết luận sau năm bản: prompt không dịch chuyển được lớp lỗi này.** Ba hướng khác
#: nhau — nêu mục tiêu (v2), liệt kê chi tiết hơn (v3/v4), tự kiểm (v5) — đều không đổi
#: đầu ra ở hai ca đích, mà mỗi lần thêm điều cấm lại mất thêm phần nén có ích.
#:
#: Cách đọc: đây là quyết định về **quan hệ diễn ngôn** — `và` thay được cho nối tiếp
#: nhưng không thay được cho giải thích. Nhận ra quan hệ ấy trong đoạn nguồn khó hơn
#: chính việc nén, nên một model 4B ở nhiệt độ 0 không có chỗ mà áp dụng luật.
#:
#: - **v6** — CÙNG chữ của v4, chỉ **dời khối luật `và` lên đầu** (cùng 1097 ký tự).
#:   Cắt trung bình **20%** (v1: 14%), số ca nén >=10% lên **16** (v1: 11). Bản nén
#:   khoẻ nhất tới giờ, chỉ nhờ đổi vị trí.
#: - **v7** — v4 cộng **hai ví dụ làm mẫu** có nhãn ĐÚNG/SAI. Nhận 37/39 nhưng cắt chỉ
#:   6%: ví dụ làm model rụt hẳn tay. Và nó **không** chữa được ca nào — xem dưới.
#:
#: ### Kết quả đáng kể nhất của cả loạt: model không áp dụng được phân biệt này
#:
#: Prompt v7 chứa **nguyên văn** ca RAG-102, dán nhãn:
#:
#:     ĐÚNG:  ...điều khiển cửa sổ bằng cách tắt chức năng.
#:     SAI:   ...điều khiển cửa sổ và tắt chức năng.
#:
#: Model vẫn trả về đúng dòng ghi SAI. Cho nó xem chính ca ấy, dán nhãn, giải thích tại
#: sao — vẫn không đổi. Đây không phải chuyện viết prompt khéo hay vụng; **Qwen3-4B
#: không áp dụng được phân biệt quan hệ diễn ngôn này**, kể cả khi đáp án nằm ngay
#: trước mắt.
#:
#: Hệ quả cho việc chọn cần: prompt **điều chỉnh được ĐỘ MẠNH TAY** (v6 chứng minh: cùng
#: chữ, dời vị trí, cắt 14% -> 20%) nhưng **không sửa được LỚP LỖI** này. Hai thứ khác
#: nhau, và trộn chúng vào một câu "cải tiến prompt" là lý do tôi thử hụt năm bản.
#:
#: - **v3** — giữ khung mục tiêu của v2, trả lại danh sách từ quan hệ của v1. **Không
#:   chữa được gì**: `chen_tu_quan_he` còn tăng 15 → 17. Giả thuyết "thiếu danh sách"
#:   sai; xem lưới 2×2 ngay dưới.
#:
#: **Bản đang dùng vẫn là v1.** v2 và v3 giữ lại làm bản ghi của một thí nghiệm ÂM —
#: xoá chúng đi là mời người sau thử lại đúng hai hướng đã biết là không đi tới đâu.
#:
#: ### Lưới 2×2, và biến thật hoá ra là CÂU HỎI chứ không phải chữ nghĩa
#:
#: Ba thứ đổi cùng lúc ở v2 (danh sách, câu hỏi, khung "cắt mạnh") nên không quy được
#: trách nhiệm. Chạy chéo 39 ca, đếm `chen_tu_quan_he`:
#:
#: |                | không câu hỏi | có câu hỏi |
#: |----------------|---------------|------------|
#: | v1 (prompt cũ) | **0**, bác 49% | **7**, bác 64% |
#: | v3 (mục tiêu)  | **1**, bác 49% | **17**, bác 85% |
#:
#: Giữ prompt cố định mà thêm câu hỏi: 0→7 và 1→17. Giữ câu hỏi cố định mà đổi prompt:
#: 0→1 và 7→17. **Câu hỏi là nguyên nhân**, prompt chỉ khuếch đại.
#:
#: Cách đọc: đưa câu hỏi vào là lật model từ vai **biên tập** sang vai **trả lời**. Một
#: câu trả lời phải là câu hoàn chỉnh, mà câu hoàn chỉnh cần từ nối — nên nó chèn, dù
#: prompt cấm bằng luật tổng quát hay bằng danh sách liệt kê.
#:
#: Hệ quả tổng quát hơn, đáng ghi: **hợp đồng dãy con và việc hướng theo câu hỏi mâu
#: thuẫn nhau.** Muốn cắt đúng phần trả lời thì phải biết câu hỏi; biết câu hỏi thì
#: model thôi trích và bắt đầu soạn. Không lấy được cả hai từ một model trong một lượt.
#:
#: ### Số đo đầy đủ (39 ca, Qwen3-4B, `dung_sai=1 san_giu=0.0`)
#:
#: | bản | bác | cắt khi nén được | thân câu | giữ chốt (đạt) |
#: |---|---|---|---|---|
#: | **v1 −Q (đang dùng)** | 49% | 16% | 135 | **62%** |
#: | v1 +Q | 64% | 22% | 134 | 59% |
#: | v2 +Q | 82% | 53% | 132 | 62% |
#: | v3 +Q | 85% | 44% | 136 | 62% |
#: | v3 −Q | 49% | 36% | **119** | 56% |
#:
#: `v3 −Q` là ô tốt nhất cho **độ trực tiếp**: ngắn hơn 12% với cùng tỷ lệ bác. Nhưng
#: nó mất 6 điểm giữ chốt, và dự án này đặt độ chính xác trên độ ngắn — nên **chưa đổi
#: sang nó**, chờ chấm tay xem 6 điểm ấy là mất nghĩa thật hay chỉ là khác cách nói.
PROMPT_VERSION = "v3"

#: ### Vì sao v2 đưa câu hỏi vào — thay đổi lớn nhất, và không phải chuyện chữ nghĩa
#:
#: v1 chỉ nhận **đoạn văn**. Bộ nén mù với câu hỏi, nên nó không có cách nào biết câu
#: nào trong đoạn là câu trả lời và câu nào là dẫn nhập. Bảo một người "rút gọn cho
#: ngắn" mà không nói họ đang trả lời ai, hỏi gì, thì thứ hợp lý nhất họ làm là biên
#: tập đều tay khắp đoạn — đúng thứ v1 đang làm.
#:
#: Đo 20/08 trên 39 ca có khoá đáp án: các **câu chứa chốt** dài trung vị 227 ký tự,
#: còn **span hẹp nhất phủ mọi chốt** chỉ 125. Tức 45% chỗ đang tiêu là chữ bao quanh
#: đáp án chứ không phải đáp án. Muốn cắt đúng 45% ấy thì phải biết đáp án nằm ở đâu,
#: mà muốn biết thì phải thấy câu hỏi.
#:
#: An toàn không đổi: đầu ra vẫn phải là dãy con của **đoạn**, nên đưa câu hỏi vào
#: không mở đường cho model bịa. Rủi ro còn lại là nó chép một chữ **từ câu hỏi** sang
#: bản nén; `khong_phai_day_con` bắt được, và `dung_sai=1` chỉ tha đúng một từ — đây là
#: thứ phải nhìn kỹ khi chấm tay.

_PROMPT_V1 = (
    "Bạn rút gọn một đoạn sổ tay xe thành câu ngắn để đọc cho tài xế đang lái nghe.\n"
    "\n"
    "CÁCH LÀM: chỉ XOÁ bớt chữ thừa trong đoạn. Giữ nguyên các chữ còn lại và giữ\n"
    "nguyên thứ tự của chúng. Đừng viết lại câu theo cách của bạn.\n"
    "\n"
    "TUYỆT ĐỐI KHÔNG:\n"
    "1. Không thêm danh từ, động từ hay tính từ mới. Chỉ dùng chữ có sẵn trong đoạn.\n"
    "2. Không thêm từ chỉ quan hệ: nếu, thì, rồi, khi, sau, trước, trong, để, vì, nên,\n"
    "   hoặc, tuy, nhưng, bằng, theo, về. Chúng phát biểu một quan hệ sổ tay không nói.\n"
    "3. Không đổi thứ tự các bước hay các ý.\n"
    "4. Không bỏ chữ phủ định: không, chưa, đừng, cấm, tránh.\n"
    "5. Không bỏ nhãn CẢNH BÁO, LƯU Ý, THẬN TRỌNG, NGUY HIỂM nếu đoạn có.\n"
    "6. Không đổi hay bịa con số. Không dịch sang tiếng khác.\n"
    "\n"
    "Chỉ được thêm chữ 'và' để nối hai vế. Ngoài ra không thêm gì.\n"
    "\n"
    "Trả về đúng một câu, dưới 200 ký tự, không giải thích."
)

_PROMPT_V2 = """Bạn cắt một đoạn sổ tay xe thành câu trả lời ngắn, đọc cho tài xế đang lái nghe.

MỤC TIÊU: giữ đúng phần TRẢ LỜI ĐƯỢC CÂU HỎI. Cắt bỏ phần dẫn nhập, phần định nghĩa
hệ thống, tên đầy đủ và chữ viết tắt lặp lại, và mọi ý không liên quan tới câu hỏi.
Ngắn nhất có thể mà vẫn trả lời được — một câu đủ thì đừng viết hai.

CÁCH LÀM: chỉ XOÁ chữ khỏi đoạn. Giữ nguyên chữ còn lại và giữ nguyên thứ tự của
chúng. Không viết lại, không diễn đạt theo cách của bạn.

KHÔNG ĐƯỢC:
1. Thêm bất kỳ chữ nào không có trong đoạn. Ngoại lệ duy nhất: chữ 'và' để nối.
2. Bỏ chữ phủ định (không, chưa, đừng, cấm, tránh), từ điều kiện (nếu, khi, chỉ), hay
   từ chọn (hoặc). Bỏ chúng là đổi nghĩa, không phải rút gọn.
3. Bỏ nhãn CẢNH BÁO, LƯU Ý, THẬN TRỌNG, NGUY HIỂM nếu đoạn có.
4. Đổi hay bịa con số, đổi thứ tự các bước, dịch sang tiếng khác.

Trả về đúng một câu hoàn chỉnh, không giải thích."""

#: ### Vì sao v3 trả lại danh sách liệt kê — bài học đắt nhất của vòng này
#:
#: v2 gộp sáu điều cấm còn bốn, thay danh sách tường minh của v1 (`nếu, thì, rồi, khi,
#: sau, trước, để, vì, nên, hoặc…`) bằng một luật tổng quát: *"đừng thêm chữ nào không
#: có trong đoạn"*. Về logic thì luật tổng quát **bao hàm** danh sách.
#:
#: Với model thì không. `chen_tu_quan_he` nhảy từ **0 lên 15/39** — chiếm 47% số ca của
#: v2 và là nguyên nhân bác áp đảo. Model không coi hư từ là "chữ"; nó coi chúng là keo
#: dán được phép dùng để câu nghe trôi chảy. Danh sách liệt kê **không hề thừa**.
#:
#: Bài học ghi lại vì nó tổng quát hơn ca này: một luật bao hàm một luật khác **không**
#: đồng nghĩa với việc thay thế được nó, khi người thi hành là một model ngôn ngữ.
_PROMPT_V3 = """Bạn cắt một đoạn sổ tay xe thành câu trả lời ngắn, đọc cho tài xế đang lái nghe.

MỤC TIÊU: giữ đúng phần TRẢ LỜI ĐƯỢC CÂU HỎI. Cắt bỏ phần dẫn nhập, phần định nghĩa
hệ thống, tên đầy đủ và chữ viết tắt lặp lại, và mọi ý không liên quan tới câu hỏi.
Ngắn nhất có thể mà vẫn trả lời được — một câu đủ thì đừng viết hai.

CÁCH LÀM: chỉ XOÁ chữ khỏi đoạn. Giữ nguyên chữ còn lại và giữ nguyên thứ tự của
chúng. Không viết lại, không diễn đạt theo cách của bạn.

KHÔNG ĐƯỢC:
1. Thêm chữ nào không có trong đoạn. Ngoại lệ duy nhất: chữ 'và' để nối hai vế.
2. Thêm từ chỉ quan hệ, kể cả khi câu nghe trôi chảy hơn: nếu, thì, rồi, khi, sau,
   trước, trong, để, vì, nên, do, hoặc, tuy, nhưng, bằng, theo, về, mà, là. Chúng
   phát biểu một quan hệ mà sổ tay không nói.
3. Bỏ chữ phủ định: không, chưa, đừng, chớ, cấm, tránh. Bỏ một chữ 'không' là đảo
   ngược nghĩa của cả câu, không phải rút gọn nó.
4. Bỏ từ điều kiện (nếu, khi, chỉ, trừ) hay từ chọn (hoặc) đang có sẵn trong đoạn.
5. Bỏ nhãn CẢNH BÁO, LƯU Ý, THẬN TRỌNG, NGUY HIỂM nếu đoạn có.
6. Đổi hay bịa con số, đổi thứ tự các bước, dịch sang tiếng khác.

Trả về đúng một câu hoàn chỉnh, không giải thích."""

#: ### v4 — nói cho model biết KHI NÀO được dùng `và`
#:
#: v1 cấp quyền trần: *"Chỉ được thêm chữ 'và' để nối hai vế"* — không nói khi nào.
#: Chấm tay 20/08 cho thấy quyền ấy là nguồn của cả hai ca sai còn lại, và ranh giới
#: đúng do @HVNhan-Relieq chỉ ra:
#:
#: - `sau đó` → `và`: mất mát **nhỏ**, vì `và` tiếng Việt cũng chở được nghĩa nối tiếp.
#: - `bằng cách` → `và`: mất mát **thật**, vì vế sau **giải thích** vế trước, mà `và`
#:   không chở được nghĩa giải thích.
#:
#: Cổng không phân biệt nổi hai ca — với nó cả hai chỉ là "chèn một chữ `và`". Prompt
#: thì nói được, vì nó nói với thứ hiểu tiếng Việt.
_THEM_V4 = """Chỉ được thêm chữ 'và'. Ngoài ra không thêm gì.
Và chỉ dùng 'và' khi hai vế là hai mục ngang hàng, hoặc hai bước nối tiếp nhau.
KHÔNG dùng 'và' thay cho một vế GIẢI THÍCH: 'bằng cách', 'nghĩa là', hay phần trong
ngoặc đơn nói CÁCH NÀO / TẠI SAO, không phải RỒI GÌ NỮA. Gặp vế như thế thì giữ nguyên
chữ nối của đoạn, hoặc bỏ hẳn cả vế."""

_PROMPT_V4 = _PROMPT_V1.replace("Chỉ được thêm chữ 'và' để nối hai vế. Ngoài ra không thêm gì.", _THEM_V4)

#: ### v5 — đòi hỏi chưa prompt nào có: câu phải TỰ HIỂU ĐƯỢC
#:
#: Mọi chỉ dẫn từ v1 tới v4 đều nói về **tính trung thành** (đừng thêm, đừng bỏ). Không
#: dòng nào đòi bản nén phải **đọc lên hiểu được**.
#:
#: RAG-130 hỏng đúng ở đó và lọt qua **cả bảy cổng**: đủ chữ, đúng thứ tự, không bịa số.
#: Nguồn `"(cạnh thành lốp sang cạnh KHÁC)"` mất chữ `khác` thành `"cạnh thành lốp sang
#: cạnh"` — vô nghĩa. Cổng đo được sự trung thành, không đo được sự hiểu được.
_THEM_V5 = """TRƯỚC KHI TRẢ VỀ: đọc lại câu của bạn như thể bạn chưa từng thấy đoạn gốc.
Chỗ nào không hiểu được — một cụm bị cụt, một chữ bị thiếu làm cả cụm mất nghĩa — thì
trả chữ đã xoá về. Câu bạn đưa ra phải tự nó đứng được.

Trả về đúng một câu, dưới 200 ký tự, không giải thích."""

_PROMPT_V5 = _PROMPT_V4.replace("Trả về đúng một câu, dưới 200 ký tự, không giải thích.", _THEM_V5)

#: ### v6 và v7 — kiểm giả thuyết "vì sao v4 nói rõ thế mà vẫn lỗi"
#:
#: Trong v4, luật `và` nằm **sau sáu điều cấm đánh số**, tức bị chôn trong một bức
#: tường cấm đoán. Hai cách giải thích, mỗi cách một phép thử đổi **đúng một** biến:
#:
#: - **v6 — vị trí.** Cùng chữ ấy, dời lên ngay sau câu mô tả vai, trước mọi thứ khác.
#:   Đầu ra đổi thì đúng là hiệu ứng vị trí ("lost in the middle").
#: - **v7 — cụ thể thay vì trừu tượng.** Giữ nguyên vị trí của v4, thêm **hai ví dụ
#:   làm mẫu**. "Vế giải thích" là một phạm trù ngữ pháp; bắt model tự phân loại quan
#:   hệ diễn ngôn có thể khó hơn cho nó xem một ca đã giải sẵn.
_NL = chr(10)
_CAU_VAI = "Bạn rút gọn một đoạn sổ tay xe thành câu ngắn để đọc cho tài xế đang lái nghe."
_QUYEN_V1 = "Chỉ được thêm chữ 'và' để nối hai vế. Ngoài ra không thêm gì."

_PROMPT_V6 = _PROMPT_V1.replace(_CAU_VAI, _CAU_VAI + _NL + _NL + _THEM_V4, 1).replace(_NL + _NL + _QUYEN_V1, "", 1)

_VI_DU_V7 = """VÍ DỤ:
  Đoạn:  Công tắc ngăn hành khách phía sau điều khiển cửa sổ bằng cách tắt chức năng.
  ĐÚNG:  Công tắc ngăn hành khách phía sau điều khiển cửa sổ bằng cách tắt chức năng.
  SAI:   Công tắc ngăn hành khách phía sau điều khiển cửa sổ và tắt chức năng.
  Vì sao sai: 'bằng cách' nói CÁCH NÀO. Đổi thành 'và' biến một cơ chế thành hai việc.

  Đoạn:  Số có 3 chữ số là chiều rộng của lốp (cạnh thành lốp sang cạnh khác).
  ĐÚNG:  Số có 3 chữ số là chiều rộng của lốp.
  SAI:   Số có 3 chữ số là chiều rộng của lốp và cạnh thành lốp sang cạnh.
  Vì sao sai: bỏ CẢ phần trong ngoặc thì được; giữ một mảnh rồi dán bằng 'và' thì hỏng."""

_KET_V1 = "Trả về đúng một câu, dưới 200 ký tự, không giải thích."
_PROMPT_V7 = _PROMPT_V4.replace(_KET_V1, _VI_DU_V7 + _NL + _NL + _KET_V1, 1)

_BAN = {
    "v1": _PROMPT_V1,
    "v2": _PROMPT_V2,
    "v3": _PROMPT_V3,
    "v4": _PROMPT_V4,
    "v5": _PROMPT_V5,
    "v6": _PROMPT_V6,
    "v7": _PROMPT_V7,
}
TOM_TAT_SYSTEM = _BAN[PROMPT_VERSION]


#: ĐÃ BỎ: `NHAC_THEO_CONG` và cơ chế nén hai lượt.
#:
#: Lượt hai từng mua thêm 11 điểm phủ (bác 62% → 51%) với giá +84% độ trễ — đã mỏng.
#: Nhưng lý do bỏ hẳn là chỗ khác: phần lớn số ca nó chữa được đến từ việc **prompt của
#: tôi nói ngược cổng**, chứ không phải từ việc model cần thử lại. Sửa prompt cho khớp
#: hợp đồng kéo tỷ lệ bác từ 62% xuống 15% trong MỘT lượt — nhiều gấp bốn lần thứ lượt
#: hai mua được, và không tốn thêm mili-giây nào.
#:
#: Bài học ghi lại vì nó rẻ hơn mọi vòng lặp: khi tỷ lệ bác cao, hãy đọc prompt trước
#: khi dựng cơ chế thử lại.


class QwenTomTat:
    """Client llama-server cho vai tóm tắt. Mọi lỗi trả `None` = "không có ý kiến".

    `None` thì tầng gọi dùng nguyên văn — tức ca xấu nhất của tính năng này bằng ca
    bình thường của tính năng cũ.
    """

    def __init__(
        self,
        endpoint: str,
        timeout_s: float = 30.0,
        dung_sai: int = 1,
        san_giu: float = 0.0,
        top_mang_tin: int = 0,
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._timeout_s = timeout_s
        self._dung_sai = dung_sai
        self._san_giu = san_giu
        self._top_mang_tin = top_mang_tin

    def tom(self, doan: str, cau_hoi: str | None = None) -> tuple[str | None, str]:
        """Trả `(bản tóm tắt hoặc None, tên cổng đã bác)`.

        Một lượt, không thử lại — xem khối ĐÃ BỎ ở trên để biết vì sao.
        """
        import httpx

        from src.agents.slm import chatml

        # Câu hỏi đi TRƯỚC đoạn: model đọc tuần tự, biết mình đang tìm gì rồi mới
        # đọc đoạn thì nó lọc trong lúc đọc. Đảo lại là bắt nó nhớ cả đoạn rồi mới
        # biết cần gì. Thiếu câu hỏi (`None`) vẫn chạy — v1 vốn không có.
        nguoi_dung = f"Câu hỏi của tài xế: {cau_hoi}\n\nĐoạn sổ tay:\n{doan}" if cau_hoi else f"Đoạn sổ tay:\n{doan}"
        try:
            r = httpx.post(
                f"{self._endpoint}/completion",
                json={
                    "prompt": chatml(TOM_TAT_SYSTEM, nguoi_dung),
                    "temperature": 0,
                    # Bản tóm tắt không thể dài hơn nguồn; trần này vừa đúng vừa rẻ.
                    # v1 để `len(doan)//2` — dòng ấy ngầm bảo model "một nửa là được",
                    # đúng thứ v2 muốn bỏ. Trần tuyệt đối 120 token: span hẹp nhất phủ
                    # mọi chốt đo được là 125 KÝ TỰ, mà tiếng Việt ~2-3 ký tự/token nên
                    # 120 token thừa sức chở, còn model thì không còn cớ viết dài.
                    "n_predict": min(120, max(24, len(doan) // 3)),
                    "cache_prompt": True,
                    "stop": ["<|im_end|>", "<|im_start|>", "\n\n"],
                },
                timeout=self._timeout_s,
            )
            r.raise_for_status()
            tom = str(r.json().get("content", "")).strip().strip('"“”')
            tom = sua_ngoac_lung(tom)
        except Exception:
            return None, "goi_hong"

        ok, cong = qua_cong(doan, tom, self._dung_sai, self._san_giu, self._top_mang_tin)
        return (tom, "") if ok else (None, cong)


def _df_corpus() -> dict[str, int]:
    """Tần suất tài liệu của từng token trên kho chunk. Nạp trễ, cache một lần.

    Thiếu index thì trả `{}` — và cổng "giữ từ mang tin" khi ấy **cho qua tất cả**.
    Fail-open có chủ ý: CI không cài `rag` extra, và một cổng chất lượng không được
    phép làm chết cả nhánh sổ tay trên máy không có index.
    """
    global _DF_CACHE
    if _DF_CACHE is None:
        df: dict[str, int] = {}
        try:
            from src.agents.nodes.rag_node import _default_retriever

            for ch in _default_retriever()._chunks.values():  # noqa: SLF001
                for t in set(_tokens(ch.text or "")):
                    df[t] = df.get(t, 0) + 1
        except Exception:
            df = {}
        _DF_CACHE = df
    return _DF_CACHE


_DF_CACHE: dict[str, int] | None = None


def tu_mang_tin(text: str, top: int = TOP_MANG_TIN) -> set[str]:
    """`top` token **hiếm nhất trong corpus** của `text` — các từ chở thông tin thật.

    Bỏ từ nối và token một ký tự. Từ không có trong corpus (tên riêng, viết tắt) tính
    là hiếm nhất, nên luôn thuộc nhóm này.
    """
    df = _df_corpus()
    if not df:
        return set()
    ung = {t for t in _tokens(text) if t not in TU_NOI and len(t) > 1}
    return set(sorted(ung, key=lambda t: df.get(t, 0))[:top])


def giu_du_tu_mang_tin(goc: str, tom: str, top: int = TOP_MANG_TIN) -> set[str]:
    """Các từ mang tin của `goc` bị bản tóm đánh rơi. Rỗng nghĩa là giữ đủ.

    ## Vì sao cổng này thay cho sàn giữ lại

    Sàn giữ lại bác một bản tóm vì **ngắn**, không vì **sai** — và đo 19/08 cho thấy nó
    gây ra **20 trên 24** ca bị bác, tức 83% toàn bộ độ khắt khe, trong khi bốn cổng an
    toàn cộng lại chỉ bác 9 ca.

    Nó là một proxy thô: tôi đặt nó vì ca mất cụm chốt nén còn 64% còn ca giữ được nén
    còn 75% — tương quan thật, nhưng tương quan không phải nhân quả. Một bản tóm cô
    đọng mà vẫn giữ đủ ý thì vẫn bị nó bác.

    Cổng này hỏi đúng thứ cần hỏi: *bản tóm có đánh rơi từ nào chở thông tin không*.
    Nó không phạt sự cô đọng — bỏ mười chữ phổ biến vẫn qua; bỏ một chữ "ca-pô" thì không.
    """
    return tu_mang_tin(goc, top) - set(_tokens(tom))
