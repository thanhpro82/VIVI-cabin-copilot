"""Bảng từ đồng nghĩa của router — **một** chỗ duy nhất cho mọi cách gọi tên.

## Vì sao tách khỏi `router.py`

Trước file này, mỗi matcher tự khai chuỗi cứng của riêng nó: `_match_hvac` biết
`điều hòa|nhiệt độ|quạt`, `_match_seat` biết `sưởi`, `_match_lights` bắt buộc có
token `đèn`. Không tra được ở đâu rằng "máy lạnh" là cách gọi khác của điều hòa,
nên mỗi lần thêm một cách nói là sửa một matcher — và mỗi matcher lệch nhau một ít.
Đợt báo lỗi 24/08 có **28/42 dòng** rơi vào lớp này.

Gom vào đây thì bảng có test riêng (`tests/test_agents/test_tu_dong_nghia.py`) và
một cách nói mới chỉ phải thêm đúng một chỗ.

## Luật khớp: theo TỪ, không theo chuỗi con

`co_cum()` so trên biên từ chứ không dùng `in` trần. Đây không phải chuyện sạch sẽ:
alias `"ac"` mà khớp bằng `in` sẽ trúng `"các"`, `"bác sĩ"`, `"khác"` — tức là biến
một câu hỏi sổ tay bất kỳ có chữ `các` thành lệnh điều hòa. Chuỗi vào đây đã qua
`normalize_vi` (thường hoá, bỏ dấu câu, gộp khoảng trắng) nên biên từ chính là dấu
cách, và phép so bằng `" cụm "` là đủ — không cần regex.

## Ranh giới cố ý KHÔNG mở rộng

- **Không thêm alias cho loại đèn ngoài bề mặt điều khiển.** `_UNSUPPORTED_LIGHTS`
  trong `router.py` tồn tại để câu về đèn sương mù/hazard **rơi xuống sổ tay**; nới
  ở đây là cách nhanh nhất làm tụt `question_recall` (đã đo: 0.9833 → 0.9667 khi
  danh sách ấy bị bỏ).
- **Không đoán tân ngữ.** `"dừng ngay"` không được ánh xạ thành `pause` nhạc: khi
  đang dẫn đường thì nó có nghĩa khác, và router không đọc trạng thái xe nên không
  có cơ sở để chọn. Đoán ở đây là làm một việc khác việc được yêu cầu — đúng lớp
  lỗi KI-001 mà cả đợt sửa này nhắm vào.
"""

from __future__ import annotations

#: Cách gọi hệ thống điều hòa. `điều hoà` không cần có mặt: `normalize_vi` đã hợp
#: nhất `hoà` → `hòa` trước khi chuỗi tới đây.
HVAC: tuple[str, ...] = (
    "điều hòa",
    "nhiệt độ",
    "máy lạnh",
    "ac",
    "hệ thống làm mát",
    "làm mát",
)

#: Cách gọi sưởi ghế. `làm ấm`/`hâm nóng` là cách nói đời thường; `sưởi` là chữ
#: dùng trong sổ tay.
SUOI_GHE: tuple[str, ...] = ("sưởi", "làm ấm", "hâm nóng")

#: `cụm -> trục` của `set_seat_position`. Thứ tự là hợp đồng, không phải trình bày:
#: `"dựng lưng ghế lái lên 40%"` chứa cả cụm lưng lẫn chữ `lên`, nên nhóm **recline
#: phải đứng trước nhóm height** — đảo lại là biến một lệnh ngả lưng thành lệnh nâng
#: ghế, tức là dịch chuyển sai bộ phận.
#:
#: Bản trước file này chỉ có `nâng ghế|hạ ghế` cho height và `ngả lưng|ngả ghế` cho
#: recline, nên bốn câu đo được ngày 24/08 (`dựng lưng...`, `đẩy ghế lái tới...`,
#: `đưa ghế lái lên cao...`, `đưa ghế lái xuống thấp...`) đều rơi xuống sổ tay.
TRUC_GHE: tuple[tuple[str, str], ...] = (
    ("ngả lưng", "recline"),
    ("ngả ghế", "recline"),
    ("dựng lưng", "recline"),
    ("lưng ghế", "recline"),
    ("lên cao", "height"),
    ("xuống thấp", "height"),
    ("độ cao", "height"),
    ("chiều cao", "height"),
    ("nâng ghế", "height"),
    ("hạ ghế", "height"),
    ("về trước", "fore_aft"),
    ("về sau", "fore_aft"),
    ("ra trước", "fore_aft"),
    ("ra sau", "fore_aft"),
    ("tiến", "fore_aft"),
    ("lùi", "fore_aft"),
    # `tới` chỉ an toàn vì người gọi đã biết câu nói về ghế (`_match_seat` đòi chữ
    # `ghế` trước khi vào đây). Ngoài ngữ cảnh ấy nó là từ của dẫn đường.
    ("tới", "fore_aft"),
)


