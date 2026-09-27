r"""Nhận diện câu hỏi tiếng Việt, và phân biệt phủ định với nghi vấn.

Hai hiện tượng ngữ pháp khiến bản router đầu tiên chỉ đẩy được 8,3% câu hỏi sổ
tay sang RAG (xem ADR-011):

1. `có … không?` là câu hỏi có/không, nhưng regex `\bkhông\b` đọc thành phủ định
   rồi từ chối thẳng.
2. Dạng nghi vấn cũng được dùng cho **lệnh lịch sự** (`"Mở cửa sổ được không?"`),
   nên không thể coi mọi câu có dấu `?` là câu hỏi tra cứu.

Danh sách marker dưới đây suy từ ngữ pháp nghi vấn tiếng Việt, **không** phải từ
việc soi case nào đang trượt trong bộ eval — xem mục kỷ luật trong plan.
"""

from __future__ import annotations

#: Hỏi CÁCH/CÁI GÌ/TẠI SAO → câu hỏi tra cứu sổ tay.
HOW_WHAT_MARKERS: tuple[str, ...] = (
    "thế nào",
    "như thế nào",
    "ra sao",
    "làm sao",
    "là gì",
    "để làm gì",
    "nghĩa là gì",
    "tại sao",
    "vì sao",
    # Cùng họ với `tại sao`/`vì sao`, chỉ khác chỗ đứng: `"... là sao"` hỏi *chuyện
    # gì đang xảy ra*. Sót từ đầu; ca `CC-AN14`/`CC-AB14` ("thắng/phanh kêu két két
    # LÀ SAO") làm nó lộ ra — nhưng nó là marker nghi vấn thật, không phải vá theo ca.
    "là sao",
    "khi nào",
    "ở đâu",
    "bao nhiêu",
    "bao lâu",
    "thì xử lý",
    "xử lý thế nào",
)

#: Từ đứng ngay trước `"không"` biến nó thành **số 0** thay vì phủ định/nghi vấn.
#: Định nghĩa gốc ở đây vì cả `is_question` lẫn `router._loc_khong_khong_phai_so`
#: đều phải dùng CÙNG một tập — hai bản sao là hai bản sẽ lệch nhau.
#:
#: **Danh sách ĐÓNG, và mỗi mục phải trả giá bằng một ca dương tính từ NGUỒN ĐỘC LẬP**
#: (điều kiện 2 của review #268). Bản đầu có bảy mục; sáu mục đã bị loại, theo hai lớp
#: bằng chứng khác nhau — chép lại đây vì lần sau ai muốn thêm từ sẽ đi đúng con đường này.
#:
#: **Loại vì gây hại đo được (26/08):**
#:
#: - `là` — trùng *"vấn đề là không..."*. `"bật điều hòa lên đi vấn đề là không ai chịu
#:   được"` ra `denied / temperature_out_of_range`: một lời từ chối kèm lý do 0 °C **không
#:   có thật**, đúng lớp lỗi mà chính thay đổi này sinh ra để diệt.
#: - `còn` — trùng dạng hỏi thông dụng nhất. `"xăng còn không"`, `"quạt gió còn không"`
#:   đều bị `is_question` trả **False**: một câu hỏi rõ ràng thôi được nhận là câu hỏi.
#: - `đến`, `tới` — đứng ngay trước `"không gian"`/`"không khí"`, nơi `"không"` là âm tiết
#:   đầu của một từ ghép chứ không phải con số.
#:
#: **Loại vì ca dương tính là câu do chính người viết luật tự nghĩ ra:**
#:
#: - `về`, `bằng` — `"đặt âm lượng về không"` / `"bằng không"` không xuất hiện lần nào
#:   trong `eval/datasets/` lẫn corpus sổ tay (grep 26/08: 0/0). Không có hại đo được,
#:   nhưng nhãn tự viết chỉ là tripwire hồi quy chứ không nói gì về khái quát hoá — đúng
#:   cái bẫy `agent/v3` mà repo đã ghi thành kỷ luật. Giá phải trả cho việc loại chúng đo
#:   được và **an toàn**: `"đặt âm lượng về không"` ra `clarify / missing_volume`, tức hỏi
#:   lại chứ không làm sai.
#:
#: `mức` ở lại vì nguồn độc lập có sẵn: câu do người khác viết trong `eval/datasets/agent/`
#: dùng đúng cấu trúc ấy (`"Bật sưởi ghế lái mức 2"`, `"Đặt sưởi ghế phụ mức 3"`).
#:
#: Thêm mục mới thì phải kèm (a) một ca dương tính **không do mình viết**, và (b) một ca
#: âm tính chứng minh nó không nuốt mất một câu không phải lệnh.
NEO_SO_KHONG: tuple[str, ...] = ("mức",)

