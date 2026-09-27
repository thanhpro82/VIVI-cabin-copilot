"""Router luật cho lệnh điều khiển tiếng Việt.

Kỹ thuật ở đây kế thừa `experiments/offline_poc/src/offline_poc/control_router.py`
(đã đo 95% downstream tool-exact trên dataset `poc/v2`), nhưng contract thì theo
`docs/agent_spec.md`: router **chỉ** sinh `CandidateActionPlan`, không gán safety.

Nguyên tắc bất di bất dịch của file này:

- Thiếu slot bắt buộc thì hỏi lại (`clarify`), **không đoán**.
- Giá trị ngoài khoảng thì từ chối (`denied`), **không kẹp về biên**.
- Mỗi matcher đòi hỏi cả từ khóa domain lẫn động từ điều khiển ở đầu câu, để
  câu hỏi tra cứu không bị hiểu nhầm thành lệnh.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

from src.agents.contracts import (
    CandidateActionPlan,
    CandidateStep,
    Disposition,
    Intent,
    RouteDecision,
)
from src.agents.question import (
    DAU_SUA_LOI,
    DAU_SUA_LOI_RO,
    NEO_SO_KHONG,
    bo_tieu_tu_cuoi,
    co_tu_vung_xe,
    is_information_question,
    is_negated,
    is_question,
)
from src.agents.routines_intent import doc_y_dinh
from src.agents.tu_dong_nghia import (
    BAT,
    DAN_DUONG_MO_HO,
    DAN_DUONG_RO,
    DAT_TUYET_DOI,
    DEN_PHIA_TRUOC,
    DONG_VAT_LY,
    GOI_VA_AM_U,
    HVAC,
    MAX_TU_TIEN_TO,
    MO_VAT_LY,
    PHAT,
    SUOI_GHE,
    TANG_GIAM,
    TAT,
    TIEP_TUC_PHAT,
    che_do_den,
    co_bat_ky,
    truc_ghe,
)
from src.fixtures import (
    load_poi_fixture,
    loai_poi_tu_alias,
    poi_alias_map,
    tim_poi_theo_loai,
    tim_track_theo_ten,
)
from src.services.tool_registry import TOOL_REGISTRY

MatchResult = tuple[Disposition, Intent, str, tuple[CandidateStep, ...]]

_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{1,3})(?!\d)")
_POLITE_PREFIX_PATTERN = re.compile(r"^(?:(?:hãy|vui lòng|làm ơn|giúp tôi)\s+)*")
# `phần trăm` là ĐƠN VỊ, không phải số. Để nguyên thì `_number` thấy token `trăm`
# và tưởng đó là toán tử hàng trăm — issue #117.
_PERCENT_UNIT_PATTERN = re.compile(r"\bphần trăm\b")

# Phân số và số thập phân viết bằng chữ số. `normalize_vi` xoá mọi dấu câu, nên
# `1/3` từng thành `"1 3"` rồi `_NUMBER_PATTERN` nhặt **1** và mở kính 1% trong im
# lặng. Hai regex dưới chạy TRƯỚC lúc xoá dấu, và chỉ khớp khi dấu nằm **giữa hai
# chữ số** — dấu phẩy ngăn vế câu và dấu chấm cuối câu vẫn bị xoá như cũ.
_DIGIT_FRACTION_INFIX = re.compile(r"(?<=\d)\s*/\s*(?=\d)")
_DIGIT_DECIMAL_INFIX = re.compile(r"(?<=\d)\s*[.,]\s*(?=\d)")
_FRACTION_PATTERN = re.compile(r"(?<!\d)(\d{1,3}) chia (\d{1,3})(?!\d)")
_DECIMAL_PATTERN = re.compile(r"(?<!\d)(\d{1,3}) phẩy (\d{1,2})(?!\d)")

_NUMBER_WORDS = {
    "không": 0,
    "một": 1,
    "mốt": 1,
    "hai": 2,
    "ba": 3,
    "bốn": 4,
    "tư": 4,
    "năm": 5,
    "lăm": 5,
    # `nhăm`/`bẩy` là biến thể Bắc Bộ, không phải lỗi chính tả — STT chép đúng cái
    # người ta nói. Thiếu chúng thì `"hai mươi nhăm"` ra **20** và `"ba bẩy"` ra **3**:
    # mất chữ số cuối trong im lặng, đúng lớp lỗi KI-001.
    "nhăm": 5,
    "sáu": 6,
    "bảy": 7,
    "bẩy": 7,
    "tám": 8,
    "chín": 9,
}

# `mười` (10) và `mươi` (toán tử hàng chục) là hai từ khác nhau, và `mười` KHÔNG
# được đưa vào bảng trên: nhánh cặp số liền kề dưới `_number` sẽ đọc `"mười lăm"`
# thành 10*10 + 5 = 105. Nó thuộc về nhánh hàng chục, với hệ số cố định bằng 1.
# `chục` cùng lớp với `mươi`: `"hai chục"` = 20, trước đây đọc ra 2.
_TENS_TOKENS = ("mươi", "mười", "chục")

# Phân số viết chữ: `"một phần ba"`. Chạy SAU khi cắt `phần trăm` nên không đụng
# nhau. Trước đây vòng quét ngược lấy **mẫu số**: `"ba phần tư"` ra 4%.
_WORD_FRACTION_PATTERN = re.compile(r"\b(\w+) phần (\w+)\b")
_HALF_TOKENS = ("nửa", "rưỡi")

# Lượng không xác định. `"mười mấy"` là 11..19, người nói cố ý không chốt; đoán 10
# là sai kiểu tệ nhất. `"mấy chục"` vốn đã hỏi lại, đây là mở rộng cùng nguyên tắc.
_INDEFINITE_TOKENS = ("mấy", "vài", "dăm")

# Lượng định tính — không quy ra số được. `"mở cửa sổ một chút"` từng ra 1%.
_QUALITATIVE_TOKENS = ("chút", "tí", "xíu", "hé", "tẹo")

# Cách nói "kịch mức". Là cụm chứ không phải token: `"hết"` một mình vẫn có nghĩa
# khác (xem `_ALL_POSITIONS`), nên phải khớp nguyên cụm.
#: Cách nói "mở toang" — `percent = 100`.
#:
#: `"hạ hết"` và `"xuống hết"` thêm 30/08 (#368). Chúng đáng chú ý vì `percent` đo
#: **độ mở**, không đo độ hạ: *"hạ hết xuống"* là **100**, không phải 0. Viết theo
#: nghĩa đen của chữ *"hạ… xuống"* thì ra 0 — tức **đóng kín** cửa sổ cho một tài xế
#: vừa xin thoáng khí, và ở bối cảnh #339 đó là lúc xe đang chạy.
#:
#: Thiếu hai cách nói này thì xe **đề nghị một việc mà chính nó không hiểu** khi tài
#: xế nhắc lại nguyên văn — mặc định của #339 là "không nói gì thì hạ hết xuống".
_MAXIMUM_PHRASES = ("mở hết", "hạ hết", "xuống hết", "hết cỡ", "hết mức", "hoàn toàn", "tối đa", "toang", "kịch")

# Lệnh tương đối. Router KHÔNG đọc vehicle state (ADR-011) nên không cộng trừ được
# từ mức hiện tại; đọc `"tăng âm lượng thêm 10"` thành `set_volume 10` có thể làm
# đúng điều ngược lại ý người dùng. Nhánh quạt gió đã hỏi lại từ trước, hai nhánh
# kia thì không — cùng hạn chế, hai hành vi trái ngược.
_RELATIVE_TOKENS = ("thêm", "bớt")
#: Cách gọi cửa sổ điện. `"kính"` trần thêm 15/08 (issue #96): đó là cách nói phổ
#: biến nhất trong xe, và `set_window_position` đã hỗ trợ đầy đủ — để nó rơi về tra sổ
#: tay là trả lời sai chủ đề cho một câu nằm **trong** phạm vi.
#: `"kiếng"` là cách gọi cửa kính ở miền Nam. Thiếu nó thì `"hạ kiếng xuống chút coi"`
#: KHÔNG khớp matcher nào và rơi xuống model, trong khi `"hạ kính xuống một tí"` khớp
#: thẳng — một lệnh điều khiển đi hai đường chỉ vì giọng (đo 22/08, issue #244).
_CUA_SO_TERMS = ("cửa sổ", "cửa kính", "kính", "kiếng")

#: Cụm chứa `"kính"` nhưng không phải kính cửa. Phải loại **trước** khi nhận, và đây
#: là phần đắt nhất của issue #96 chứ không phải việc thêm `"kính"`.
#:
#: `set_window_position` là **S2**. Khớp nhầm ở đây không cho ra một câu trả lời lạc
#: đề — nó cho ra một *lời xin phê duyệt hạ kính* trong lúc người dùng đang hỏi về
#: gương chiếu hậu. Đó là đổi một lỗi im lặng sai lấy một lỗi ồn ào sai hơn.
#:
#: Không có tool nào cho gương/kính chắn gió (xem `docs/coverage_matrix.md`), nên
#: đường đúng của chúng vẫn là tra sổ tay theo ADR-011.
_KINH_KHONG_PHAI_CUA_SO = ("kính chiếu hậu", "kính chắn gió", "kính lái", "kính hậu")

_ACTUATOR_TOKENS = (
    "điều hòa",
    "nhiệt độ",
    "quạt",
    "nhạc",
    "âm lượng",
    "cửa sổ",
    "cửa kính",
    # `"kính"` trần cũng là actuator: `"đừng mở kính bên lái"` phải `denied` như
    # `"đừng mở cửa sổ bên lái"`. Bỏ sót thì phủ định chỉ chặn được nhờ dạng mệnh
    # lệnh, tức phụ thuộc cách người ta đặt câu chứ không phải vào thứ họ nhắm tới.
    "kính",
    "sưởi",
    "ghế",
    "cửa",
    "cốp",
    "đèn",
)
# `cốp xe`/`cốp sau` đã rời danh sách này 2026-08-12: cốp giờ là actuator thật
# (`set_trunk_state`, domain `trunk`). Xem ADR-020.
_UNSUPPORTED_TOKENS = ("phanh abs", "phanh tay", "động cơ", "túi khí")

#: `đừng/chớ/chẳng` phủ định ở mọi vị trí — trùng `_HARD_NEGATIONS` bên
#: `question.py`, chép sang đây để tránh import vòng (question không được kéo router).
_PHU_DINH_CUNG = frozenset({"đừng", "chớ", "chẳng"})


def _phu_dinh_ta_trieu_chung(text: str) -> bool:
    """Chữ "không" đang TẢ trạng thái, không phải ra lệnh phủ định.

    Dấu hiệu tất định: actuator đứng TRƯỚC chữ "không" — "Đèn trong xe cứ sáng
    hoài **không tắt**" có `đèn` trước, là lời tả cái đèn; "**Không tắt** đèn"
    có actuator sau, là lệnh. Chỉ áp cho "không" trần: `đừng/chớ/chẳng` là phủ
    định mệnh lệnh ở mọi vị trí, không bao giờ tả triệu chứng.

    Run `20260821T130203` đo được đúng hai ca lớp này bị `negated_command` nuốt
    thành `denied` — tài xế than đèn không tắt và nhận câu "tôi không làm việc
    đó", thay vì được tra sổ tay.
    """
    tokens = text.split()
    if _PHU_DINH_CUNG & set(tokens):
        return False
    if "không" not in tokens:
        return False
    truoc = " ".join(tokens[: tokens.index("không")])
    return any(t in truoc for t in _ACTUATOR_TOKENS)


_AMBIGUOUS_TEXTS = {"mở nó ra", "đặt thấp hơn", "đặt cao hơn", "bật nó lên", "tắt nó đi"}

#: Media là domain duy nhất người ta gọi bằng cụm danh từ trần — "bài trước",
#: "bài tiếp theo" — chứ không nhất thiết có động từ điều khiển ở đầu câu. Cho
#: phép được vì `_match` đã lọc mọi dạng nghi vấn **trước** khi tới matcher, nên
#: "bài trước tên gì?" không thể lọt vào đây.
_PREVIOUS_TRACK = ("bài trước", "bài hát trước", "bản trước")
_NEXT_TRACK = ("bài tiếp", "bài hát tiếp", "bài sau", "bài hát sau", "bài kế")

#: Cụm chứa `"tiếng"` nhưng **không** nói về âm thanh của dàn nhạc. Loại **trước**
#: khi nhận, đúng khuôn `_KINH_KHONG_PHAI_CUA_SO`: chữ `tiếng` mang bốn lớp nghĩa
#: trong tiếng Việt và chỉ một lớp là actuator, nên nhánh tắt tiếng là nhánh dễ
#: cướp câu của miền khác nhất trong cả bộ luật.
#:
#: Bốn lớp ấy, đo trên develop @ `1477a26` (27/08) — **cả bốn đang ra `not_control`**,
#: tức đường đúng của chúng đã là tra sổ tay theo ADR-011 và nhánh mới không được
#: làm hỏng:
#:
#:     "tắt tiếng còi"          -> còi không có tool (docs/coverage_matrix.md nhóm 5)
#:     "xe có tiếng kêu lạ"     -> tả triệu chứng, câu hỏi sổ tay
#:     "chuyển sang tiếng việt" -> tên ngôn ngữ, không phải âm thanh
#:     "tiếng động cơ to quá"   -> tả triệu chứng, câu hỏi sổ tay
#:
#: Khác `_UNSUPPORTED_LIGHTS` ở một điểm và điểm ấy quan trọng: ở đây câu **có**
#: một actuator thật đứng cạnh (`media_control` biết chỉnh âm lượng), nên khớp
#: nhầm không cho ra `clarify` lạc đề mà cho ra một lệnh **chạy thật** — tắt câm
#: dàn nhạc trong lúc người ta đang hỏi vì sao xe kêu.
_TIENG_KHONG_PHAI_AM_THANH = (
    "tiếng còi",
    "tiếng ồn",
    "tiếng động cơ",
    "tiếng kêu",
    "tiếng rít",
    "tiếng gõ",
    "tiếng bíp",
    "tiếng chuông",
    "tiếng cảnh báo",
    "tiếng việt",
    "tiếng anh",
)

#: Danh từ chỉ **âm lượng dàn nhạc**. `"nhạc"` cố ý KHÔNG có mặt: `"tắt nhạc"` là
#: `pause` (issue Đ7/#314), không phải tắt tiếng — hai việc khác nhau, xem
#: `_match_media_mute`.
_DANH_TU_AM_THANH = ("tiếng", "âm thanh", "âm lượng")

#: Cách nói bảo xe **thôi phát tiếng** mà không gọi tên `nhạc`. Khớp **neo đầu câu**
#: (`_starts_with_command`), không phải chứa-là-khớp: `"xe chạy im lặng quá"` và
#: `"làm sao cho cabin im lặng hơn"` là câu tả/câu hỏi sổ tay, và biến chúng thành lệnh
#: là đúng lớp lỗi mà `_TIENG_KHONG_PHAI_AM_THANH` phải dựng cả một bảng loại trừ để
#: tránh. Ở đây neo đầu câu làm được việc ấy mà không cần bảng.
_IM_LANG = ("im lặng", "im đi", "yên lặng")

#: Động từ mở đầu một câu **gọi tên bài**. Rộng hơn tập của nhánh play chung (`phát`,
#: `bật`, `mở`) vì gọi đích danh một bài thì `chơi`/`nghe` là cách nói tự nhiên nhất —
#: và ở đây mở rộng an toàn hơn hẳn: câu phải chứa một cái tên có thật trong playlist
#: (tập đóng 5 bài) thì mới khớp, không phải chỉ chứa chữ `nhạc`.
_PHAT_TRACK_VERBS = ("phát", "bật", "mở", "chơi", "nghe")

#: Từ đứng ngay sau `bài` mà **không** phải tên bài. Thiếu bảng này thì "phát bài hát"
#: — một cách nói `play` chung — bị đọc thành lời gọi một bài tên "hát" rồi từ chối.
_SAU_BAI_KHONG_PHAI_TEN = frozenset(
    "hát trước sau tiếp kế này đó khác nữa mới cũ gì nào đi thôi nhé nào đó".split()
)

#: Chỉ định "cả xe" thay cho một vị trí cụ thể.
_ALL_POSITIONS = ("tất cả", "toàn bộ", "mọi ")

#: Loại đèn hệ thống **không** điều khiển được (xem `docs/coverage_matrix.md` nhóm 5).
#: Câu nhắc tới chúng phải rơi xuống tra sổ tay theo ADR-011, **không** được hỏi lại
#: về một loại đèn khác mà ta có. Bỏ danh sách này thì `"Bật đèn nháy cảnh báo nguy
#: hiểm bằng cách nào?"` — một câu hỏi sổ tay hợp lệ — trả `clarify missing_light_target`,
#: và `question_recall` tụt 0.9833 -> 0.9667.
_UNSUPPORTED_LIGHTS = (
    "sương mù",
    "nháy",
    "cảnh báo",
    "khẩn cấp",
    "xi nhan",
    "báo rẽ",
    "đèn phanh",
    "đèn lùi",
    "đèn đỗ",
    "đọc sách",
    "chào mừng",
    "ambient",
)

#: Mọi động từ mở đầu mà các matcher chấp nhận. Dùng để phân biệt câu mệnh lệnh
#: với câu trần thuật/hỏi khi áp guard phủ định và guard actuator không hỗ trợ.
#: Dựng từ các lớp ngữ nghĩa (`tu_dong_nghia`) **cộng** những từ chỉ có nghĩa ở
#: đúng một miền (`tạm dừng`, `ngả`, `quay lại`...). Trước 2b đây là một danh sách
#: viết tay, và nó lệch với tập từ mà từng matcher thật sự chấp nhận — `chỉnh` có ở
#: đây nhưng `_match_window` không nhận, nên guard phủ định coi câu là mệnh lệnh
#: trong khi matcher lại bỏ qua nó.
#:
#: `dict.fromkeys` để khử trùng lặp mà **giữ nguyên thứ tự** — thứ tự này đi vào
#: `_COMMAND_VERBS_DAI_TRUOC` và ảnh hưởng chỗ cắt câu ghép.
_COMMAND_VERBS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            *BAT,
            *TAT,
            *DAT_TUYET_DOI,
            *TANG_GIAM,
            *MO_VAT_LY,
            *DONG_VAT_LY,
            *PHAT,
            *DAN_DUONG_RO,
            *DAN_DUONG_MO_HO,
            "hạ",
            "tạm dừng",
            "dừng",
            "hủy",
            "tiếp",
            "ngả",
            "quay lại",
        )
    )
)

#: Bốn vị trí cửa/kính, dùng khi lệnh nhắm cả xe thay vì một vị trí.
_ALL_SIDES: tuple[str, ...] = ("front_left", "front_right", "rear_left", "rear_right")

#: Câu **đã** nhắm một đích cụ thể nhưng chưa đủ để xác định đúng một cửa.
#:
#: `_side()` trả `None` cho cả hai loại câu rất khác nhau: câu không nêu vị trí gì
#: (*"mở cửa"* — nút toàn xe, quyết định T36) và câu nêu **nửa** vị trí (*"mở cửa bên
#: trái"* — thiếu hàng ghế). `_match_door` đọc `None` là "nhắm cả xe", nên loại thứ
#: hai nở thành kế hoạch mở **cả bốn cửa**.
#:
#: Đẩy plan bốn cửa ấy qua HITL **không** phải hàng rào: người dùng đã nói rõ họ muốn
#: một phía, nên thứ họ nhìn thấy ở màn duyệt là ba cửa mình chưa từng yêu cầu, và việc
#: duy nhất họ làm được là từ chối. Một câu hỏi lại đúng chỗ rẻ hơn hẳn (review #301).
#:
#: Chỉ liệt kê cụm **tường minh nhắm đích**. `"tất cả"`/`"toàn bộ"` (xem `_ALL_POSITIONS`)
#: đi hướng ngược lại và vẫn phải ra bốn cửa; `"mở cửa"` trần cũng vậy.
#:
#: `"sau bên trái"`/`"sau bên phải"` **không** cần loại trừ ở đây dù chúng chứa
#: `"bên trái"`: `_side()` khớp chúng trước và trả về một vị trí, nên bảng này chỉ được
#: đọc tới khi `_side()` đã bó tay.
_VI_TRI_CHUA_DU: tuple[str, ...] = (
    "bên trái",
    "bên phải",
    "phía trái",
    "phía phải",
    "bên tay trái",
    "bên tay phải",
)

#: Liên từ tách hai ý trong một lượt. Dấu phẩy **không** có mặt ở đây và không thể
#: có: `normalize_vi` bỏ mọi dấu câu trước khi văn bản tới matcher, nên `"tắt điều
#: hòa, tắt quạt gió"` đến đây đã là `"tắt điều hòa tắt quạt gió"`. Đường voice thì
#: còn không sinh dấu câu bao giờ. Lượt ghép không mang liên từ do đó là ca **thường**
#: chứ không phải ngoại lệ, và `_split_fan_and_rest` mới là chỗ lo cho nó.
_CONJUNCTIONS: tuple[str, ...] = ("và", "rồi", "với", "cùng")
_CONJUNCTION_PATTERN = re.compile(rf" (?:{'|'.join(_CONJUNCTIONS)}) ")
#: Nối các vế không phải quạt lại để dò từ khóa và đọc số. Dùng lại một liên từ bất
#: kỳ là đủ — `rest` không bao giờ được đem ra hiển thị.
_CONJUNCTION_JOIN = " và "

#: Trần số vế trong một lượt ghép (issue #223). Bảng kịch bản có tối đa 4 ý
#: (`"... và quạt gió mức 2 và mở nhạc và bật đèn trần"`), nên 4 là mức vừa đủ chứa
#: mọi ca thật mà vẫn chặn một bản chép STT trôi dài đẻ ra kế hoạch chục bước.
_MAX_CLAUSES = 4

#: `_COMMAND_VERBS` sắp dài-trước-ngắn, dùng khi dò động từ mở đầu một vế. Thiếu thứ
#: tự này thì `tạm dừng` bị `dừng` nuốt và "tạm dừng nhạc" thành một lệnh khác.
_COMMAND_VERBS_DAI_TRUOC: tuple[str, ...] = tuple(sorted(_COMMAND_VERBS, key=len, reverse=True))

#: Dấu sửa lời, dài trước ngắn — `"à thôi"` phải thắng `"không"` khi cả hai cùng
#: xuất hiện, và `"à không"` phải thắng `"không"` trần.
_DAU_SUA_LOI_DAI_TRUOC: tuple[str, ...] = tuple(sorted(DAU_SUA_LOI, key=len, reverse=True))

#: Những khoá args trỏ **đích** thao tác chứ không phải giá trị đặt vào đích ấy.
#:
#: Dùng để phát hiện hai vế cùng nhắm một đích. `percent`/`level`/`temperature_c`/
#: `volume`/`value`/`enabled`/`state`/`mode` cố ý **không** có mặt: chúng chính là thứ
#: phải khác nhau thì mới gọi là mâu thuẫn. `action` có mặt vì với `media_control` nó
#: đóng vai đích (`set_volume` và `next` là hai việc khác nhau, không phải hai giá trị
#: của một việc).
_TARGET_ARG_KEYS: frozenset[str] = frozenset({"window", "door", "seat", "axis", "app", "action", "operation"})


def _consecutive_runs(positions: list[int]) -> list[list[int]]:
    """Gom các chỉ số liền nhau thành từng cụm: `[1,2,5,6,7]` → `[[1,2],[5,6,7]]`."""
    runs: list[list[int]] = []
    for position in positions:
        if runs and position - runs[-1][-1] == 1:
            runs[-1].append(position)
        else:
            runs.append([position])
    return runs


def normalize_vi(text: str) -> str:
    """NFC → casefold → hợp nhất `hoà`/`hòa` → bỏ ký tự không phải chữ/số/`%`.

    Dấu giữa hai chữ số được đổi thành từ **trước** khi xoá dấu câu, nếu không thì
    `1/3` thành `"1 3"` và parser nhặt số đầu tiên — mở kính 1% trong im lặng. Chỉ
    dấu nằm giữa hai chữ số mới được đổi, nên dấu phẩy ngăn vế câu và dấu chấm cuối
    câu vẫn bị xoá y như cũ (`_CONJUNCTION` vẫn là ` và `, không phải dấu phẩy).
    """
    normalized = unicodedata.normalize("NFC", text).casefold()
    normalized = normalized.replace("hoà", "hòa")
    normalized = _DIGIT_FRACTION_INFIX.sub(" chia ", normalized)
    normalized = _DIGIT_DECIMAL_INFIX.sub(" phẩy ", normalized)
    normalized = re.sub(r"[^\w%]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


#: Tài xế trả lời lời mời "Bạn có muốn nghe tiếp nguyên văn không?" (S3).
#:
#: Cố ý **không** nhận "có" / "vâng" / "ok" trần. Đó là ranh giới an toàn chứ không
#: phải chuyện tiện dụng: HITL cũng hỏi có/không, và nuốt "có" ở đây nghĩa là một lượt
#: xác nhận mở cửa có thể bị chuyển hướng — hoặc ngược lại, tài xế định xác nhận lại
#: nghe đọc sổ tay. Chỉ nhận cụm **nói rõ là đọc/nghe tiếp**.
#:
#: Khớp trên chuỗi đã qua `normalize_vi` (thường, bỏ dấu câu). "Nối tiếp ắc quy" không
#: khớp vì luật đòi động từ đọc/nghe đứng ngay trước "tiếp".
#: Câu hỏi về **áp suất** lốp — và luật này cố ý **hẹp**.
#:
#: Bảng curate chỉ trả lời được đúng một loại câu: *con số áp suất bơm là bao nhiêu*. Nó
#: không trả lời được "cảm biến báo lỗi thì làm sao", "lốp non hơi có nguy hiểm không",
#: "bơm lốp ở đâu" — mà sổ tay thì trả lời được cả ba. Bắt rộng nghĩa là **cướp** những
#: câu ấy khỏi nhánh sổ tay rồi đọc cho tài xế một con số không liên quan.
#:
#: Bản đầu chỉ đòi "có ý áp suất" + "có ý lốp", và @thanhpro82 chỉ ra nó bắt cả năm ca
#: trên (review #168). Nên thêm vế thứ ba: câu phải **hỏi số lượng**.
_AP_SUAT = re.compile(r"áp suất|bơm|căng hơi|non hơi", re.IGNORECASE)
_LOP = re.compile(r"\blốp\b|\bbánh xe\b|\bvỏ xe\b", re.IGNORECASE)

#: Dấu hiệu đang hỏi **con số**. Thiếu nó thì câu nói về lốp nhưng không xin giá trị —
#: để sổ tay trả lời.
_HOI_SO = re.compile(r"bao nhiêu|mấy\b|tiêu chuẩn|khuyến nghị|đúng chuẩn|bơm bao", re.IGNORECASE)

#: Câu hỏi *"cảm biến"*, *"đèn báo"*, *"cảnh báo"* thuộc về TPMS, không thuộc bảng số.
_KHONG_PHAI_SO = re.compile(r"cảm biến|đèn báo|báo lỗi|cảnh báo|nguy hiểm|ở đâu|thay|mòn|đảo lốp", re.IGNORECASE)

#: Trục nào. Neo vào danh từ bộ phận: `\bsau\b` trần bắt cả *"sau khi chạy đường dài"*
#: và trả về đúng một trục — ngược lại lý lẽ của chính luật này, vì nói một số rồi im là
#: để tài xế bơm sai đầu còn lại.
_TRUC_TRUOC = re.compile(r"\b(?:trục|bánh|lốp)\s+trước\b|\bphía trước\b", re.IGNORECASE)
_TRUC_SAU = re.compile(r"\b(?:trục|bánh|lốp)\s+sau\b|\bphía sau\b", re.IGNORECASE)
_DU_PHONG = re.compile(r"dự phòng|sơ cua|sơ-cua", re.IGNORECASE)


def _truc_ap_suat_lop(text: str) -> str | None:
    """`"front"` / `"rear"` / `"spare"` / `"all"`, hoặc `None` nếu không phải câu hỏi này."""
    if not (_AP_SUAT.search(text) and _LOP.search(text)):
        return None
    if _KHONG_PHAI_SO.search(text):
        return None
    if not _HOI_SO.search(text):
        return None
    if _DU_PHONG.search(text):
        return "spare"
    truoc, sau = bool(_TRUC_TRUOC.search(text)), bool(_TRUC_SAU.search(text))
    if truoc and not sau:
        return "front"
    if sau and not truoc:
        return "rear"
    return "all"


#: Động từ mở đầu một câu dẫn đường.
#:
#: `"dẫn đường"` là **tường minh**: câu nào bắt đầu bằng nó thì chắc chắn nói về dẫn
#: đường, nên không khớp địa điểm nào vẫn `clarify` — hỏi lại đúng thứ còn thiếu.
#:
#: Ba động từ còn lại **mơ hồ**: *"đi tới đâu thì hết pin"* mở đầu bằng `đi tới` nhưng
#: là câu tra sổ tay. Nên chúng chỉ khớp khi câu **có** một địa điểm trong fixture;
#: không có thì nhường, câu rơi về tra sổ tay theo ADR-011. Thiếu vế thu hẹp này là
#: đúng lớp lỗi @thanhpro82 bắt ở luật áp suất lốp (review #168).
#: Động từ mở đầu một câu TÌM địa điểm.
_TIM_VERB: tuple[str, ...] = ("tìm", "kiếm")

#: Cụm "quanh xe" — BẮT BUỘC phải có. Thiếu nó thì `"tìm cà phê"` (có thể là tìm
#: trong danh bạ, tìm bài hát, tìm mục sổ tay) cũng thành lệnh dẫn đường.
_QUANH_DAY: tuple[str, ...] = ("gần đây", "gần nhất", "quanh đây", "gần đó", "ở đây")

#: Từ chỉ SỐ NHIỀU — dấu hiệu tài xế muốn xem lựa chọn chứ không muốn đi luôn.
#: Tập đóng (spec SP-5 §2.1); đây là TOÀN BỘ cách phân biệt "đi luôn" với "cho tôi
#: chọn", nên thêm bớt ở đây là đổi hành vi sản phẩm, không phải chỉnh từ vựng.
_SO_NHIEU: tuple[str, ...] = ("các ", "những ", "mấy ", "bao nhiêu ")

#: Vế dẫn đường **hồi chỉ**: `"… rồi dẫn đường tới ĐÓ"`. Đại từ trỏ về vế trước chứ
#: không nêu đích mới, nên đó không phải một việc riêng — xem `_segment_clauses`.
_VE_HOI_CHI = re.compile(r"^(?:rồi\s+)?(?:dẫn đường|đưa tôi|đi)\s+(?:tới|đến)\s+(?:đó|đấy|chỗ đó|chỗ đấy)\s*$")

#: `"tìm hiểu"` là HỎI, không phải TÌM. Loại trừ **trước** khi nhận, cùng khuôn với
#: `_KINH_KHONG_PHAI_CUA_SO`: `"tìm hiểu về áp suất lốp"` phải đi tra sổ tay. Đây
#: chính là ô cổng cứng `manual→control` mà cả hệ thống đang giữ bằng 0, và matcher
#: tìm-POI là đường MỚI duy nhất có thể làm vỡ nó.
_TIM_KHONG_PHAI_TIM_POI: tuple[str, ...] = ("tìm hiểu", "cách tìm", "làm sao tìm", "tìm thấy")

_NAV_VERB_TUONG_MINH = "dẫn đường"
_NAV_VERB_MO_HO: tuple[str, ...] = ("tìm đường", "đưa tôi tới", "đưa tôi đến", "đi tới", "đi đến")


#: App giải trí mở được bằng giọng nói. Enum **đóng** — ADR-023: "mở app tuỳ ý" và
#: "URL tuỳ ý" nằm ngoài phạm vi P0. Alias dài đứng trước alias ngắn.
_APP_ALIASES: tuple[tuple[str, str], ...] = (
    ("you tube", "youtube"),
    ("youtube", "youtube"),
    ("tik tok", "tiktok"),
    ("tiktok", "tiktok"),
    ("spotify", "spotify"),
)

#: Cái gì được phép đứng **sau** tên app mà câu vẫn là "mở app".
#:
#: Luật này hẹp có chủ ý. Bản đầu chỉ đòi "động từ mở + tên app", và nó bắt cả
#: *"mở youtube xem hướng dẫn thay lốp"* — một câu tra sổ tay — rồi mở app thay vì trả
#: lời. Đúng lớp lỗi @thanhpro82 bắt ở luật áp suất lốp (review #168): vế nhận diện
#: đúng nhưng thiếu vế thu hẹp thì luật **cướp** câu của nhánh khác.
#:
#: Nên: tên app phải đứng cuối câu, chỉ được theo sau bởi tiểu từ. Có mệnh đề mục đích
#: thì luật này nhường, câu rơi về tra sổ tay theo ADR-011.
#: Đuôi nghi vấn nằm trong danh sách cho phép, không phải ngoại lệ: *"mở YouTube được
#: không?"* vẫn là câu **về việc mở YouTube**, và ADR-011 muốn nó ra `offer` — nêu ý
#: định rồi hỏi lại — chứ không rơi xuống tra sổ tay.
_DUOI_CAU_CHO_PHEP = re.compile(
    r"^(?:\s*(?:lên|đi|nhé|nha|nhá|với|giùm|hộ|cái|ạ|cho tôi|giúp tôi|cho mình|giúp mình"
    r"|được không|được chứ|được ko|nhỉ|hả|không|ko))*\s*$"
)


#: Ba ý định Routine `doc_y_dinh` trả về mà router chuyển tiếp. `dong_y`/`tu_choi`/
#: `bo_buoc` **cố ý vắng**: chúng chỉ có nghĩa bên trong ngữ cảnh preview, và ngữ cảnh
#: ấy do node giữ, không phải router. Thiếu chỗ ở bảng này = rơi xuống nhánh cũ.
_INTENT_ROUTINE = {
    "chay": "routine_run",
    "xem_truoc": "routine_preview",
    "huy": "routine_cancel",
}

_CONTINUE_READING = re.compile(
    r"\b(?:nghe|đọc|nói|kể)\s+tiếp\b"
    r"|\btiếp\s+(?:đi|nào|nữa)\b"
    r"|\btiếp\s+tục\s+(?:đọc|nghe)\b"
    r"|\bđọc\s+nốt\b"
    r"|\bcòn\s+gì\s+(?:nữa|khác)\b"
)


#: Tập neo dùng chung với `question.py` — KHÔNG chép lại, vì hai bản sao sẽ lệch nhau
#: vào đúng ngày ai đó thêm một từ ở một bên.


def _loc_khong_khong_phai_so(tokens: list[str]) -> list[str]:
    """Bỏ mọi `"không"` **không có từ neo** đứng trước. Giữ lại cái có neo."""
    giu: list[str] = []
    for i, tok in enumerate(tokens):
        if tok != "không" or (i > 0 and tokens[i - 1] in NEO_SO_KHONG):
            giu.append(tok)
    return giu


#: Giàn giáo nghi vấn — từ chỉ **đánh dấu câu hỏi**, không mang nội dung lệnh. Issue #368.
#:
#: Tập **đóng và ngắn**, có chủ ý. Đây không phải một phép chuẩn hoá chung: nới nó ra là
#: mở đường cho một câu hỏi thật bị đọc thành lệnh, mà ranh giới ấy chính là thứ ADR-011
#: dựng lên. Mỗi từ ở đây phải là từ **không bao giờ** là một phần của câu lệnh.
#:
#: `"được"` nằm đây vì nó chen giữa động từ và tân ngữ trong dạng nghi vấn
#: (`"mở **được** cốp không"`), chứ không phải vì nó vô nghĩa ở mọi chỗ.
_GIAN_GIAO_NGHI_VAN: tuple[str, ...] = ("có thể", "giúp tôi", "giúp mình", "có", "được", "bạn", "cậu")

#: Tiểu từ nghi vấn cuối câu. Bóc được **chỉ vì** hàm gọi đã ở trong nhánh `is_question` —
#: ngoài nhánh ấy, `"không"` cuối câu có thể là số 0 hoặc một phủ định (xem `NEO_SO_KHONG`
#: và issue #331).
_TIEU_TU_CUOI: tuple[str, ...] = ("không", "chứ", "nhé", "ạ")


def _boc_gian_giao_nghi_van(text: str) -> str | None:
    """Bỏ giàn giáo nghi vấn để thử khớp luật lại **một lần**. `None` = không đổi gì.

    ## Vì sao cần

    Ba câu dưới đây là **cùng một** câu hỏi, nhưng chỉ câu đầu ra `offer` (đo 29/08):

        "Mở cốp được không"          ->  offer
        "Có mở được cốp không"       ->  manual_question
        "Có thể bật điều hòa không"  ->  manual_question

    Hậu tố `"được không"` đã được dung nạp sẵn, nên chỗ hổng nằm ở **đầu câu và giữa câu**.

    ## Ba chốt

    1. **Chỉ gọi trong nhánh `is_question`.** Đường lệnh thường không đi qua đây, nên một
       câu mệnh lệnh không thể bị bóc mất chữ rồi hiểu khác đi.
    2. **Chỉ gọi khi `_run_matchers` đã trả `None`.** Nó là một lần **thử lại**, không phải
       một phép tiền xử lý — câu đã khớp thì không ai đụng vào.
    3. **Tập từ đóng.** Không phải chuẩn hoá chung: `"Có cần bảo dưỡng định kỳ không"` bóc
       xong thành `"cần bảo dưỡng định kỳ"`, vẫn không khớp luật nào, vẫn đi tra sổ tay.
       Đó là ca âm tính bắt buộc mà #368 nêu, và nó đúng **không nhờ ngoại lệ nào** — nhờ
       việc bóc từ không tạo ra nội dung lệnh mà câu vốn không có.
    """
    tu = text.split()
    if not tu:
        return None
    con = list(tu)
    while con and con[-1].strip(".?!,") in _TIEU_TU_CUOI:
        con.pop()
    ra: list[str] = []
    i = 0
    while i < len(con):
        # Cụm hai từ trước, để `"có thể"` không bị `"có"` ăn mất một nửa.
        hai = " ".join(con[i : i + 2])
        if hai in _GIAN_GIAO_NGHI_VAN:
            i += 2
            continue
        if con[i] in _GIAN_GIAO_NGHI_VAN:
            i += 1
            continue
        ra.append(con[i])
        i += 1
    moi = " ".join(ra).strip()
    return moi if moi and moi != text.strip() else None


class DeterministicControlRouter:
    def __init__(self, poi_fixture: list[dict[str, Any]] | None = None) -> None:
        """`poi_fixture` là **danh sách id được phép dẫn đường tới**, không phải từ điển.

        Hai thứ cố ý tách nhau:

        - **Từ vựng** (alias → id) luôn lấy từ `src/fixtures/poi.json`. Nó là cách người
          ta *gọi tên* địa điểm, không phụ thuộc router này được phép đi đâu.
        - **Danh sách cho phép** (`_poi_ids`) lấy từ tham số. Guard `poi_not_in_fixture`
          tồn tại để bắt đúng ca "câu nói hợp lệ, alias tra ra một id đã bị xoá khỏi
          fixture" — nên nó chỉ có nghĩa khi từ vựng vẫn nhận ra được câu đó.

        Gộp hai thứ làm một thì guard thành vô nghĩa: fixture thiếu id nào thì câu gọi
        id ấy cũng không còn khớp alias, và ta nhận `clarify` thay vì `denied`.
        """
        self._alias_map = poi_alias_map()
        self._poi_ids = {str(item["id"]) for item in (poi_fixture or load_poi_fixture()) if "id" in item}

    def route(self, input_text: str) -> RouteDecision:
        started_ns = time.perf_counter_ns()
        text = normalize_vi(input_text)
        disposition, intent, reason, steps = self._match(input_text, text)
        candidate = CandidateActionPlan(steps=steps) if steps else None
        # Đọc lại tên thô trên đúng nhánh Routine. Hai lần chạy một regex rẻ, trên một
        # nhánh hiếm, đổi lấy việc `_match` giữ nguyên chữ ký 4 phần tử ở ~40 chỗ return —
        # và đổi lấy một router **không có trạng thái nào của riêng nó**.
        ten_tho = ""
        if disposition == "routine":
            y_dinh = doc_y_dinh(text)
            ten_tho = (y_dinh.ten_tho or "") if y_dinh is not None else ""
        return RouteDecision(
            disposition=disposition,
            intent=intent,
            reason=reason,
            route_source="deterministic",
            candidate_plan=candidate,
            routine_ten_tho=ten_tho,
            latency_ms=(time.perf_counter_ns() - started_ns) / 1_000_000,
        )

    def _match(self, raw_text: str, text: str) -> MatchResult:
        """Thứ tự sáu bước dưới đây là nội dung của ADR-011; đừng đảo lại.

        Điểm quan trọng nhất là bước cuối: mặc định của một trợ lý trong xe khi
        nghe câu lạ phải là tra sổ tay, không phải nhún vai. Bước nhận diện câu
        hỏi phải đứng trước hai guard vì `"Cách thay dầu động cơ xăng"` chứa
        `động cơ` — nó là câu hỏi, và câu trả lời đúng là RAG từ chối **có trích
        dẫn** (VF9 chạy điện), khác hẳn từ chối vì trùng chuỗi.
        """
        # **Đứng trước tất cả**, kể cả bước nhận diện câu hỏi: "Còn gì nữa không?" là
        # dạng nghi vấn, mà nghĩa của nó ở đây là *đọc nốt đi* chứ không phải một câu
        # hỏi mới cho sổ tay. Trả lời một lời mời do chính xe phát ra thì phải được
        # hiểu theo lời mời đó.
        #
        # Nhưng **sau** kiểm phủ định — "Đừng đọc tiếp nữa" là lệnh dừng, ngược nghĩa.
        if _CONTINUE_READING.search(text) and not is_negated(text):
            return "not_control", "manual_continue", "continue_reading", ()

        # Routine đứng đây — sau "đọc tiếp", trước mọi thứ còn lại (#274, #299).
        #
        # Phải trước `is_information_question`: `"Routine Về nhà gồm những gì"` chứa chữ
        # "gì" nên nhánh câu hỏi bắt được nó và đưa đi tra sổ tay. Đó đúng là thứ đo được
        # trên develop @ d088b49 — sáu câu Routine, sáu lần "không tìm thấy trong sổ tay".
        #
        # Đặt trước KHÔNG làm rộng cửa: `doc_y_dinh` đòi động từ + từ chỉ loại (`routine`/
        # `kịch bản`), còn `_HUY` neo đầu câu và đòi từ thứ hai. Một câu hỏi sổ tay bình
        # thường vẫn trả `None` và rơi xuống nhánh cũ nguyên vẹn.
        #
        # Router **không** phân giải tên: danh sách Routine của user là trạng thái, và
        # ADR-006/010 cấm router đọc trạng thái. Nó chỉ nói "đây là ý định Routine, tên
        # thô là X"; phân giải là việc của `routine_node`.
        if (y_dinh := doc_y_dinh(text)) is not None:
            intent = _INTENT_ROUTINE.get(y_dinh.loai)
            if intent is not None:
                return "routine", intent, "routine_intent", ()

        # Áp suất lốp đứng **trước** `is_information_question`, vì "áp suất lốp bao
        # nhiêu?" đúng là một câu hỏi thông tin — nhưng thông tin ấy **không có trong
        # sổ tay**. Sổ tay chỉ sang cái nhãn ở khung cửa; con số thật nằm ở bảng curate
        # và phụ thuộc cấu hình xe. Để nó rơi vào `manual_query` thì tài xế nghe đúng
        # câu breadcrumb đã gặp ngày 17/08.
        #
        # Router vẫn **không đọc trạng thái**: nó chỉ nói "đây là câu hỏi áp suất lốp,
        # trục nào". Việc tra cấu hình xe nằm ở compose, nơi có `vehicle_id`.
        if (truc := _truc_ap_suat_lop(text)) is not None:
            return "not_control", "tire_pressure_query", f"tire_pressure_{truc}", ()

        # Hỏi xin giải thích thì luôn tra sổ tay, kể cả khi câu chứa từ khoá điều
        # khiển. `"Chỉnh nhiệt độ thế nào?"` hỏi *cách làm*; đáp lại bằng
        # "bạn muốn chỉnh bao nhiêu độ?" là trả lời sai câu hỏi.
        # SP-2: CHỈ KHI câu có từ vựng về xe — "Cậu tên gì thế?" cũng có "gì" nhưng
        # không hỏi về xe; để nó rơi xuống classifier. Xem `co_tu_vung_xe`.
        if is_information_question(text) and co_tu_vung_xe(text):
            return "not_control", "manual_query", "manual_question", ()

        if is_question(raw_text, text):
            # Dạng nghi vấn có/không: hỏi *có làm được không*. Câu hỏi không bao giờ
            # thực thi, nên nếu nội dung khớp một luật điều khiển thì nêu ra thành
            # lời đề nghị; người dùng quyết ở lượt sau.
            matched = self._run_matchers(text)
            if matched is None and (thu_lai := _boc_gian_giao_nghi_van(text)) is not None:
                # Thử LẠI một lần với giàn giáo nghi vấn đã bóc — xem
                # `_boc_gian_giao_nghi_van`. Một lần, và chỉ ở đây.
                matched = self._run_matchers(thu_lai)
            if matched is None:
                if co_tu_vung_xe(text):
                    return "not_control", "manual_query", "manual_question", ()
                # Câu hỏi không về xe: không phải việc của sổ tay, để classifier quyết
                # (rơi tiếp xuống mặc định ở cuối hàm).
            else:
                disposition, intent, _reason, steps = matched
                if disposition == "control":
                    return "offer", intent, "question_about_supported_action", steps
                if disposition == "clarify":
                    # Một câu HỎI không bao giờ được đẻ ra một câu hỏi lại về slot.
                    #
                    # `"có thể chỉnh độ ngả ghế không"` ra `clarify missing_seat_side` —
                    # xe hỏi ngược "ghế nào?" trong khi người ta đang hỏi *làm được
                    # không*, chưa yêu cầu làm gì. Còn `"có thể chỉnh độ cao ghế không"`
                    # ra `manual_query` **đúng một cách tình cờ**: `độ cao ghế` không
                    # khớp trục nào nên rơi xuống mặc định, chứ không phải vì có luật
                    # nào phân biệt hai câu. Hai câu cùng dạng, hai số phận.
                    #
                    # `denied` KHÔNG đi đường này: hỏi về một việc bị cấm thì vẫn phải
                    # được nói là bị cấm (`"tắt đèn pha được không"` → ADR-020), và
                    # `offer` cũng không: câu hỏi khớp trọn một luật thì nêu việc sẽ làm
                    # rồi hỏi lại, đó là ADR-011.
                    return "not_control", "manual_query", "manual_question", ()
                # Ngoài khoảng thì từ chối. Không đề nghị một việc không hợp lệ chỉ vì
                # nó được hỏi bằng dạng nghi vấn.
                return matched

        # Phủ định chỉ chặn khi câu thực sự nhắm vào một actuator hoặc là mệnh lệnh.
        # Bỏ điều kiện này thì `"Tôi không muốn ăn cơm"` cũng bị `denied` thay vì
        # rơi xuống mặc định — đúng cái lỗi ADR-011 đang sửa, chỉ đổi chỗ.
        # Và phủ định TẢ TRIỆU CHỨNG thì không phải mệnh lệnh: "Đèn cứ sáng hoài
        # không tắt" tả cái đèn, "Không tắt đèn" mới là lệnh — xem helper.
        if (
            is_negated(text)
            and not _phu_dinh_ta_trieu_chung(text)
            and (self._looks_imperative(text) or any(t in text for t in _ACTUATOR_TOKENS))
        ):
            return "denied", "none", "negated_command", ()
        if text in _AMBIGUOUS_TEXTS:
            return "clarify", "none", "ambiguous_reference", ()

        # Tự sửa lời phải xét **trước** matcher chính: matcher đọc cả câu và sẽ khớp
        # vế TRÁI — tức là đúng cái vừa bị rút lại.
        if (sua_loi := self._tach_tu_sua_loi(text)) is not None:
            return sua_loi

        matched = self._run_matchers(text)
        if matched is not None:
            return matched

        # Vế dẫn nhập ("nóng quá...", "vivi ơi...") — thử lại sau khi bóc nó ra.
        #
        # Vị trí này là một phần của hàng rào, không phải tiện tay: mọi nhánh câu hỏi
        # ở trên đã `return` xong từ lâu, nên `_bo_ve_dan_nhap` không bao giờ nhìn thấy
        # một câu hỏi. Chuyển nó lên trên `is_question` là biến "Làm sao để bật điều
        # hòa?" thành lệnh bật điều hòa.
        if (con_lai := self._bo_ve_dan_nhap(text)) is not None:
            sau_khi_boc = self._run_matchers(con_lai)
            if sau_khi_boc is not None:
                return sau_khi_boc

        if self._looks_imperative(text) and any(token in text for token in _UNSUPPORTED_TOKENS):
            return "denied", "none", "unsupported_actuator", ()
        return "not_control", "manual_query", "default_to_manual", ()

    def _run_matchers(self, text: str) -> MatchResult | None:
        """Tách câu thành từng vế, khớp **từng vế một**, rồi gộp steps lại (issue #223).

        Trước thay đổi này cả câu nói được đối xử như **một** lệnh: động từ đọc ở đầu
        câu, số đọc trên toàn chuỗi, và `_match_one_clause` thoát ngay khi matcher đầu
        tiên khớp. Ba hậu quả đo được trên máy dev 21/08:

        - `"mở cốp xe và đóng tất cả các cửa"` → **mở** cả bốn cửa. Động từ của vế 1
          áp lên đối tượng của vế 2, tức xe làm đúng điều ngược lại.
        - `"bật điều hòa 22 độ, quạt gió mức 2 và phát nhạc"` → `fan_level_out_of_range`
          dù mức 2 hợp lệ: `_number` nhặt 22 của vế nhiệt độ rồi đo theo dải quạt.
        - Chéo domain **0/78** kịch bản trong `docs/kich_ban_test_ghep_lenh.xlsx` sinh
          được bước ở hai domain — bất khả thi về cấu trúc, không phải thiếu luật.

        Một vế = một câu đơn, và `_match_one_clause` vốn đã đúng cho câu đơn. Nên bản
        sửa không viết lại matcher nào; nó chỉ thôi đưa cả câu ghép vào cửa dành cho
        câu đơn.

        **Chỉ tách theo liên từ, cố ý.** `_COMMAND_VERBS` chứa `ngả`, `tiếp`, `dừng`,
        `kéo`, `nâng` — những từ nằm **giữa** một lệnh đơn hợp lệ. Cắt tại động từ giữa
        câu sẽ xé `"đặt ghế lái ngả lưng 60 phần trăm"` thành `"đặt ghế lái"` +
        `"ngả lưng 60 phần trăm"` và làm hỏng một câu đang chạy tốt. Ca ghép **không**
        liên từ (`"bật điều hòa mở nhạc"`) vì thế vẫn còn hở — trong HVAC thì
        `_split_fan_and_rest` đã lo, chéo domain thì chưa. Xem "Còn hở" ở `_segment_clauses`.
        """
        clauses = self._segment_clauses(text)
        if len(clauses) == 1:
            # Câu đơn đi đúng đường cũ, không qua bước gộp nào — giữ cho thay đổi này
            # không chạm được vào phần lớn bộ test hiện có.
            return self._match_one_clause(text)
        if len(clauses) > _MAX_CLAUSES:
            # Trần tồn tại để một câu dài (hoặc một bản chép STT trôi) không đẻ ra kế
            # hoạch chục bước mà tài xế không kiểm nổi trong một hộp thoại duyệt.
            return "clarify", "none", "too_many_clauses", ()

        whole = self._match_one_clause(text)
        ket = self._gop_ve_cung_domain([(clause, self._match_one_clause(clause)) for clause in clauses])
        merged = self._merge_clause_matches(ket)
        return merged if self._merging_gained_something(whole, merged) else whole

    @staticmethod
    def _merging_gained_something(whole: MatchResult | None, merged: MatchResult | None) -> bool:
        """Hai đường ra **cùng một tập việc** thì giữ đường cả-câu. Khác thì lấy đường gộp.

        Đây không phải phép chọn cho chắc ăn: hai đường biết hai thứ khác nhau.

        Đường cả-câu là **chuyên gia trong một domain**. `_match_hvac_compound` biết
        rằng đặt nhiệt độ và đặt mức quạt đều phải **chờ máy chạy**, nên nó gắn
        `depends_on=("step-1",)` cho cả hai. Cắt câu rồi khớp từng vế thì mỗi vế là một
        câu đơn độc lập và tri thức thứ tự ấy biến mất — `"bật điều hòa 22 độ và quạt
        gió mức 2"` vẫn ra đủ ba bước, nhưng bước quạt hết phụ thuộc bước bật máy, và
        bật máy hỏng thì quạt vẫn chạy. Bộ test hiện có bắt đúng ca này.

        Đường gộp là **người tổng quát**: nó thấy được các vế mà matcher đầu tiên đã
        nuốt mất, và đó là toàn bộ lý do issue #223 tồn tại.

        So bằng **tập (tool, args)** chứ không bằng số bước hay số domain: nó trả lời
        đúng câu hỏi cần hỏi — *hai đường có bất đồng về việc phải làm không?* Không bất
        đồng thì chuyên gia thắng, vì nó biết thêm thứ tự. Bất đồng thì người tổng quát
        thắng, vì phần chênh chính là ý mà đường kia bỏ rơi.
        """

        def workload(result: MatchResult | None) -> list[tuple[str, tuple[tuple[str, Any], ...]]] | None:
            if result is None or result[0] != "control":
                return None
            return sorted((step.tool, tuple(sorted(step.args.items()))) for step in result[3])

        if merged is None:
            # Không vế nào khớp matcher nào. Đường cả-câu có thể vẫn khớp — cụm đích
            # nằm vắt qua liên từ chẳng hạn — nên lùi về nó thay vì vứt cả lượt.
            return False
        merged_work = workload(merged)
        if merged_work is None:
            # Đường gộp dừng ở `clarify`/`denied` vì một vế cụ thể hỏng. Đó là thông tin
            # thật về câu người dùng vừa nói, chính xác hơn hẳn một kế hoạch dựng từ
            # nửa câu — `_merge_clause_matches` trả nguyên vẹn lý do của vế ấy.
            return True
        return workload(whole) != merged_work

    def _match_one_clause(self, text: str) -> MatchResult | None:
        """Chạy các matcher lệnh theo thứ tự; matcher đầu tiên khớp thì thắng.

        Cả đường lệnh lẫn đường `offer` đều đi qua đây, nên chốt chặn số mơ hồ đặt
        ở đây là đủ một chỗ.

        `_match_trunk` phải đứng **sau** `_match_door`: "mở cốp" không chứa `cửa`
        nên không đụng nhau, nhưng giữ thứ tự này để lệnh cửa luôn được xét trước
        khi thêm cách nói mới cho cốp.
        """
        for matcher in (
            self._match_hvac,
            # `_match_open_app` phải đứng **trước** `_match_music`: "bật nhạc trên
            # Spotify" chứa `nhạc` nên `_match_music` sẽ nuốt nó và bấm play trên hệ
            # thống nhạc của xe, trong khi người nói đã gọi đích danh một app.
            self._match_open_app,
            self._match_music,
            self._match_window,
            self._match_seat,
            self._match_door,
            self._match_trunk,
            self._match_lights,
            self._match_tim_poi,
            self._match_navigation,
        ):
            result = matcher(text)
            if result is not None:
                return self._reject_relative_change(text, self._reject_ambiguous_number(text, result))
        return None

    def _segment_clauses(self, text: str) -> list[str]:
        """Cắt câu tại liên từ, rồi cho vế trần **thừa hưởng** động từ của vế trước.

        Luật kế thừa là phần quan trọng nhất, và nó cắt theo cả hai chiều:

        - `"bật điều hòa 22 độ và quạt gió mức 2"` — vế 2 không có động từ nên mượn
          `bật`. Thiếu luật này thì `_match_hvac` từ chối vế 2 (nó đòi câu mở đầu bằng
          động từ) và ta mất đúng cái ý vừa tách ra được.
        - `"mở cốp xe và đóng tất cả các cửa"` — vế 2 **có** động từ riêng nên **không**
          mượn. Đây là chỗ sửa lỗi làm-ngược-lệnh: trước đây `đóng` bị `mở` đè mất.

        Vế nào chưa có động từ nào **đứng trước** để mượn thì để trần. Nó gần như chắc
        chắn không khớp matcher nào, và như thế là đúng: `"gọi cho vợ tôi và phát nhạc"`
        vẫn phát được nhạc, còn `"điều hòa 24 độ và quạt gió mức 3"` vẫn rơi xuống sổ
        tay y như trước (cả hai vế đều thiếu động từ — đó là một issue riêng).

        ## Còn hở

        Ca ghép **không** liên từ. `normalize_vi` xoá dấu phẩy và STT không sinh dấu
        câu, nên `"bật điều hòa, mở nhạc"` tới đây là `"bật điều hòa mở nhạc"` — một
        câu hai ý, không ký tự nào ngăn giữa. Trong HVAC `_split_fan_and_rest` đã bịt
        được bằng tín hiệu domain; chéo domain thì chưa, và cắt bừa theo động từ giữa
        câu là phá `"đặt ghế lái ngả lưng 60 phần trăm"` (xem `_run_matchers`). Cần một
        chốt "cả hai nửa đều tự khớp" trước khi mở luật đó — để PR sau.
        """
        parts = [part.strip() for part in _CONJUNCTION_PATTERN.split(text)]
        parts = [part for part in parts if part] or [text]
        # Vế hồi chỉ (`"… rồi dẫn đường tới đó"`) KHÔNG phải một việc riêng: đại từ
        # trỏ về vế trước. Giữ nó lại thì nó tự khớp `_match_navigation`, không tra
        # được đích, trả `clarify` — và theo luật ở `_merging_gained_something`, một
        # vế hỏng thắng cả câu, nên cả lượt chết. Bỏ nó đi thì còn một vế, đường
        # cả-câu chạy và `_match_tim_poi` xử trọn (spec SP-5 §2.3).
        # Chỉ bỏ khi CÓ vế đứng trước để trỏ về; `"dẫn đường tới đó"` đứng một mình
        # vẫn đi đường cũ và vẫn hỏi lại.
        if len(parts) > 1:
            giu = [parts[0]] + [p for p in parts[1:] if not _VE_HOI_CHI.match(p)]
            parts = giu

        clauses: list[str] = []
        inherited: str | None = None
        for part in parts:
            verb = self._leading_verb(part)
            if verb is None:
                if inherited is not None:
                    part = f"{inherited} {part}"
            else:
                inherited = verb
            clauses.extend(self._split_at_inner_verbs(part))
        return clauses if len(clauses) > 1 else [text]

    def _bo_ve_dan_nhap(self, text: str) -> str | None:
        """Bỏ vế dẫn nhập ở đầu câu, hoặc `None` nếu không bỏ được gì.

        *"Nóng quá bật điều hòa giúp mình"*, *"ờ bật nhạc đi"*, *"vivi ơi bật nhạc"*,
        *"ê vivi dẫn tui tới bình minh"* — tất cả đều `not_control` trước PR này.
        `_split_at_inner_verbs` không cắt được chúng vì nó đòi **cả hai** nửa tự khớp
        một `control`, mà `"nóng quá"` thì không khớp gì cả.

        Bằng chứng đây là một lỗ chứ không phải thiết kế: *"lạnh rồi tắt điều hòa giúp
        mình"* **chạy đúng** — nhưng chỉ vì `rồi` tình cờ nằm trong `_CONJUNCTIONS`.
        Cùng lớp câu, hai số phận.

        ## Ba điều kiện, và cả ba đều là hàng rào của ADR-011

        1. **Phần còn lại phải tự khớp `control`.** Không phải `clarify`, không phải
           `denied`. Đây là điều kiện quan trọng nhất: một câu hỏi tra cứu không bao
           giờ để lại một lệnh hoàn chỉnh ở đuôi sau khi bóc vài từ đầu.
        2. **Câu hỏi thì không bóc.** *"Làm sao để bật điều hòa?"* có đuôi khớp
           `control`, và bóc nó đi là biến một câu hỏi sổ tay thành một lệnh — đúng
           thứ `question_reaches_RAG` đo. Điều kiện 1 một mình **không** đủ chặn ca này.
        3. **Tiền tố phải là vế dẫn nhập thật**, không phải "vài từ bất kỳ": hoặc nằm
           trong `GOI_VA_AM_U`, hoặc là một cảm thán trạng thái kết thúc bằng `quá`
           (*"nóng quá"*, *"im quá"*, *"trong xe nóng quá"*). Cho bóc tiền tố tuỳ ý là
           mở đường cho *"hướng dẫn tôi bật điều hòa"* thành một lệnh bật điều hòa.
        """
        tokens = text.split()
        for so_tu in range(1, min(MAX_TU_TIEN_TO, len(tokens) - 1) + 1):
            tien_to = " ".join(tokens[:so_tu])
            if not (tien_to in GOI_VA_AM_U or tokens[so_tu - 1] == "quá"):
                continue
            con_lai = " ".join(tokens[so_tu:])
            ket_qua = self._match_one_clause(con_lai)
            if ket_qua is not None and ket_qua[0] == "control":
                return con_lai
        return None

    def _tach_tu_sua_loi(self, text: str) -> MatchResult | None:
        """Người nói rút lại vế trước rồi nói lại — thực thi vế **phải**, không phải vế trái.

        Đo được trước thay đổi này (cả ba đều thực thi đúng cái vừa bị rút lại):

        ```
        "bật nhạc không tắt đi"              → media play        (vế BỊ HUỶ)
        "bật điều hòa à thôi"                → set_hvac_power on (vế BỊ HUỶ)
        "đặt âm lượng 70 không 40 phần trăm" → set_volume 70     (số CŨ)
        ```

        ## Chữ `không` và luật neo

        Đây là nghĩa **thứ tư** của `không` trong router. Ba nghĩa trước: phủ định
        (`is_negated`), tiểu từ nghi vấn (`is_question`), và **số 0** — cái cuối chỉ
        đúng khi có từ neo đứng ngay trước (`NEO_SO_KHONG`, dựng ở PR #268).

        Luật ấy được **dùng lại nguyên vẹn** ở đây chứ không chép ra bản thứ hai:
        `"đặt âm lượng về không"` có neo `về` nên là lệnh đặt volume 0, không phải một
        câu rút lại. Bỏ điều kiện neo là biến mọi lệnh "về không" thành câu sửa lời.

        ## Vế phải thừa hưởng đích của vế trái

        Vế phải hiếm khi là một câu hoàn chỉnh. Ba đường, thử theo thứ tự:

        1. **Tự khớp** — `"tắt điều hòa"` sau `"bật nhạc à thôi"`.
        2. **Thiếu đối tượng** — `"tắt đi"` có động từ nhưng không biết tắt cái gì; mượn
           phần đối tượng của vế trái (`"bật nhạc"` → `nhạc`) thành `"tắt nhạc"`.
        3. **Thiếu cả động từ** — `"40 phần trăm"` chỉ là một con số; mượn cả cụm
           động-từ-và-đối-tượng của vế trái sau khi **bỏ số cũ đi** (`"đặt âm lượng 70"`
           → `"đặt âm lượng"`) thành `"đặt âm lượng 40 phần trăm"`.

        Bỏ số cũ ở đường 3 là bắt buộc: giữ lại thì `_number` gặp hai số trong một câu
        và nhặt cái đầu — tức là đúng con số vừa bị rút lại.

        ## Ứng viên phải **khác** vế trái mới được tính

        `"bật điều hòa à thôi cái kia"`: đường 3 dựng ra `"bật điều hòa cái kia"`, khớp
        `set_hvac_power on` — tức đúng vế vừa bị rút lại, chỉ đi vòng qua nhánh "sửa
        lời" để tới. Nên một ứng viên chỉ được nhận khi kết quả của nó **khác** kết quả
        của vế trái; giống hệt nghĩa là vế phải không đóng góp gì.

        ## Fail-closed, và vì sao nó không thể là `return None`

        Điều kiện approve #2 của review #315. Bản đầu trả `None` khi không ứng viên nào
        dựng được thành lệnh, và `None` ở đây **không** trung tính: `_match` đi tiếp
        xuống `_run_matchers(text)`, khớp **cả câu**, và cả câu bắt đầu bằng đúng vế
        vừa bị rút lại. Tức là đường thoát của nhánh an toàn dẫn thẳng về hành vi mà
        nhánh ấy sinh ra để chặn.

        Nhưng fail-closed chỉ áp cho dấu **không mơ hồ** (`DAU_SUA_LOI_RO`), và đó là
        điều kiện approve #1. Với `"không"` trần thì việc "không dựng được vế phải" là
        bằng chứng mạnh nhất rằng đây **không** phải câu sửa lời: `"bật nhạc không nghe
        rõ"`, `"bật điều hòa không cần mạnh"` là câu bình thường, và chúng phải đi tiếp
        đúng đường cũ chứ không bị hỏi lại. Nên `"không"` trả `None` như trước, còn
        `"à thôi"`/`"à quên"`/`"nhầm rồi"` trả `clarify` với **0 bước**.

        Điều kiện (a) vế trái tự nó là một lệnh vẫn bắt buộc cho cả hai: thiếu nó thì
        `"tôi không biết bật điều hòa kiểu gì"` — một câu hỏi sổ tay — bị bắt thành câu
        hỏi lại thay vì đi tra sổ tay, đúng thứ ADR-011 đo.
        """
        tokens = text.split()
        # `True` khi đã gặp một dấu rút lại **có thật** (vế trái tự khớp một lệnh) mà
        # chưa dựng nổi vế phải. Xem mục fail-closed ở docstring.
        rut_lai_that = False
        # Duyệt từ PHẢI sang: câu có thể sửa lời nhiều lần, và lần cuối mới là ý thật.
        for i in range(len(tokens) - 1, 0, -1):
            dau = next(
                (d for d in _DAU_SUA_LOI_DAI_TRUOC if tokens[i : i + len(d.split())] == d.split()),
                None,
            )
            if dau is None:
                continue
            if dau == "không" and tokens[i - 1] in NEO_SO_KHONG:
                # Có neo → đây là số 0, không phải dấu rút lại. Luật của PR #268.
                continue
            trai = " ".join(tokens[:i])
            phai = " ".join(tokens[i + len(dau.split()) :])
            if not trai:
                continue
            if not phai:
                # "bật điều hòa à thôi" — rút lại mà không nói lại gì. KHÔNG làm gì, và
                # nói ra là mình không làm gì: để nó rơi xuống sổ tay thì tài xế nhận
                # một đoạn hướng dẫn cho một việc họ vừa huỷ.
                if self._match_one_clause(trai) is None:
                    return None
                return "clarify", "none", "tu_sua_loi_khong_con_lenh", ()
            trai_khop = self._match_one_clause(trai)
            for ung_vien in self._ung_vien_ve_phai(trai, phai):
                ket_qua = self._match_one_clause(ung_vien)
                if ket_qua is None or ket_qua[0] not in {"control", "denied"}:
                    continue
                # Giống hệt vế trái = vế phải không đóng góp gì. Xem docstring.
                if ket_qua == trai_khop:
                    continue
                return ket_qua
            # Không ứng viên nào dựng được. Chỉ tính là "đã rút lại" khi dấu là loại
            # không mơ hồ **và** vế trái tự nó là một lệnh — hai điều kiện ấy là thứ
            # phân biệt câu tự sửa lời với câu bình thường có chữ `không` ở giữa.
            if dau in DAU_SUA_LOI_RO and trai_khop is not None and trai_khop[0] in {"control", "denied"}:
                rut_lai_that = True
        if rut_lai_that:
            # Fail-closed: KHÔNG `return None`. Xem docstring — `None` ở đây rơi về
            # `_run_matchers(text)`, và cả câu mở đầu bằng chính vế vừa bị rút lại.
            return "clarify", "none", "tu_sua_loi_khong_doc_duoc", ()
        return None

    def _ung_vien_ve_phai(self, trai: str, phai: str) -> tuple[str, ...]:
        """Ba cách đọc vế phải, từ ít giả định nhất tới nhiều nhất. Xem `_tach_tu_sua_loi`."""
        ung_vien = [phai]
        dong_tu_trai = self._leading_verb(trai)
        if dong_tu_trai is not None:
            doi_tuong = trai[len(dong_tu_trai) :].strip()
            doi_tuong_khong_so = _NUMBER_PATTERN.sub("", doi_tuong).replace("phần trăm", "").strip()
            if self._leading_verb(phai) is not None and doi_tuong_khong_so:
                # Vế phải có động từ riêng, chỉ thiếu đối tượng.
                ung_vien.append(f"{phai} {doi_tuong_khong_so}")
            trai_khong_so = _NUMBER_PATTERN.sub("", trai).replace("phần trăm", "")
            ung_vien.append(f"{' '.join(trai_khong_so.split())} {phai}")
        return tuple(dict.fromkeys(u for u in ung_vien if u.strip()))

    def _split_at_inner_verbs(self, clause: str) -> list[str]:
        """Cắt tại động từ lệnh **giữa** vế — chỉ khi CẢ HAI nửa tự khớp một lệnh.

        Đây là ca ghép **không liên từ**, và nó là ca **thường** chứ không phải ngoại
        lệ: `normalize_vi` xoá mọi dấu câu, còn STT thì không sinh dấu câu bao giờ. Nên
        `"tắt điều hòa, tắt quạt gió"` — gõ vào lẫn nói ra — đều tới đây dưới dạng
        `"tắt điều hòa tắt quạt gió"`: một câu hai ý, không một ký tự nào ngăn giữa.

        Chốt "cả hai nửa đều tự khớp" là thứ giữ cho việc cắt không phá câu đơn. Nó cần
        thiết vì `_COMMAND_VERBS` chứa những từ nằm **giữa** một lệnh đơn hợp lệ —
        `tiếp` trong `"bài kế tiếp"`, `ngả` trong `"đặt ghế lái ngả lưng 60 phần trăm"`.
        Cắt mù theo động từ sẽ xé đúng những câu ấy.

        Đo trên 359 câu đơn của bộ test và bảng kịch bản (21/08):

        - **cắt 11 câu**, đều là hai lệnh thật: `"tắt điều hòa, tắt quạt gió"`,
          `"bật điều hòa mở nhạc"`, `"mở một cửa, đóng cửa kia"`, và cả nhóm "liên từ
          lạ" mà `_CONJUNCTIONS` không có (`xong`, `sau đó`, `luôn tiện`, dấu `;`);
        - **tha 122 câu** đang chạy đúng, gồm đúng những câu nguy hiểm kể trên và
          `"bật quạt gió mức 2 điều hòa"` — ca issue #65, một lệnh quạt duy nhất.

        Cắt xong thì **đệ quy sang nửa phải**: `"bật điều hòa phát nhạc bật đèn trần"`
        là ba ý, và dừng ở hai thì vẫn còn nuốt một.
        """
        tokens = clause.split()
        for index in range(1, len(tokens)):
            verb = next(
                (v for v in _COMMAND_VERBS_DAI_TRUOC if tokens[index : index + len(v.split())] == v.split()),
                None,
            )
            if verb is None:
                continue
            trai, phai = " ".join(tokens[:index]), " ".join(tokens[index:])
            ket_trai, ket_phai = self._match_one_clause(trai), self._match_one_clause(phai)
            if ket_trai is not None and ket_trai[0] == "control" and ket_phai is not None and ket_phai[0] == "control":
                return [trai, *self._split_at_inner_verbs(phai)]
        return [clause]

    @staticmethod
    def _leading_verb(text: str) -> str | None:
        """Động từ lệnh mở đầu, hoặc `None`. Khớp dài trước ngắn.

        `tạm dừng` phải thắng `dừng`, nếu không `"tạm dừng nhạc"` bị đọc thành một vế
        `dừng` và mất chữ `tạm` — hai lệnh khác nhau ở `_match_music`.
        """
        command = _POLITE_PREFIX_PATTERN.sub("", text, count=1)
        for verb in _COMMAND_VERBS_DAI_TRUOC:
            if command == verb or command.startswith(f"{verb} "):
                return verb
        return None

    def _gop_ve_cung_domain(
        self, matches: list[tuple[str, MatchResult | None]]
    ) -> list[tuple[str, MatchResult | None]]:
        """Nối lại các vế **liền nhau cùng một domain** rồi khớp một lần, để giữ `depends_on`.

        Đây là chỗ bịt lỗ mà @thanhpro82 chặn merge #225 vì nó (PM/PO review 21/08):
        *"thêm domain music không được làm rơi phụ thuộc vào bước bật điều hòa."*

        `"bật điều hòa 22 độ và quạt gió mức 2 và mở nhạc và bật đèn trần"` tách thành bốn
        vế, và hai vế HVAC đầu bị khớp **độc lập**: vế 2 (`"bật quạt gió mức 2"`) đứng một
        mình là một lệnh quạt hoàn chỉnh, không có lý do gì phải chờ ai. Nên
        `set_hvac_fan_level.depends_on` ra `()` thay vì `("step-1",)`, và nếu bật máy hỏng
        thì đặt mức quạt vẫn chạy.

        Ca hai vế (`"... 22 độ và quạt gió mức 2"`) **không** lộ lỗi này, vì đường cả-câu
        cho đúng cùng một tập việc nên `_merging_gained_something` chọn nó và mang theo
        `depends_on`. Thêm một vế domain khác vào là đường cả-câu hết khớp, và cái lưới ấy
        rách. Đó là lý do lỗi chỉ hiện ra ở câu bốn ý.

        Cách bịt: các vế liền nhau cùng domain được **nối lại và khớp một lần**, tức trả
        chúng về đúng cho chuyên gia trong domain đó (`_match_hvac_compound`) — nơi duy nhất
        biết rằng đặt nhiệt độ và đặt mức quạt đều phải chờ máy chạy.

        Chốt an toàn: chỉ nhận bản nối nếu nó **không đánh rơi việc nào** so với khớp rời.
        Nối chuỗi rồi khớp lại là một phép biến đổi có thể ra ít hơn, và im lặng mất một ý
        đúng là thứ cả issue #223 sinh ra để chặn.
        """
        gop: list[tuple[str, MatchResult | None]] = []
        i = 0
        while i < len(matches):
            dom = self._domain_cua(matches[i][1])
            j = i + 1
            while dom is not None and j < len(matches) and self._domain_cua(matches[j][1]) == dom:
                j += 1
            if j - i < 2:
                gop.append(matches[i])
                i += 1
                continue
            noi = _CONJUNCTION_JOIN.join(clause for clause, _ in matches[i:j])
            lai = self._match_one_clause(noi)
            roi = {
                (step.tool, tuple(sorted(step.args.items())))
                for _clause, ket in matches[i:j]
                if ket is not None
                for step in ket[3]
            }
            if (
                lai is not None
                and lai[0] == "control"
                and roi <= {(step.tool, tuple(sorted(step.args.items()))) for step in lai[3]}
            ):
                gop.append((noi, lai))
            else:
                gop.extend(matches[i:j])
            i = j
        return gop

    @staticmethod
    def _domain_cua(matched: MatchResult | None) -> str | None:
        """Domain **duy nhất** của một kết quả `control`, hoặc `None`.

        `None` cho mọi thứ khác — kể cả plan chạm nhiều domain, và cả tool S0/IVI không có
        domain (`open_app`). Không có domain rõ ràng thì không nối, vì phép nối chỉ an toàn
        khi ta biết chắc mình đang trả việc về cho đúng một chuyên gia.
        """
        if matched is None or matched[0] != "control":
            return None
        doms = {spec.domain for spec in (TOOL_REGISTRY.get(step.tool) for step in matched[3]) if spec is not None}
        doms.discard(None)
        return next(iter(doms)) if len(doms) == 1 else None

    def _merge_clause_matches(self, matches: list[tuple[str, MatchResult | None]]) -> MatchResult | None:
        """Gộp kết quả từng vế thành **một** kế hoạch.

        Ba luật, theo thứ tự:

        1. **Một vế hỏng thì cả lượt dừng.** `clarify`/`denied`/`not_control` ở bất kỳ
           vế nào được trả nguyên vẹn. Chạy nửa lệnh rồi im lặng về nửa kia là đúng thứ
           `agent_spec.md` gọi là "tuân thủ một phần trong im lặng". Chạy vế hợp lệ
           **và nói ra** vế bị từ chối thì tốt hơn, nhưng `RouteDecision` hiện không có
           chỗ biểu diễn kết quả một phần (`contracts.py:147` bắt loại trừ) — đó là
           BUG-06, một issue riêng.
        2. **Vế không khớp matcher nào bị bỏ qua**, không làm hỏng lượt. `"phát nhạc và
           gọi cho vợ tôi"` vẫn phát nhạc — y như hôm nay, chỉ khác là nay vế nhạc
           không còn phải là vế đầu tiên mới được chạy.
        3. **Trùng và mâu thuẫn** xử lý ở `_merge_steps`.
        """
        controls: list[tuple[Intent, tuple[CandidateStep, ...]]] = []
        for _clause, result in matches:
            if result is None:
                continue
            disposition, intent, reason, steps = result
            if disposition != "control":
                return result
            controls.append((intent, steps))

        if not controls:
            return None
        if len(controls) == 1:
            intent, steps = controls[0]
            return "control", intent, "deterministic_rule", steps
        return self._merge_steps(controls)

    @staticmethod
    def _merge_steps(controls: list[tuple[Intent, tuple[CandidateStep, ...]]]) -> MatchResult:
        """Đánh số lại, ánh xạ `depends_on`, và chặn hai vế cùng nhắm một đích.

        `_target_key` gom theo **đích thao tác**, không theo giá trị: hai vế chỉnh hai
        cửa sổ khác nhau là hai việc, còn hai vế chỉnh **cùng** một cửa sổ về hai mức
        là một câu mâu thuẫn.

        - Trùng y hệt → giữ một. `"bật điều hòa và bật điều hòa"` là một ý nói hai lần.
        - Cùng đích, khác giá trị → `clarify`. Chạy cả hai là **thực thi actuator hai
          lần** cho một đích, thứ mà `CLAUDE.md` liệt là hard gate của eval; chọn bừa
          giá trị đầu thì im lặng bỏ ý sau. Hỏi lại là đường duy nhất còn lại.
        """
        merged: list[CandidateStep] = []
        seen: dict[tuple[str, tuple[tuple[str, Any], ...]], dict[str, Any]] = {}
        for _intent, steps in controls:
            remap: dict[str, str] = {}
            for step in steps:
                key = DeterministicControlRouter._target_key(step)
                previous = seen.get(key)
                if previous is not None:
                    if previous == step.args:
                        continue
                    return "clarify", _intent, "conflicting_duplicate", ()
                seen[key] = step.args
                new_id = f"step-{len(merged) + 1}"
                remap[step.step_id] = new_id
                merged.append(
                    step.model_copy(
                        update={
                            "step_id": new_id,
                            "ordinal": len(merged),
                            # Chỉ ánh xạ trong phạm vi vế của chính nó. `depends_on`
                            # không bao giờ trỏ sang vế khác — hai vế là hai ý độc lập,
                            # nên buộc chúng phụ thuộc nhau sẽ khiến một vế hỏng kéo
                            # vế kia thành `skipped_due_to_prior_failure` vô cớ.
                            "depends_on": tuple(remap[dep] for dep in step.depends_on if dep in remap),
                        }
                    )
                )
        # Intent của lượt ghép lấy theo vế **đầu tiên**: nó là trường một-giá-trị dùng
        # cho log/metrics, không phải hợp đồng thực thi (`steps` mới là hợp đồng).
        return "control", controls[0][0], "deterministic_rule", tuple(merged)

    @staticmethod
    def _target_key(step: CandidateStep) -> tuple[str, tuple[tuple[str, Any], ...]]:
        """Khoá định danh **đích** của một step, bỏ qua giá trị đặt vào đích ấy."""
        target = tuple(sorted((key, value) for key, value in step.args.items() if key in _TARGET_ARG_KEYS))
        return step.tool, target

    @staticmethod
    def _reject_relative_change(text: str, matched: MatchResult) -> MatchResult:
        """`"tăng âm lượng thêm 10"` là lệnh **tương đối** — hỏi lại, đừng đặt tuyệt đối.

        Router không đọc vehicle state (ADR-011) nên không cộng trừ được từ mức hiện
        tại. Nhánh quạt gió đã hỏi lại từ trước vì `"tăng quạt gió"` không mang số;
        nhưng khi câu **có** số thì mọi miền đều đọc nó thành giá trị tuyệt đối và
        chạy luôn: đang ở 60 mà nói `"tăng thêm 10"` thì âm lượng **tụt xuống** 10, và
        `"giảm đi 20"` khi đang ở 10 thì **tăng lên** 20. Cùng lớp lỗi KI-001, chỉ khác
        là nó làm đúng điều ngược lại ý người dùng.

        `đi` không tự nó là dấu hiệu tương đối — `"mở cửa sổ đi"` chỉ là tiểu từ cầu
        khiến. Nó chỉ tính khi đứng **ngay trước** một con số.
        """
        disposition, intent, _reason, _steps = matched
        # Phải xét cả `denied`, y như `_reject_ambiguous_number`: `"tăng nhiệt độ thêm
        # 2 độ"` bị chặn ở dải 16..30 **trước**, nên người dùng nghe `temperature_out_
        # _of_range` — báo sai lý do cho một câu mà vấn đề thật là không cộng trừ được.
        if disposition not in {"control", "denied"}:
            return matched
        tokens = text.split()
        relative = any(token in _RELATIVE_TOKENS for token in tokens)
        if not relative:
            relative = any(
                token == "đi"
                and index + 1 < len(tokens)
                and (tokens[index + 1].isdigit() or tokens[index + 1] in _NUMBER_WORDS)
                for index, token in enumerate(tokens)
            )
        if not relative:
            return matched
        return "clarify", intent, "relative_change_unsupported", ()

    @staticmethod
    def _reject_ambiguous_number(text: str, matched: MatchResult) -> MatchResult:
        """Hai từ số **liền nhau** mà không có `mươi`/`trăm` thì hỏi lại, không đoán.

        `"đặt âm lượng hai bốn"`: fallback của `_number` quét ngược lấy từ số cuối
        nên ra **4**, và 4 nằm trong 0..100 nên lệnh **chạy luôn** với âm lượng 4
        thay vì 24 — tuân thủ một phần trong im lặng, đúng lớp lỗi KI-001.

        `"hai bốn"` (hai từ) đọc được thành 24 — xem `_number`. Nhưng **ba từ số trở
        lên** liền nhau thì không có cách đọc hợp lý nào (`"một hai ba"` là 123? 12
        rồi 3? ba số rời?), nên hỏi lại thay vì đoán.
        """
        disposition, intent, _reason, _steps = matched
        if disposition not in {"control", "denied"}:
            return matched
        # Có chữ số thì `_number` đã lấy từ chữ số (kiểm trước), nên từ số viết chữ
        # không còn ảnh hưởng — không cần chặn.
        if _NUMBER_PATTERN.search(text):
            return matched
        tokens = text.split()
        numerals = [index for index, token in enumerate(tokens) if token in _NUMBER_WORDS]
        if any(len(run) >= 3 for run in _consecutive_runs(numerals)):
            return "clarify", intent, "ambiguous_number", ()
        return matched

    def _looks_imperative(self, text: str) -> bool:
        """Câu bắt đầu bằng một động từ điều khiển — dùng để giới hạn guard actuator."""
        return self._starts_with_command(text, *_COMMAND_VERBS)

    # ---- HVAC -------------------------------------------------------------

    def _match_hvac(self, text: str) -> MatchResult | None:
        fan = "quạt" in text
        # Bảng `HVAC` thay cho hai chuỗi cứng cũ (`điều hòa`, `nhiệt độ`): đợt báo
        # lỗi 24/08 có `bật máy lạnh`, `bật ac`, `bật hệ thống làm mát` — cùng một
        # ý định, ba cách nói, cả ba rơi xuống tra sổ tay.
        if not fan and not co_bat_ky(text, HVAC):
            return None
        turning_on = self._starts_with_command(text, *BAT)
        turning_off = self._starts_with_command(text, *TAT)
        adjusting = self._starts_with_command(text, *DAT_TUYET_DOI, *TANG_GIAM, "hạ")
        if not (turning_on or turning_off or adjusting):
            return None

        # Lượt ghép phải tách **trước** khi đọc số, vì `_number` quét cả câu và sẽ
        # nhặt con số của vế kia. Xem `_match_hvac_compound`.
        #
        # Không còn gác bằng `_CONJUNCTION in text`: lượt ghép không có liên từ cũng
        # phải vào đây, và `_match_hvac_compound` trả `None` cho mọi câu đơn nên
        # nhánh dưới vẫn nguyên vẹn.
        if fan:
            compound = self._match_hvac_compound(text, turning_on, turning_off)
            if compound is not None:
                return compound

        value = self._number(text)

        # Quạt gió phải xét **trước** nhiệt độ. Ngược lại thì "chỉnh quạt gió điều
        # hòa mức 3" bị chuỗi `điều hòa` kéo vào nhánh nhiệt độ, `_number` đọc 3
        # thành độ C, và người dùng nhận `temperature_out_of_range` cho một lệnh
        # quạt — báo sai lý do, đúng lớp lỗi KI-001 (issue #65).
        if fan:
            if turning_off:
                return self._control("hvac_fan_level", "set_hvac_fan_level", {"level": 0})
            if value is None:
                # "tăng/giảm quạt gió" không mang số. Router không đọc vehicle state
                # nên không cộng trừ được từ mức hiện tại — hỏi lại thay vì đoán.
                # FE phải tự tính mức rồi gửi số, y như nó đã làm cho nhiệt độ và
                # sưởi ghế. Xem docs/tasks/TASK-BE-FE-004.
                return "clarify", "hvac_fan_level", "missing_fan_level", ()
            if not 0 <= value <= 3:
                return "denied", "hvac_fan_level", "fan_level_out_of_range", ()
            return self._control("hvac_fan_level", "set_hvac_fan_level", {"level": value})

        if turning_off:
            return self._control("hvac_power", "set_hvac_power", {"enabled": False})

        if turning_on:
            # KI-001: "Bật điều hòa lên 25 độ" phải giữ được cả hai ý định. Bản PoC
            # return ngay ở đây và nuốt mất con số — đó là "tuân thủ một phần trong
            # im lặng", tệ hơn cả từ chối.
            if value is None:
                return self._control("hvac_power", "set_hvac_power", {"enabled": True})
            if not 16 <= value <= 30:
                return "denied", "hvac_temperature", "temperature_out_of_range", ()
            return self._control_steps(
                "hvac_temperature",
                (
                    ("set_hvac_power", {"enabled": True}, ()),
                    ("set_hvac_temperature", {"temperature_c": value}, ("step-1",)),
                ),
            )

        if value is None:
            return "clarify", "hvac_temperature", "missing_temperature", ()
        if not 16 <= value <= 30:
            return "denied", "hvac_temperature", "temperature_out_of_range", ()
        return self._control("hvac_temperature", "set_hvac_temperature", {"temperature_c": value})

    @staticmethod
    def _mentions_temperature(text: str) -> bool:
        """Câu có thật sự nói tới nhiệt độ không.

        Không thể chỉ kiểm `"độ" in text`: `"chỉnh tốc độ quạt gió mức 2"` cũng chứa
        `độ` mà không nói gì về nhiệt độ, và nhận nhầm sẽ khiến router đòi một giá trị
        không ai nêu. Xét đúng từ đứng ngay trước `độ` là đủ tách cả ba dạng thật
        (`nhiệt độ`, `22 độ`, `hai mươi hai độ`) khỏi `tốc độ`.
        """
        tokens = text.split()
        for index, token in enumerate(tokens):
            if token != "độ" or index == 0:
                continue
            previous = tokens[index - 1]
            # `mươi`/`rưỡi` cũng phải tính: `"hai mươi độ"` và `"hai mươi rưỡi độ"` có
            # từ ngay trước `độ` không nằm trong bảng từ số, nên lượt ghép từng bỏ sót.
            if previous == "nhiệt" or previous.isdigit() or previous in _NUMBER_WORDS:
                return True
            if previous in _TENS_TOKENS or previous in _HALF_TOKENS:
                return True
        return False

    def _fan_slot_already_closed(self, text: str, tokens: list[str], fan_position: int, other_position: int) -> bool:
        """Vế quạt đã đủ thông tin **trước khi** cụm domain thứ hai xuất hiện chưa?

        Đây là dấu hiệu thứ tư, và nó bịt ca cuối cùng của lớp lỗi KI-001 trong hàm
        này: `"chỉnh quạt gió mức 2 điều hòa"` — vế sau trần, không động từ, không
        nhiệt độ, không liên từ. Trước đó ba dấu hiệu kia đều vắng nên câu giữ nguyên
        là lệnh quạt và ý điều hòa **bị bỏ trong im lặng**.

        Hai cách một lệnh quạt tự đóng:

        - có `mức <số>` (hay chỉ con số) nằm giữa `quạt` và cụm domain thứ hai;
        - động từ của cả câu là `tắt` — tắt quạt là mức 0, không cần số nào.

        Đây cũng chính là thứ phân biệt với issue #65. `"chỉnh quạt gió điều hòa mức 3"`
        có `quạt` rồi `điều hòa` y hệt, nhưng con số nằm **sau** `điều hòa`, tức lệnh
        quạt chưa đóng khi gặp cụm thứ hai — nên không tách, và nó vẫn là một lệnh quạt.

        Tách xong thì kết quả do `_match_hvac_compound` quyết, đúng như lượt có liên từ:
        `"chỉnh ... điều hòa"` thiếu nhiệt độ nên trả `clarify` **không kèm plan**;
        `"bật ... điều hòa"` thì đủ nghĩa nên chạy cả hai vế.
        """
        if self._starts_with_command(text, "tắt"):
            return True
        between = tokens[fan_position:other_position]
        return any(token == "mức" or token.isdigit() or token in _NUMBER_WORDS for token in between)

    @staticmethod
    def _carries_a_temperature(tail: list[str]) -> bool:
        """Vế bắt đầu tại cụm domain thứ hai có nói về **nhiệt độ** không?

        Đây là dấu hiệu thứ hai — bên cạnh động từ mở đầu — cho biết vế sau là một ý
        riêng chứ không phải phần đuôi của lệnh quạt. Hai hình dạng, và cả hai đều
        không thể xuất hiện trong một lệnh quạt đơn:

        - `"nhiệt độ ..."`: cụm này tường minh là nhiệt độ. `"tốc độ"` không lọt vào
          đây được, vì cặp `("tốc", "độ")` không nằm trong tập cụm domain nên
          `other_position` đã là `None` từ trước.
        - `"điều hòa ... <số> độ"`: `độ` đứng sau cụm `điều hòa` là đơn vị nhiệt độ.

        Chính hình dạng thứ hai giữ nguyên issue #65: `"chỉnh quạt gió điều hòa mức 3"`
        có `điều hòa` nhưng không có `độ` nào theo sau, nên vẫn là một lệnh quạt và
        không bị cắt đôi.
        """
        if tuple(tail[:2]) == ("nhiệt", "độ"):
            return True
        return "độ" in tail[2:]

    def _split_fan_and_rest(self, text: str) -> tuple[str, str] | None:
        """Tách lượt nói thành `(vế quạt, vế còn lại)`. `None` nghĩa là không tách được.

        Hai đường, theo đúng thứ tự tin cậy:

        1. **Liên từ tường minh** (`và`/`rồi`/`với`/`cùng`) — ranh giới do người nói
           nêu ra, nên cứ thế mà cắt.
        2. **Tách ngầm**, khi không có liên từ nào. Đây không phải ca hiếm: `normalize_vi`
           xóa dấu phẩy, và STT không sinh dấu câu, nên `"tắt điều hòa, tắt quạt gió"`
           *nói ra* lẫn *gõ vào* đều tới đây dưới dạng `"tắt điều hòa tắt quạt gió"` —
           một câu có hai ý mà không có một ký tự nào ngăn giữa.

        Đường 2 cắt tại cụm domain đứng **sau**, lùi một token nếu ngay trước đó là
        động từ điều khiển (`"... | tắt quạt gió"`, không phải `"... tắt | quạt gió"`).

        Chốt chặn quan trọng nhất nằm ở `boundary_is_trustworthy`. Cắt bừa sẽ dựng lại
        đúng issue #65: `"chỉnh quạt gió điều hòa mức 3"` là **một** lệnh quạt, nhưng
        nhìn theo token thì nó cũng có `quạt` rồi `điều hòa` y hệt một lượt ghép. Phân
        biệt được vì ở lượt ghép thật, vế sau có ít nhất một trong ba dấu hiệu: chính
        vế quạt là vế đứng sau, vế sau mở đầu bằng động từ của riêng nó, hoặc vế sau
        mang một giá trị nhiệt độ (`_carries_a_temperature`). Câu #65 không có dấu hiệu
        nào nên không tách, và lệnh quạt của nó đi tiếp xuống nhánh câu đơn như cũ.
        """
        segments = [segment for segment in _CONJUNCTION_PATTERN.split(text) if segment]
        if len(segments) >= 2:
            fan_index = next((index for index, segment in enumerate(segments) if "quạt" in segment), None)
            if fan_index is None:
                return None
            rest = _CONJUNCTION_JOIN.join(segment for index, segment in enumerate(segments) if index != fan_index)
            return segments[fan_index], rest

        tokens = text.split()
        fan_position = next((index for index, token in enumerate(tokens) if token == "quạt"), None)
        if fan_position is None:
            return None
        other_position = next(
            (
                index
                for index in range(len(tokens) - 1)
                if (tokens[index], tokens[index + 1]) in {("điều", "hòa"), ("nhiệt", "độ")}
            ),
            None,
        )
        if other_position is None:
            return None

        cut = max(fan_position, other_position)
        # Vế quạt đứng sau là ranh giới đáng tin: mọi thứ trước `quạt` thuộc về ý kia.
        # Ngược lại — vế quạt đứng trước — thì tin khi vế sau tự mở đầu bằng động từ,
        # hoặc khi nó mang một giá trị nhiệt độ (ngay dưới đây).
        boundary_is_trustworthy = cut == fan_position
        if cut == other_position and (
            self._carries_a_temperature(tokens[other_position:])
            or self._fan_slot_already_closed(text, tokens, fan_position, other_position)
        ):
            boundary_is_trustworthy = True
        if tokens[cut - 1 : cut] and tokens[cut - 1] in _COMMAND_VERBS:
            cut -= 1
            boundary_is_trustworthy = True
        if cut == 0 or not boundary_is_trustworthy:
            return None
        before, after = " ".join(tokens[:cut]), " ".join(tokens[cut:])
        return (after, before) if "quạt" in after else (before, after)

    def _match_hvac_compound(self, text: str, turning_on: bool, turning_off: bool) -> MatchResult | None:
        """Một lượt nói CẢ quạt gió lẫn một ý HVAC khác. `None` nghĩa là không phải.

        Hai câu hỏng trước khi có hàm này, cùng một nguyên nhân:

        - `"bật điều hòa 22 độ và quạt gió mức 2"` trả `denied/fan_level_out_of_range`.
          Nhánh quạt chạy trước, `_number()` quét cả câu nên nhặt đúng số 22 của nhiệt
          độ rồi đo nó theo dải quạt 0..3 — mất ý nhiệt độ **và** báo sai lý do.
        - `"tắt điều hòa và quạt gió"` chỉ hạ quạt về 0, nuốt luôn ý tắt điều hòa.

        Cả hai là lớp lỗi KI-001 mà `_match_hvac` tuyên bố tránh; nó chỉ tránh được cho
        câu đơn. Tách vế rồi đọc số **trong từng vế** là đủ, vì mỗi vế lúc đó là một câu
        đơn và `_number` đã đúng cho câu đơn từ trước. Việc tìm ranh giới — kể cả khi
        người nói không dùng liên từ nào — nằm ở `_split_fan_and_rest`.

        Thiếu slot ở bất kỳ vế nào thì hỏi lại **và không chạy vế còn lại**: chạy một
        nửa rồi im lặng về nửa kia đúng là thứ phải tránh.
        """
        split = self._split_fan_and_rest(text)
        if split is None:
            return None
        fan_segment, rest = split

        wants_temperature = self._mentions_temperature(rest)
        if not wants_temperature and "điều hòa" not in rest:
            # Vế kia không thuộc HVAC (`"... và bật đèn trần"`). Ghép chéo domain là
            # khoảng trống có sẵn của `_run_matchers` (matcher đầu tiên khớp thì thắng),
            # không phải việc của hàm này — trả None để giữ nguyên hành vi cũ.
            return None

        # Chỉ `bật`/`tắt` mới là ý **nguồn**. `"chỉnh điều hòa và quạt gió mức 2"`
        # không xin bật máy, nên suy `enabled=True` ra từ đó là tự thêm một việc người
        # dùng không nói — đúng lớp lỗi KI-001 mà cả hàm này sinh ra để tránh.
        #
        # Đường câu đơn xử lý y hệt: `"chỉnh điều hòa"` (không số) trả
        # `clarify missing_temperature`, chứ không bật máy. Hai đường phải khớp nhau.
        wants_power = not wants_temperature and (turning_on or turning_off)
        if not wants_temperature and not wants_power:
            return "clarify", "hvac_temperature", "missing_temperature", ()

        # Vế quạt có thể không mang động từ (`"... và quạt gió mức 2"`); lúc đó nó thừa
        # hưởng động từ của cả câu, nên `"tắt điều hòa và quạt gió"` mới ra mức 0.
        if self._starts_with_command(fan_segment, "tắt") or (turning_off and not self._looks_imperative(fan_segment)):
            level: int | None = 0
        else:
            level = self._number(fan_segment)

        temperature: int | None = None
        if wants_temperature:
            temperature = self._number(rest)
            if temperature is None:
                return "clarify", "hvac_temperature", "missing_temperature", ()
            if not 16 <= temperature <= 30:
                return "denied", "hvac_temperature", "temperature_out_of_range", ()
        if level is None:
            return "clarify", "hvac_fan_level", "missing_fan_level", ()
        if not 0 <= level <= 3:
            return "denied", "hvac_fan_level", "fan_level_out_of_range", ()

        specs: list[tuple[str, dict[str, Any], tuple[str, ...]]] = []
        if wants_power:
            specs.append(("set_hvac_power", {"enabled": not turning_off}, ()))
        elif turning_on:
            specs.append(("set_hvac_power", {"enabled": True}, ()))
        depends = ("step-1",) if specs else ()
        if temperature is not None:
            specs.append(("set_hvac_temperature", {"temperature_c": temperature}, depends))
        specs.append(("set_hvac_fan_level", {"level": level}, depends))
        return self._control_steps("hvac_temperature" if wants_temperature else "hvac_power", tuple(specs))

    # ---- Nhạc -------------------------------------------------------------

    def _match_media_track(self, text: str) -> MatchResult | None:
        """*"Phát bài Carefree"* → `play_track` đúng bài; tên lạ → `denied`, không phát gì.

        Hai nửa đều bắt buộc. Nửa thứ hai là nửa quan trọng hơn: trước thay đổi này
        *"phát bài See Tình"* — một bài **không có** trong playlist — vẫn ra
        `media_control{action: play}` và xe phát một bài khác trong im lặng. Từ chối
        mà vẫn đổi bài thì vẫn là làm một việc không ai yêu cầu, nên nhánh `denied`
        không sinh bước nào cả.

        Điều hướng bài (`bài trước`/`bài tiếp`) xét trước và trả `None` để nhường
        nhánh cũ: chúng chứa chữ `bài` nhưng không gọi tên bài nào.
        """
        if any(cum in text for cum in _PREVIOUS_TRACK + _NEXT_TRACK):
            return None
        if not self._starts_with_command(text, *_PHAT_TRACK_VERBS):
            return None
        track = tim_track_theo_ten(text)
        if track is not None:
            return self._control(
                "media_playback",
                "media_control",
                {"action": "play_track", "track_id": str(track["id"])},
            )
        if self._ten_bai_duoc_goi(text) is None:
            return None
        return "denied", "media_playback", "media_track_unknown", ()

    @staticmethod
    def _ten_bai_duoc_goi(text: str) -> str | None:
        """Phần đứng sau `bài`/`bài hát` khi nó là một **cái tên**, ngược lại `None`.

        Chỉ dùng để phân biệt "người dùng có gọi tên một bài không" — giá trị trả về
        không đi vào lệnh nào, vì tên không khớp playlist thì không có gì để phát.
        """
        for moc in ("bài hát ", "bài "):
            vi_tri = text.find(moc)
            if vi_tri == -1:
                continue
            duoi = text[vi_tri + len(moc) :].strip()
            if not duoi:
                return None
            if duoi.split()[0] in _SAU_BAI_KHONG_PHAI_TEN:
                return None
            return duoi
        return None

    def _match_media_mute(self, text: str) -> MatchResult | None:
        """*"Tắt tiếng"* → `set_volume: 0`; *"bật tiếng lại"* → hỏi lại mức, không đoán.

        Phải đứng **đầu** `_match_music`, trước cả nhánh `"âm lượng"`: `"tắt âm lượng"`
        chứa `âm lượng` nên nhánh ấy nhận câu rồi trượt ngay ở tập động từ của nó
        (`đặt/tăng/giảm/chỉnh/hạ`, không có `tắt`) và trả `None` — câu chết ở giữa
        đường thay vì rơi xuống đây.

        ## `pause` và `set_volume: 0` là hai việc khác nhau, và cả hai đều có thật

        `_apply_media` (`src/vehicle_sim/state.py:317`) cho mỗi action chạm đúng **một**
        trường: `pause` đổi `status`, `set_volume` đổi `volume`. Nên `"tắt nhạc"` dừng
        hẳn (`status: paused`) còn `"tắt tiếng"` vẫn phát mà câm — đúng nghĩa nút mute
        trên đầu phát, và đúng chỗ issue #320 chốt hai cách nói ấy về hai action khác
        nhau thay vì gộp làm một.

        ## Chiều ngược CỐ Ý hỏi lại, không khôi phục

        `MediaState` chỉ có `status/volume/track`, và schema khoá chặt
        (`schemas/mqtt/vehicle_state_domains.schema.json:68`, `additionalProperties: false`)
        nên **không có chỗ nhớ mức trước khi tắt**. `"bật tiếng lại"` vì thế không có gì
        để khôi phục, và mọi con số ta tự chọn — kể cả 35 của trạng thái khởi tạo — là
        đoán một giá trị người dùng không nói ra, đúng lớp lỗi KI-001 mà `_match_media_track`
        ngay bên dưới đã phải trả giá một lần để tránh. Hỏi lại là đường duy nhất còn
        lại cho tới khi có ai chốt việc thêm `muted` vào hợp đồng MQTT — đó là quyết
        định về hợp đồng, không phải về luật.
        """
        if any(cum in text for cum in _TIENG_KHONG_PHAI_AM_THANH):
            return None
        if not any(danh_tu in text for danh_tu in _DANH_TU_AM_THANH):
            return None
        if self._starts_with_command(text, "tắt"):
            return self._control("media_volume", "media_control", {"action": "set_volume", "volume": 0})
        # `bật`/`mở` mà tân ngữ là ÂM THANH, không phải nhạc: `"bật nhạc"` không có
        # chữ nào trong `_DANH_TU_AM_THANH` nên không tới được đây, nó vẫn là `play`.
        if self._starts_with_command(text, "bật", "mở"):
            return "clarify", "media_volume", "missing_volume", ()
        return None

    def _match_media_silence(self, text: str) -> MatchResult | None:
        """*"Im lặng đi"* → `pause`, **đúng bước mà `"tắt nhạc"` sinh ra**.

        ## Đây là một quyết định sản phẩm, không phải một luật suy ra được

        Issue #320 liệt kê `"im lặng đi"` trong **tiêu chí đóng** cùng `"tắt tiếng"` và
        `"tắt nhạc"`, nhưng để ngỏ câu hỏi nó thuộc về `pause` hay `set_volume: 0` —
        chính issue viết *"đây là quyết định sản phẩm chứ không phải hạn chế kỹ thuật"*.
        Bản đầu của PR #340 để câu này ở `not_control` và ghi lý do vào test. PO chốt
        ngược lại ở review #340 (2026-08-28): *"im lặng đi được hiểu là yêu cầu tắt
        nhạc… map vào `media_control { action: pause }`, cùng hành vi với tắt nhạc"*.
        Nên nhánh này đi qua đúng `_control("media_playback", ...)` mà `"tắt nhạc"` dùng,
        không phải một đường song song trả ra cùng giá trị: hai cách nói cùng một ý thì
        phải hỏng cùng nhau khi ai đó sửa một chỗ.

        ## Giới hạn còn lại, nói ra chứ không giấu

        `pause` dừng **dàn nhạc**, không ngắt **TTS**. Người nói *"im lặng đi"* giữa lúc
        VIVI đang đọc một đoạn sổ tay sẽ thấy nhạc dừng còn VIVI đọc tiếp. Lệnh thoại
        ngắt TTS chưa tồn tại (PR #140 chỉ ngắt bằng thao tác tay ở FE), nên đây là
        khoảng trống của hệ chứ không phải của luật này.

        ## Vì sao neo đầu câu

        `_starts_with_command` chứ không phải `in`: `"xe chạy im lặng quá"` là lời khen,
        `"làm sao cho cabin im lặng hơn"` là câu hỏi sổ tay. Chứa-là-khớp biến cả hai
        thành lệnh dừng nhạc — và khác `_UNSUPPORTED_LIGHTS`, ở đây có actuator thật
        đứng cạnh nên khớp nhầm cho ra một lệnh **chạy thật**, không phải một `clarify`
        lạc đề.

        Phải đứng **trên** cổng `"nhạc" not in text and "bài" not in text` của
        `_match_music`: không câu nào trong tập này chứa hai chữ ấy, nên đặt dưới cổng
        là nhánh không bao giờ chạy tới.
        """
        if not self._starts_with_command(text, *_IM_LANG):
            return None
        return self._control("media_playback", "media_control", {"action": "pause"})

    def _match_music(self, text: str) -> MatchResult | None:
        tat_tieng = self._match_media_mute(text)
        if tat_tieng is not None:
            return tat_tieng
        im_lang = self._match_media_silence(text)
        if im_lang is not None:
            return im_lang
        if "âm lượng" in text:
            if not self._starts_with_command(text, "đặt", "tăng", "giảm", "chỉnh", "hạ"):
                return None
            value = self._percent(text)
            if value is None:
                return "clarify", "media_volume", "missing_volume", ()
            if not 0 <= value <= 100:
                return "denied", "media_volume", "volume_out_of_range", ()
            return self._control("media_volume", "media_control", {"action": "set_volume", "volume": value})
        # Gọi đích danh một bài phải xét **trước** mọi nhánh dưới: các nhánh ấy chỉ
        # biết "có nói tới nhạc" nên câu "phát bài Carefree" rơi vào `play` chung và
        # xe phát bài đang đứng đầu playlist — làm một việc khác việc được yêu cầu mà
        # không nói ra (KI-001).
        theo_ten = self._match_media_track(text)
        if theo_ten is not None:
            return theo_ten
        # `bài` cũng là từ khóa domain, không chỉ `nhạc`. Thiếu nó thì "chuyển bài"
        # — cách nói tự nhiên nhất để sang bài kế — rơi xuống mặc định và đi tra sổ
        # tay, nên `next` cũng không gọi được chứ không riêng `previous` (issue #65).
        # `tiếp tục phát` / `phát tiếp` nói rõ là nhạc mà không có chữ `nhạc` —
        # đây là cách nói duy nhất được mở rộng ở đây, vì nó chứa sẵn động từ `phát`.
        # `dừng ngay` **không** được thêm: xem docstring `tu_dong_nghia`.
        if co_bat_ky(text, TIEP_TUC_PHAT):
            return self._control("media_playback", "media_control", {"action": "play"})
        if "nhạc" not in text and "bài" not in text:
            return None
        # `tắt` có mặt ở đây từ issue Đ7, và nó là một lỗ **riêng** lộ ra khi làm ca
        # "bật nhạc, không, tắt đi": `"tắt nhạc"` — cách nói tự nhiên nhất để dừng —
        # rơi xuống tra sổ tay trên develop, trong khi `"dừng nhạc"` chạy. Ánh xạ sang
        # `pause` chứ không phải một action mới: `media_control` không có `stop`, và
        # bịa thêm một action để "tắt" nghe cho đúng chữ là đổi hợp đồng MQTT lấy một
        # từ đồng nghĩa.
        if self._starts_with_command(text, "tạm dừng", "dừng", "tắt"):
            return self._control("media_playback", "media_control", {"action": "pause"})
        # Điều hướng bài phải xét TRƯỚC `phát/bật/mở`: "mở bài trước" là chuyển bài,
        # không phải phát nhạc. Và `previous` phải xét trước `next` vì cả hai cùng mở
        # đầu bằng `chuyển` — "chuyển bài trước" là lùi, không phải tiến.
        if any(phrase in text for phrase in _PREVIOUS_TRACK) or self._starts_with_command(text, "quay lại"):
            return self._control("media_playback", "media_control", {"action": "previous"})
        if any(phrase in text for phrase in _NEXT_TRACK) or self._starts_with_command(text, "chuyển", "tiếp"):
            return self._control("media_playback", "media_control", {"action": "next"})
        if self._starts_with_command(text, *PHAT):
            return self._control("media_playback", "media_control", {"action": "play"})
        return None

    # ---- Cửa sổ -----------------------------------------------------------

    def _match_window(self, text: str) -> MatchResult | None:
        # Thứ tự bắt buộc: loại trừ **trước** khi nhận. `"kính chiếu hậu"` chứa `"kính"`,
        # nên đảo lại là biến câu hỏi về gương thành lệnh hạ kính.
        if any(cum in text for cum in _KINH_KHONG_PHAI_CUA_SO):
            return None
        if not any(cum in text for cum in _CUA_SO_TERMS):
            return None
        # Trước 2b, danh sách này là `mở|đóng|hạ|kéo|nâng` — `chỉnh` có trong
        # `_COMMAND_VERBS` nhưng không có ở đây, nên `"chỉnh cửa sổ bên lái 25%"`
        # chết trong khi `"chỉnh lưng ghế"` sống.
        if not self._starts_with_command(text, *MO_VAT_LY, *DONG_VAT_LY, *DAT_TUYET_DOI):
            return None
        window = self._side(text)
        # Khác cửa xe: ở đây `hết` KHÔNG có nghĩa "tất cả" mà là "mở hết cỡ" (100%),
        # nên chỉ token tường minh mới nhắm cả bốn kính. Bỏ qua chi tiết này thì
        # "mở hết cửa sổ bên phụ" biến thành lệnh bốn kính.
        targets_all = window is None and any(token in text for token in _ALL_POSITIONS)
        if window is None and not targets_all:
            return "clarify", "window_position", "missing_window_side", ()

        # `"mở hết"` (100%) và `"một nửa"` (50%) từng là hai nhánh cứng của riêng chỗ
        # này, nên âm lượng và ghế không thừa hưởng gì: `"đặt âm lượng một nửa"` ra 1.
        # Cả hai đã chuyển vào `_percent`, dùng chung cho ba miền cùng thang 0..100.
        if "đóng" in text:
            percent: int | None = 0
        else:
            percent = self._percent(text)
        if percent is None:
            return "clarify", "window_position", "missing_window_position", ()
        if not 0 <= percent <= 100:
            return "denied", "window_position", "window_position_out_of_range", ()
        if targets_all:
            return self._control_steps(
                "window_position",
                tuple(("set_window_position", {"window": side, "percent": percent}, ()) for side in _ALL_SIDES),
            )
        return self._control("window_position", "set_window_position", {"window": window, "percent": percent})

    # ---- Ghế --------------------------------------------------------------

    def _match_seat(self, text: str) -> MatchResult | None:
        # `làm ấm ghế lái mức 2` chứa `ghế` nên trước đây rơi vào nhánh vị trí, không
        # khớp trục nào và trả `None` — sưởi ghế không bao giờ tới lượt. Xét sưởi
        # trước, và xét bằng bảng alias thay vì đúng chữ `sưởi`.
        if co_bat_ky(text, SUOI_GHE):
            return self._match_seat_heating(text)
        if "ghế" in text:
            return self._match_seat_position(text)
        return None

    def _match_seat_heating(self, text: str) -> MatchResult | None:
        # `làm ấm`/`hâm nóng` vừa là tên gọi vừa là động từ mở đầu (*"làm ấm ghế lái
        # mức 2"*), nên chúng phải có mặt ở cả hai chỗ. Đây là ngoại lệ hẹp: bảng
        # động từ dùng chung là việc của PR 2b, không kéo vào đây.
        if not self._starts_with_command(
            text, "bật", "tắt", "đặt", "tăng", "giảm", "chỉnh", "sưởi", "làm ấm", "hâm nóng"
        ):
            return None
        seat = self._side(text)
        if seat is None:
            return "clarify", "seat_heating", "missing_seat_side", ()
        if self._starts_with_command(text, "tắt"):
            level: int | None = 0
        else:
            level = self._number(text)
        if level is None:
            return "clarify", "seat_heating", "missing_seat_level", ()
        if not 0 <= level <= 3:
            return "denied", "seat_heating", "seat_level_out_of_range", ()
        return self._control("seat_heating", "set_seat_heating", {"seat": seat, "level": level})

    def _match_seat_position(self, text: str) -> MatchResult | None:
        # Bảng `TRUC_GHE` thay ba nhánh if/elif cũ. Thứ tự trong bảng là thứ tự
        # duyệt, và nó khoá được bằng test — recline trước height, nếu không
        # `"dựng lưng ghế lái lên 40%"` (có cả cụm lưng lẫn chữ `lên`) sẽ nâng ghế
        # thay vì ngả lưng: dịch chuyển sai bộ phận, im lặng.
        axis = truc_ghe(text)
        if axis is None:
            return None
        seat = self._side(text)
        if seat is None:
            return "clarify", "seat_position", "missing_seat_side", ()
        value = self._percent(text)
        if value is None:
            return "clarify", "seat_position", "missing_seat_value", ()
        if not 0 <= value <= 100:
            return "denied", "seat_position", "seat_value_out_of_range", ()
        return self._control("seat_position", "set_seat_position", {"seat": seat, "axis": axis, "value": value})

    # ---- Cửa xe -----------------------------------------------------------

    def _match_door(self, text: str) -> MatchResult | None:
        """Sinh candidate mở/đóng cửa. Việc chặn khi xe đang chạy là của policy."""
        if "cửa" not in text or "cửa sổ" in text or "cửa kính" in text:
            return None
        if not self._starts_with_command(text, "mở", "đóng"):
            return None
        state = "closed" if self._starts_with_command(text, "đóng") else "open"
        door = self._side(text)
        if door is None:
            # Nêu **nửa** vị trí — `"mở cửa bên trái"` — thì hỏi lại, không nở ra bốn
            # cửa. Nhánh này phải đứng **trước** nhánh toàn xe ngay dưới: cả hai cùng
            # nhìn thấy `door is None`, và xếp ngược lại thì hàng rào không bao giờ
            # tới lượt. Xem `_VI_TRI_CHUA_DU` cho lý do HITL không thay được nó.
            #
            # `"tất cả"` thắng: `"mở tất cả cửa bên trái"` là một câu tự mâu thuẫn,
            # và giữa "hỏi lại" với "mở bốn cửa" thì hỏi lại là phía an toàn.
            if not any(token in text for token in _ALL_POSITIONS) and any(
                cum in text for cum in _VI_TRI_CHUA_DU
            ):
                return "clarify", "door_state", "missing_door_side", ()
            # Không nêu vị trí — hoặc nêu "tất cả" — thì nhắm cả bốn cửa. Trước đây
            # đây là `clarify`, và issue #65 nêu chính câu trống `"mở cửa"` làm bằng
            # chứng cho khoảng trống này; `VehicleControlView.tsx` cũng gửi đúng câu
            # đó cho nút toàn xe.
            #
            # Không cần hỏi lại để giữ an toàn: `set_door_state` là S2, nên plan này
            # dừng ở HITL và câu xác nhận liệt kê **đủ bốn cửa** — người dùng nhìn
            # thấy chính xác thứ mình đồng ý trước khi có bất kỳ side effect nào.
            return self._control_steps(
                "door_state",
                tuple(("set_door_state", {"door": side, "state": state}, ()) for side in _ALL_SIDES),
            )
        return self._control("door_state", "set_door_state", {"door": door, "state": state})

    # ---- Cốp sau ----------------------------------------------------------

    def _match_trunk(self, text: str) -> MatchResult | None:
        """Cốp là S2/S3 y hệt cửa — phân loại thuộc policy, không thuộc đây."""
        if "cốp" not in text and "khoang hành lý" not in text:
            return None
        if not self._starts_with_command(text, "mở", "đóng"):
            return None
        state = "closed" if self._starts_with_command(text, "đóng") else "open"
        return self._control("trunk_state", "set_trunk_state", {"state": state})

    # ---- Đèn --------------------------------------------------------------

    def _match_lights(self, text: str) -> MatchResult | None:
        """Ánh xạ theo thuật ngữ sổ tay VF9 (mục *Lái xe / Đèn ngoại thất*).

        `đèn chiếu gần` / `đèn chiếu xa` là tên chính thức trong sổ tay; `đèn pha`
        và `đèn cốt` là cách gọi dân dã tương ứng.
        """
        # `chuyển sang chiếu gần` là một câu hoàn chỉnh không có chữ `đèn`. Ràng
        # buộc cũ (bắt buộc có `đèn`) làm nó rơi xuống sổ tay.
        if "đèn" not in text and not co_bat_ky(text, DEN_PHIA_TRUOC):
            return None
        # Câu nêu một loại đèn nằm ngoài bề mặt điều khiển: để nó rơi xuống mặc định
        # (tra sổ tay). Trả `clarify` ở đây là hỏi lại về đèn pha khi người ta đang
        # hỏi về đèn hazard — trả lời sai câu hỏi, và phá đúng thứ ADR-011 đo.
        if any(token in text for token in _UNSUPPORTED_LIGHTS):
            return None
        # `chuyển` có mặt vì `describe_step` sinh ra câu "chuyển đèn sang chế độ
        # tự động" — người dùng lặp lại chính câu đề nghị của hệ thống mà không
        # khớp được là hỏng vòng lặp offer -> đồng ý.
        if not self._starts_with_command(text, *BAT, *TAT, *DAT_TUYET_DOI):
            return None
        turning_off = self._starts_with_command(text, "tắt")

        if "đèn trần" in text or "đèn nội thất" in text or "đèn trong xe" in text:
            return self._control("interior_light", "set_interior_light", {"enabled": not turning_off})

        # Bảng `CHE_DO_DEN` thay cho chuỗi if/elif cũ. Nó thêm `cos`, `low beam`,
        # `high beam`, `auto` — ba cách gọi đo được ở đợt 24/08 và một cách do chính
        # `describe_step` sinh ra. Thứ tự "xa trước gần" giữ nguyên như bản cũ, và
        # bảng khoá nó lại bằng test thay vì bằng vị trí dòng.
        mode = che_do_den(text)
        if mode is None:
            # "bật đèn" trống: không biết đèn nào. Hỏi lại, không đoán.
            return "clarify", "headlight_mode", "missing_light_target", ()

        if turning_off:
            # Không có `off` trong enum `headlight` — UNECE R48 cấm chế độ tắt thủ
            # công trên xe có DRL, xem ADR-020. Từ chối tường minh thay vì ánh xạ
            # ngầm "tắt" -> "auto": ánh xạ ngầm là làm một việc khác việc được yêu
            # cầu mà không nói ra, đúng lớp lỗi KI-001.
            return "denied", "headlight_mode", "headlight_off_not_permitted", ()
        return self._control("headlight_mode", "set_headlight_mode", {"mode": mode})

    # ---- App giải trí -----------------------------------------------------

    def _match_open_app(self, text: str) -> MatchResult | None:
        """*"Mở YouTube"* → `open_app`. ADR-023.

        Đứng **trước** `_match_music` trong `_run_matchers`: khi người nói gọi tên một
        app cụ thể thì họ muốn app đó, nên *"bật nhạc trên Spotify"* mở Spotify chứ
        không phải bấm play trên hệ thống nhạc của xe. *"Mở nhạc"* không có tên app nên
        không khớp luật này và vẫn về `media_control` như cũ.

        Không có tên app trong enum thì **không** khớp — *"mở app"* trần rơi về hành vi
        hiện tại, không đoán bừa một app.
        """
        if not self._starts_with_command(text, "mở", "bật", "vào"):
            return None
        for alias, app in _APP_ALIASES:
            vi_tri = text.find(alias)
            if vi_tri == -1:
                continue
            if not _DUOI_CAU_CHO_PHEP.match(text[vi_tri + len(alias) :]):
                # Có mệnh đề mục đích phía sau — xem `_DUOI_CAU_CHO_PHEP`.
                return None
            return self._control("open_app", "open_app", {"app": app})
        return None

    # ---- Dẫn đường --------------------------------------------------------

    def _match_tim_poi(self, text: str) -> MatchResult | None:
        """Tìm địa điểm quanh xe. Số ít thì chỉ đường luôn, số nhiều thì đọc danh sách.

        Đặt **trước** `_match_navigation` trong `_run_matchers`: câu ghép
        `"tìm quán cà phê gần đây rồi dẫn đường tới đó"` chứa cả `"dẫn đường"`, và
        `_match_navigation` chạy trước sẽ ăn mất nó rồi hỏi lại *"tới đâu"* — vì đại
        từ `"đó"` không tra được ra POI nào (đo 23/08: `unknown_local_destination`).

        Nhánh số ít làm NHIỀU HƠN điều được yêu cầu: câu nói là *tìm*, việc làm là
        *dẫn đường*. Chấp nhận được vì `set_navigation` là S1, đảo ngược được và
        không làm xe chuyển động — nhưng **chỉ** khi câu trả lời nói rõ đã làm gì và
        cho lối thoát; xem `compose.py`. Bỏ vế ấy đi là biến thiết kế này thành lỗi.
        """
        if any(cum in text for cum in _TIM_KHONG_PHAI_TIM_POI):
            return None
        if not any(cum in text for cum in _QUANH_DAY):
            return None
        co_tim = any(text.startswith(v) or f" {v} " in f" {text} " for v in _TIM_VERB)
        if not co_tim and "có" not in text:
            return None
        category = loai_poi_tu_alias(text)
        if category is None:
            return None
        ket_qua = tim_poi_theo_loai(category)
        if not ket_qua:
            return None
        # Số nhiều mà chỉ có đúng một kết quả thì không có gì để chọn — đi luôn.
        if any(cum in text for cum in _SO_NHIEU) and len(ket_qua) > 1:
            return self._control("poi_search", "search_nearby_poi", {"category": category})
        return self._control(
            "navigation_start",
            "set_navigation",
            {"operation": "start", "destination_id": str(ket_qua[0]["id"])},
        )

    def _match_navigation(self, text: str) -> MatchResult | None:
        tuong_minh = any(verb in text for verb in DAN_DUONG_RO)
        if not tuong_minh and not any(verb in text for verb in DAN_DUONG_MO_HO):
            return None
        if tuong_minh and self._starts_with_command(text, "hủy", "dừng", "tắt"):
            return self._control("navigation_cancel", "set_navigation", {"operation": "cancel"})
        if not self._starts_with_command(text, *DAN_DUONG_RO, *DAN_DUONG_MO_HO):
            return None
        destination_id = self._tra_poi(text)
        if destination_id is None:
            # Động từ tường minh thì hỏi lại; động từ mơ hồ thì nhường cho sổ tay.
            # Xem `_NAV_VERB_MO_HO`.
            if not tuong_minh:
                return None
            return "clarify", "navigation_start", "unknown_local_destination", ()
        if self._poi_ids and destination_id not in self._poi_ids:
            return "denied", "navigation_start", "poi_not_in_fixture", ()
        return self._control(
            "navigation_start", "set_navigation", {"operation": "start", "destination_id": destination_id}
        )

    def _tra_poi(self, text: str) -> str | None:
        """Alias đầu tiên xuất hiện trong câu thắng; alias dài đã được xếp trước.

        Trật tự ấy là một phần hợp đồng của `poi_alias_map`, không phải chi tiết trình
        bày: để `"cà phê"` đứng trước `"cà phê bình minh"` thì *"dẫn đường đến cà phê
        bình minh"* sẽ trúng quán sai.
        """
        for alias, poi_id in self._alias_map.items():
            if alias in text:
                return poi_id
        return None

    # ---- Helper -----------------------------------------------------------

    @staticmethod
    def _side(text: str) -> str | None:
        """Vị trí ghế/cửa. `None` nghĩa là câu **không** nêu vị trí nào.

        Hai nhánh `sau ...` phải đứng **trước** hai nhánh trước, và đó không phải chuyện
        gọn gàng: `"mở cửa hành khách sau bên phải"` chứa cả `hành khách` lẫn
        `sau bên phải`. Xếp ngược lại thì alias hàng ghế trước nuốt mất vế chỉ hàng sau
        và câu ra `front_right` — mở nhầm cửa, im lặng. Ca ấy nằm trong bộ đo là
        `BL-N3-004`.

        `tài xế`/`người lái`/`hành khách`/`phụ lái` trần thêm 26/08. Trước đó `_side` trả
        `None` cho chúng, mà `_match_door` hiểu `None` là *"nhắm cả xe"* — nên
        `"mở cửa tài xế"` sinh kế hoạch mở **cả bốn cửa** và đẩy nguyên cái đó qua HITL.
        Đó không phải một câu trả lời lạc đề; đó là một plan S2 **sai đích**.
        """
        if "sau bên trái" in text:
            return "rear_left"
        if "sau bên phải" in text:
            return "rear_right"
        if "bên lái" in text or "ghế lái" in text or "sưởi lái" in text:
            return "front_left"
        if "bên phụ" in text or "ghế phụ" in text or "sưởi phụ" in text:
            return "front_right"
        # Cách gọi theo NGƯỜI ngồi, không theo bên xe. Đứng sau các luật trên vì chúng
        # cụ thể hơn: `"ghế phụ"` đã đủ rõ, không cần đoán qua người ngồi.
        if "tài xế" in text or "người lái" in text:
            return "front_left"
        if "hành khách" in text or "phụ lái" in text:
            return "front_right"
        return None

    @staticmethod
    def _starts_with_command(text: str, *verbs: str) -> bool:
        command = _POLITE_PREFIX_PATTERN.sub("", text, count=1)
        return any(command == verb or command.startswith(f"{verb} ") for verb in verbs)

    @staticmethod
    def _fraction(text: str) -> tuple[int, int] | None:
        """Đọc phân số thành `(tử, mẫu)`. `None` nghĩa là câu không nói phân số.

        Phân số **không phải** một lượng tuyệt đối: `1/3` chỉ có nghĩa khi biết thang
        đo, nên nó dừng ở đây và để `_percent` quy đổi. Miền nào không tính theo phần
        trăm (nhiệt độ, mức quạt) sẽ nhận `None` từ `_number` và hỏi lại, thay vì đọc
        bừa tử số.
        """
        stripped = _PERCENT_UNIT_PATTERN.sub(" ", text)
        digits = _FRACTION_PATTERN.search(stripped)
        if digits:
            numerator, denominator = int(digits.group(1)), int(digits.group(2))
            return (numerator, denominator) if denominator else None

        words = _WORD_FRACTION_PATTERN.search(stripped)
        if words:
            numerator = _NUMBER_WORDS.get(words.group(1), -1)
            denominator = _NUMBER_WORDS.get(words.group(2), -1)
            if numerator >= 0 and denominator > 0:
                return numerator, denominator

        # `"nửa"` = 1/2 ở mọi miền, không riêng cửa kính. `"rưỡi"` chỉ là 1/2 khi
        # đứng một mình; đi sau một con số thì nó là phần lẻ — `_number` xử lý.
        if "nửa" in stripped.split():
            return 1, 2
        return None

    @classmethod
    def _percent(cls, text: str) -> int | None:
        """Đọc lượng trên thang 0..100 — dùng cho kính, ghế và âm lượng.

        Ba miền này cùng một thang nên cùng hiểu được phân số và cách nói "kịch mức".
        Trước đây `"một nửa"` = 50 là một nhánh cứng của **riêng** `_match_window`, nên
        `"đặt âm lượng một nửa"` ra volume **1** và `"ngả ghế một nửa"` ra value **1**:
        cùng một từ, ba kết quả khác nhau tuỳ miền.
        """
        if any(phrase in text for phrase in _MAXIMUM_PHRASES):
            return 100
        fraction = cls._fraction(text)
        if fraction is not None:
            numerator, denominator = fraction
            return round(numerator * 100 / denominator)
        value = cls._number(text)
        return None if value is None else round(value)

    @classmethod
    def _number(cls, text: str) -> float | None:
        """Đọc số Ả Rập trước, rồi tới số viết chữ (`hai mươi tư` → 24).

        Trăm và chục phải đọc **cùng một lượt**, theo thứ tự trong câu. Bản đầu quét
        `mươi` trước rồi mới quét `trăm`, nên `"một trăm hai mươi"` trả 20 — và 20
        nằm trong 0..100 nên lệnh **chạy luôn** với âm lượng 20 thay vì bị từ chối
        vì 120 ngoài khoảng. Lại đúng lớp lỗi KI-001.

        Hậu tố `phần trăm` phải cắt **trước** khi tách token, vì `trăm` trong đó là
        một phần của tên đơn vị chứ không phải toán tử hàng trăm. Không cắt thì
        `"năm mươi phần trăm"` tìm số đứng ngay trước `trăm`, gặp `phần`, và trả
        None — router hỏi lại đúng cái người dùng vừa nói rõ (issue #117). Dạng chữ
        số không lộ lỗi này vì `_NUMBER_PATTERN` chặn trước.

        Trả `float` vì `SetHvacTemperatureArgs.temperature_c` là float: `"hai mươi
        rưỡi độ"` và `"22,5 độ"` biểu diễn được. Miền số nguyên gọi qua `_percent`
        (làm tròn) hoặc tự kiểm.
        """
        tokens_raw = text.split()
        # Lượng không xác định và lượng định tính đều KHÔNG quy ra số được. Bỏ hai
        # guard này thì `"mười mấy phần trăm"` ra 10 và `"mở một chút"` ra 1 — đoán
        # bừa rồi chạy, thay vì hỏi lại.
        if any(token in _INDEFINITE_TOKENS for token in tokens_raw):
            return None
        if any(token in _QUALITATIVE_TOKENS for token in tokens_raw):
            return None
        # Phân số không phải lượng tuyệt đối — xem `_fraction`.
        if cls._fraction(text) is not None:
            return None

        decimal = _DECIMAL_PATTERN.search(text)
        if decimal:
            return float(f"{decimal.group(1)}.{decimal.group(2)}")

        match = _NUMBER_PATTERN.search(text)
        if match:
            return int(match.group(1))

        tokens = _PERCENT_UNIT_PATTERN.sub(" ", text).split()
        # `rưỡi` sau một con số là phần lẻ 0,5 (`"hai mươi rưỡi"` = 20,5). Tách nó ra
        # trước rồi cộng lại, để nhánh hàng chục bên dưới không phải biết tới nó.
        half = "rưỡi" in tokens
        if half:
            tokens = [token for token in tokens if token != "rưỡi"]
            whole = cls._words_to_number(tokens)
            return None if whole is None else whole + 0.5
        return cls._words_to_number(tokens)

    @staticmethod
    def _words_to_number(tokens: list[str]) -> int | None:
        """Phần đọc số viết chữ của `_number`, sau khi mọi guard đã chạy."""
        # Hai luật chồng lên nhau, và cả hai đều cần — theo đúng thứ tự này:
        #
        # 1. `bo_tieu_tu_cuoi` — "cuối câu" trong lời nói thật là cuối câu SAU tiểu từ:
        #    `"bật điều hòa được không vậy"` từng đọc ra 0 độ C rồi trả
        #    `denied / temperature_out_of_range` cho một câu hỏi (đo 22/08, #244).
        # 2. `_loc_khong_khong_phai_so` — `"không"` là số 0 **chỉ khi có từ neo đứng ngay
        #    trước**, và tập neo chỉ còn `mức`. Bản trước chỉ bỏ `"không"` khi nó đứng
        #    cuối, nên mọi chữ `"không"` GIỮA câu đều thành số 0. Đo trên develop 25/08,
        #    hai ca làm **ngược lệnh**:
        #
        #        "mở cửa sổ bên lái không cần nhiều" -> percent 0 (ĐÓNG kính, người ta bảo MỞ)
        #        "tăng âm lượng không nghe rõ"       -> volume 0  (TẮT tiếng, người ta bảo TĂNG)
        #
        #    Và sai luôn chiều ngược: `"đặt quạt gió mức không"` — chỗ `"không"` THẬT SỰ
        #    là số 0 — bị bỏ mất, nên nói số 0 ra miệng là bất khả, trong khi STT **luôn**
        #    chép số 0 nói ra thành chữ này.
        #
        # Luật 2 bao trùm phần "bỏ `không` ở cuối", nhưng luật 1 vẫn phải chạy TRƯỚC, vì
        # nó mới là thứ đưa `"không"` về đúng vị trí cuối để luật 2 xét từ neo.
        tokens = bo_tieu_tu_cuoi(tokens)
        tokens = _loc_khong_khong_phai_so(tokens)
        total = 0
        rest = tokens
        if "trăm" in tokens:
            position = tokens.index("trăm")
            preceding = _NUMBER_WORDS.get(tokens[position - 1]) if position > 0 else None
            # `"trăm phần trăm"` = 100%: cắt đơn vị xong còn mỗi `trăm`, không hệ số.
            # Hệ số ngầm là 1, y như `mười`. Mặc định này chỉ an toàn **nhờ** bước cắt
            # đơn vị ở `_number`; không có nó thì `phần` đứng trước `trăm` sẽ bị đọc
            # thành "một trăm" — tức đổi bug #117 từ hỏi lại sang chạy sai 100%.
            hundreds = 1 if preceding is None else preceding
            if not hundreds:
                return None
            total = hundreds * 100
            rest = tokens[position + 1 :]

        # `mười` tự nó đã là 10 (`"mười lăm"` = 15); `mươi` phải mượn hệ số của từ số
        # đứng trước (`"năm mươi"` = 50). Thiếu `mười` ở đây thì vòng quét ngược phía
        # dưới nhặt `lăm` và mở kính **5%** trong im lặng — đúng lớp lỗi KI-001. Trước
        # khi cắt hậu tố `phần trăm` thì lỗi đó bị chính bug #117 che mất.
        tens_at = next((index for index, token in enumerate(rest) if token in _TENS_TOKENS), None)
        if tens_at is not None:
            if rest[tens_at] == "mười":
                tens: int | None = 1
            else:
                tens = _NUMBER_WORDS.get(rest[tens_at - 1]) if tens_at > 0 else None
            if tens:
                total += tens * 10
                if tens_at + 1 < len(rest):
                    total += _NUMBER_WORDS.get(rest[tens_at + 1], 0)
                return total
            return total or None

        # `"hai bốn"` = 24: cách nói nhanh, bỏ `mươi`. Đọc thành chục + đơn vị.
        # Bản đầu quét ngược lấy từ số cuối nên ra 4, và 4 nằm trong 0..100 nên âm
        # lượng **chạy luôn** với giá trị sai — đúng lớp lỗi KI-001.
        # Ba từ số liền nhau trở lên thì không có cách đọc hợp lý nào; để
        # `_reject_ambiguous_number` hỏi lại.
        numerals = [index for index, token in enumerate(rest) if token in _NUMBER_WORDS]
        runs = _consecutive_runs(numerals)
        pair = next((run for run in runs if len(run) == 2), None)
        if pair is not None:
            tens, units = (_NUMBER_WORDS[rest[position]] for position in pair)
            if tens:
                return total + tens * 10 + units

        for token in reversed(rest):
            if token in _NUMBER_WORDS:
                return total + _NUMBER_WORDS[token]
        return total or None

    @staticmethod
    def _control(intent: Intent, tool: str, args: dict[str, Any]) -> MatchResult:
        return (
            "control",
            intent,
            "deterministic_rule",
            (CandidateStep(step_id="step-1", ordinal=0, tool=tool, args=args),),
        )

    @staticmethod
    def _control_steps(intent: Intent, specs: tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...]) -> MatchResult:
        steps = tuple(
            CandidateStep(step_id=f"step-{index + 1}", ordinal=index, tool=tool, args=args, depends_on=depends_on)
            for index, (tool, args, depends_on) in enumerate(specs)
        )
        return "control", intent, "deterministic_rule", steps