def truc_ghe(text: str) -> str | None:
    """Trục ghế mà câu nói tới, hoặc `None`. Duyệt theo thứ tự bảng."""
    for cum, truc in TRUC_GHE:
        if co_cum(text, cum):
            return truc
    return None

#: Cụm đủ để biết câu đang nói về **đèn chiếu sáng phía trước**, kể cả khi không có
#: chữ `đèn`: *"chuyển sang chiếu gần"* là một câu hoàn chỉnh trong tiếng Việt.
DEN_PHIA_TRUOC: tuple[str, ...] = (
    "chiếu gần",
    "chiếu xa",
    "đèn cốt",
    "đèn cos",
    "đèn pha",
    "low beam",
    "high beam",
)

#: `alias -> mode` của `set_headlight_mode`. Thứ tự **quan trọng**: alias dài đứng
#: trước, và `chiếu xa` phải được xét trước `chiếu gần` ở phía người gọi vì một câu
#: có thể chứa cả hai (*"đổi từ chiếu gần sang chiếu xa"*) — xem `che_do_den()`.
CHE_DO_DEN: tuple[tuple[str, str], ...] = (
    ("high beam", "high_beam"),
    ("chiếu xa", "high_beam"),
    ("pha xa", "high_beam"),
    ("low beam", "low_beam"),
    ("chiếu gần", "low_beam"),
    ("đèn cốt", "low_beam"),
    ("đèn cos", "low_beam"),
    ("đèn pha", "low_beam"),
    ("tự động", "auto"),
    ("auto", "auto"),
)

#: Cách nói "phát tiếp bản nhạc đang dừng" mà **không** có chữ `nhạc`/`bài`.
TIEP_TUC_PHAT: tuple[str, ...] = ("tiếp tục phát", "phát tiếp", "nghe tiếp nhạc")


def co_cum(text: str, cum: str) -> bool:
    """`cum` có xuất hiện như một **cụm từ trọn vẹn** trong `text` không.

    So trên biên từ, nên `co_cum("các cửa", "ac")` là `False` trong khi
    `"ac" in "các cửa"` là `True`. Xem docstring module về lý do.
    """
    return f" {cum} " in f" {text} "


def co_bat_ky(text: str, cums: tuple[str, ...]) -> bool:
    """Có ít nhất một cụm trong `cums` xuất hiện trọn vẹn trong `text`."""
    return any(co_cum(text, cum) for cum in cums)


def che_do_den(text: str) -> str | None:
    """Chế độ đèn mà câu nói tới, hoặc `None`.

    Duyệt theo thứ tự bảng — `chiếu xa` trước `chiếu gần` — nên câu nêu cả hai
    (*"đổi từ chiếu gần sang chiếu xa"*) ra `high_beam`, tức là **đích đến**, không
    phải trạng thái đang có. Đảo thứ tự là biến câu ấy thành lệnh ngược hẳn.
    """
    for alias, mode in CHE_DO_DEN:
        if co_cum(text, alias):
            return mode
    return None


# ---------------------------------------------------------------------------
# Lớp ngữ nghĩa của động từ mở đầu (PR 2b của issue #308)
# ---------------------------------------------------------------------------
#
# Trước đây mỗi matcher tự liệt kê động từ của riêng nó, và **các tập con không
# đồng ý với nhau**: `chỉnh` có trong `_COMMAND_VERBS` nhưng `_match_window` chỉ
# nhận `mở|đóng|hạ|kéo|nâng`, nên `"chỉnh cửa sổ bên lái 25%"` chết trong khi
# `"chỉnh lưng ghế"` sống. Cùng một động từ, hai số phận, và không tra được ở đâu
# matcher nào cho phép gì.
#
# Từ đây matcher khai báo **lớp**, không liệt kê từ. Thêm một cách nói là thêm vào
# đúng một tuple, và mọi matcher dùng lớp ấy được hưởng cùng lúc.