#: Cụm báo hiệu người nói vừa **rút lại** vế trước và nói lại — *"bật nhạc, à thôi,
#: tắt đi"*, *"đặt âm lượng 70, không, 40 phần trăm"*.
#:
#: Đặt cạnh `NEO_SO_KHONG` và **không** khai một bản riêng cho chữ `không`: đây là
#: nghĩa **thứ tư** của từ ấy trong router (phủ định, tiểu từ nghi vấn, số 0, và giờ
#: là dấu rút lại). Bốn nghĩa đọc chung một luật neo thì còn tra được; mỗi nghĩa một
#: bảng thì chúng sẽ lệch nhau đúng vào ngày ai đó thêm một từ neo.
#: **Hai hạng, và ranh giới giữa chúng là toàn bộ câu trả lời cho review #315.**
#: Mọi mục dưới đây trừ `"không"` chỉ có **một** nghĩa: người nói vừa rút lại. `"không"`
#: thì có bốn nghĩa (xem `_tach_tu_sua_loi`), nên nó không được hưởng cùng mức tin cậy
#: — `DAU_SUA_LOI_RO` là chỗ ghi lại sự khác biệt đó, và router đọc đúng nó để quyết
#: định có fail-closed hay không.
DAU_SUA_LOI: tuple[str, ...] = (
    "à thôi",
    "thôi khỏi",
    "à quên",
    "à không",
    "ý tôi là",
    "ý mình là",
    "ý là",
    "nhầm rồi",
    "nhầm",
    "không",
)

#: Dấu rút lại **không mơ hồ**: gặp chúng là chắc chắn có một vế vừa bị huỷ.
#:
#: `"không"` đứng ngoài, và đó là điều kiện approve #1 của review #315. `"bật nhạc
#: không nghe rõ"`, `"bật điều hòa không cần mạnh"`, `"mở cửa sổ không được"` đều là
#: câu bình thường có `"không"` ở giữa; coi chúng là câu sửa lời rồi fail-closed là
#: đổi một lỗi (thực thi nhầm) lấy một lỗi khác (hỏi lại một câu đã rõ nghĩa).
#:
#: `"à không"` **có** trong danh sách này dù chứa `"không"`: cụm hai từ ấy chỉ dùng để
#: rút lại, và `_DAU_SUA_LOI_DAI_TRUOC` khớp dài-trước nên nó thắng `"không"` trần.
DAU_SUA_LOI_RO: frozenset[str] = frozenset(DAU_SUA_LOI) - {"không"}

#: Phủ định ở mọi vị trí, không phụ thuộc chỗ đứng.
_HARD_NEGATIONS = frozenset({"đừng", "chớ", "chẳng"})