#: Đặt một giá trị **tuyệt đối**. Không bao gồm `tăng`/`giảm`: đó là lượng tương
#: đối, và router không đọc trạng thái xe nên không tính được (xem `coverage_matrix`
#: §Cách nói về lượng). Trộn chúng vào đây là mở đường cho một phép đoán.
DAT_TUYET_DOI: tuple[str, ...] = ("đặt", "chỉnh", "để", "cho", "đưa", "chuyển", "đổi")

#: Bật / khởi động một hệ thống.
BAT: tuple[str, ...] = ("bật", "mở", "khởi động", "bắt đầu")

#: Tắt một hệ thống.
TAT: tuple[str, ...] = ("tắt",)

#: Tăng/giảm — giữ **riêng** để nơi nào chấp nhận lượng tương đối thì tự khai.
TANG_GIAM: tuple[str, ...] = ("tăng", "giảm")

#: Mở/dịch chuyển một bộ phận cơ khí (kính, ghế, cốp).
MO_VAT_LY: tuple[str, ...] = ("mở", "hạ", "kéo", "nâng", "dựng", "đẩy", "trượt", "di chuyển", "đưa")

#: Đóng một bộ phận cơ khí.
DONG_VAT_LY: tuple[str, ...] = ("đóng",)

#: Phát nhạc. `cho tôi nghe` là một cụm đủ nghĩa, không phải tiền tố lịch sự —
#: `_POLITE_PREFIX_PATTERN` không bóc nó.
PHAT: tuple[str, ...] = ("phát", "chơi", "nghe", "mở", "bật", "bắt đầu", "khởi động", "cho tôi nghe", "cho nghe")

#: Dẫn đường — động từ **tường minh**, nói rõ là đi đâu đó.
DAN_DUONG_RO: tuple[str, ...] = ("dẫn đường", "chỉ đường", "mở bản đồ", "tìm đường")

#: Dẫn đường — động từ **mơ hồ**, có thể là câu hỏi sổ tay. Khi không tra được địa
#: điểm nào thì matcher phải **nhường** cho sổ tay thay vì hỏi lại; xem
#: `_match_navigation`. Đó là lý do hai bảng tách nhau chứ không gộp làm một.
DAN_DUONG_MO_HO: tuple[str, ...] = ("đưa tôi tới", "đưa tôi đến", "dẫn", "đi tới", "đi đến", "đi")


# ---------------------------------------------------------------------------
# Vế dẫn nhập ở đầu câu (PR 2c của issue #308)
# ---------------------------------------------------------------------------

#: Từ gọi/ậm ừ đứng trước một câu lệnh. Người ta gọi tên trợ lý rồi mới ra lệnh, và
#: STT chép nguyên cả tiếng gọi ấy vào transcript.
GOI_VA_AM_U: tuple[str, ...] = (
    "vivi ơi",
    "này vivi",
    "ê vivi",
    "ơ vivi",
    "alo vivi",
    "vivi",
    "ờ",
    "à",
    "ừm",
    "ừ thì",
    # `thôi` cố ý KHÔNG có mặt. Nó là **từ rút lại** trong `"à thôi"`, `"thôi khỏi"` —
    # tức là dấu hiệu tự sửa lời, đúng thứ một issue riêng đang nhắm vào. Bóc nó ở
    # đây thì `"bật điều hòa à thôi"` mất luôn tín hiệu huỷ và biến thành lệnh bật.
    "ê",
    "này",
    # Cách nói ý định. Không phải ậm ừ, nhưng bóc được vì cùng một luật: phần còn lại
    # phải tự khớp `control`. `"tôi muốn biết áp suất lốp bao nhiêu"` để lại một câu
    # hỏi, không phải lệnh, nên không bóc được — và đó chính là hàng rào.
    "tôi muốn",
    "mình muốn",
    "tui muốn",
    "cho tôi",
    "cho mình",
)

#: Số từ tối đa của một vế dẫn nhập. 3 vừa đủ cho `"vivi ơi"`, `"nóng quá"`,
#: `"trong xe nóng quá"` — và đủ ngắn để không nuốt được nửa đầu của một câu ghép.
MAX_TU_TIEN_TO = 3