#: Tiểu từ **cuối câu** — không mang nghĩa, chỉ mang thái độ và giọng vùng.
#:
#: Vì sao cần (đo 22/08 trên 28 ca phương ngữ, issue #244): cả `is_negated` lẫn
#: `is_question` đều đọc **vị trí** của chữ `"không"`, mà giọng nói thật gần như
#: luôn còn một tiểu từ đứng sau nó. Không bóc lớp này thì cùng một ý, bản có
#: tiểu từ và bản không đi hai đường khác hẳn nhau:
#:
#:     "Mở cửa sổ được không"      -> is_question=True  -> offer   (đúng)
#:     "Mở cửa sổ được không ta"   -> is_question=False -> ...
#:     "Bật điều hòa được không vậy" -> denied / temperature_out_of_range  (SAI)
#:
#: Cố ý KHÔNG có `nhé`/`nha`: chúng làm mềm **mệnh lệnh** ("bật điều hòa lên nhé"),
#: không phải tiểu từ nghi vấn, và gộp vào chỉ làm mờ ranh giới hỏi/sai-khiến.
_TIEU_TU_CUOI = frozenset({"ta", "nhỉ", "nhở", "thế", "đấy", "vậy", "à", "ạ", "hả", "hử", "ha", "cơ"})


def bo_tieu_tu_cuoi(tokens: list[str]) -> list[str]:
    """Bóc tiểu từ ở đuôi để hai hàm dưới nhìn thấy chữ `"không"` ở đúng vị trí của nó.

    Bóc lặp vì tiếng Việt nói xếp chồng được: `"...được không vậy ta"`.
    """
    while tokens and tokens[-1] in _TIEU_TU_CUOI:
        tokens = tokens[:-1]
    return tokens


def is_negated(normalized: str) -> bool:
    """`không` là phủ định khi đứng trước động từ; là tiểu từ nghi vấn khi cuối câu.

    Đây là toàn bộ cách phân biệt `"Không phát nhạc"` (phủ định) với
    `"Ghế xe có chức năng massage không?"` (câu hỏi).

    "Cuối câu" tính **sau khi bóc tiểu từ**: `"mở cửa sổ được không ta"` có `"không"`
    ở áp chót, nhưng sau nó chỉ còn tiểu từ nên nó vẫn là nghi vấn, không phải phủ định.
    """
    tokens = normalized.split()
    if not tokens:
        return False
    if _HARD_NEGATIONS & set(tokens):
        return True
    return "không" in bo_tieu_tu_cuoi(tokens)[:-1]


def is_information_question(normalized: str) -> bool:
    """Câu hỏi xin **giải thích** (`thế nào`, `là gì`, `cách`…) — luôn đi tra sổ tay.

    Khác với dạng nghi vấn có/không. `"Chỉnh nhiệt độ thế nào?"` hỏi *cách làm*, nên
    hỏi ngược lại "bạn muốn chỉnh bao nhiêu độ?" là trả lời sai câu hỏi. Còn
    `"Mở cửa sổ được không?"` hỏi *có làm được không*, nên nêu đề nghị mới đúng.
    """
    return any(marker in normalized for marker in HOW_WHAT_MARKERS) or normalized.startswith("cách ")


def is_question(raw_text: str, normalized: str) -> bool:
    """Câu này là hỏi để tra cứu, hay là lệnh?

    `raw_text` cần thiết vì `normalize_vi` xoá dấu câu, mà dấu `?` là bằng chứng
    mạnh nhất.

    Bản đầu có thêm một "lớp yêu cầu lịch sự" (`được không`, `nhé`) để giữ
    `"Mở cửa sổ được không?"` là lệnh. Đã bỏ: phân biệt nó với `"Phát nhạc từ USB
    được không?"` (hỏi năng lực) cần ngữ cảnh mà luật không có. Câu hỏi giờ đi
    đường `offer` — nêu việc sẽ làm rồi hỏi lại — nên không còn gì phải đoán.
    """
    if is_information_question(normalized):
        return True
    tokens = bo_tieu_tu_cuoi(normalized.split())
    if tokens and tokens[-1] == "không" and not (len(tokens) > 1 and tokens[-2] in NEO_SO_KHONG):
        # `"không"` cuối câu là tiểu từ nghi vấn — TRỪ khi có từ neo đứng trước, lúc
        # ấy nó là số 0: `"đặt âm lượng về không"` là lệnh, không phải câu hỏi.
        # Luật neo phải áp ở CẢ ba chỗ đọc vị trí chữ này (`is_negated`, `is_question`,
        # `_words_to_number`); thiếu một chỗ là cùng một câu đi hai đường khác nhau.
        return True
    return raw_text.rstrip().endswith("?")


#: Từ vựng "câu này có nói về XE không" — danh sách ĐÓNG, curate từ
#: `docs/coverage_matrix.md` + 58 section của sổ tay VF9. Không phải luật điều
#: khiển: nó chỉ quyết định câu hỏi đi đường tắt sổ tay hay rơi xuống classifier.
#:
#: Vì sao cần (SP-2 §2.3, run `do-tre/20260822T030757`): 4/15 câu xã giao có dấu
#: hỏi ("Xin chào, hôm nay khỏe không?") bị `manual_question` bắt thành câu hỏi sổ
#: tay và trả "không tìm thấy" — classifier không bao giờ được hỏi. Câu hỏi KHÔNG
#: dính mục nào ở đây thì không phải câu hỏi về xe.
#:
#: Viết ở dạng đã normalize (chữ thường, có dấu, không dấu câu). Thêm mục mới thì
#: chạy lại `tests/test_agents/test_tu_vung_xe.py::test_41_cau_hoi_nhu_tai_xe_van_di_duong_tat`.
_TU_VUNG_XE: tuple[str, ...] = (
    "xe", "vinfast", "vf", "ô tô", "oto",
    "điều hòa", "điều hoà", "máy lạnh", "nhiệt độ", "quạt gió", "sưởi",
    "ghế", "vô lăng", "tay lái", "gương", "kính", "cửa", "cốp", "nắp",
    "đèn", "pha", "cốt", "xi nhan", "sương mù",
    "nhạc", "âm lượng", "loa", "radio", "bluetooth", "điện thoại", "màn hình", "app", "ứng dụng",
    "lốp", "áp suất", "bánh", "phanh", "abs", "ga", "cruise", "hộp số",
    "pin", "sạc", "điện", "ắc quy", "cầu chì", "km", "quãng đường", "dặm",
    "dây an toàn", "túi khí", "camera", "cảm biến", "radar", "còi", "gạt nước", "gạt mưa",
    "chìa khóa", "chìa khoá", "khóa", "khoá",
    "bảo dưỡng", "bảo hành", "dầu", "nước làm mát", "nước rửa kính", "lọc gió",
    "động cơ", "mô tơ", "camp", "cắm trại", "chế độ", "cảnh báo", "báo lỗi", "đèn báo",
    "dẫn đường", "bản đồ", "định vị", "sổ tay", "hướng dẫn sử dụng",
    # Ba ca `hoi-nhu-tai-xe-v1` suýt mất đường tắt ở lần cài đầu (22/08): "không mang
    # chìa thì nổ máy kiểu gì", "gọi trợ lý ảo bằng câu gì", "cứu hộ dọc đường có mất phí không".
    "chìa", "nổ máy", "khởi động", "trợ lý", "cứu hộ", "dọc đường",
    # Phương ngữ Nam — thiếu chúng thì cùng một câu hỏi, giọng Bắc đi đường tắt sổ
    # tay còn giọng Nam rơi xuống model (đo 22/08, 28 ca của Sơn, issue #244).
    "kiếng", "thắng", "vô lăng", "dè", "xăng", "bình điện", "đề",
)


def co_tu_vung_xe(normalized: str) -> bool:
    """Câu (đã normalize) có nhắc tới xe hay một bộ phận/tính năng của xe không."""
    return any(tu in normalized for tu in _TU_VUNG_XE)
