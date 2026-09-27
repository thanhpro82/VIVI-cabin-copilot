""":Chữ `"không"` là **số 0** hay là **phủ định**? Đọc sai chiều nào cũng nguy hiểm.

Phát hiện 25/08 khi CI của #267 đỏ. Đo trên `develop`, hai chiều sai cùng lúc:

```
"mở cửa sổ bên lái không cần nhiều"  -> percent 0   ĐÓNG kính khi người ta bảo MỞ
"tăng âm lượng không nghe rõ"        -> volume 0    TẮT tiếng khi người ta bảo TĂNG
"chỉnh quạt gió mức không"           -> clarify     từ chối đúng lúc "không" LÀ số 0
```

Hai ca đầu cùng lớp với BUG-02 (làm ngược lệnh): xe làm điều trái hẳn câu nói, và
composer vẫn báo "đã thực hiện".

Luật phân biệt: `"không"` là số 0 **chỉ khi có từ neo đứng ngay trước** — và tập neo
chỉ còn đúng một từ, `mức`. Không có neo thì nó là phủ định hoặc tiểu từ nghi vấn — cả
hai đều **không phải số**, nên bị loại khỏi chuỗi đọc số.

Tập neo là **danh sách đóng và phải trả giá**: sáu mục của bản đầu đã bị loại theo hai
lớp bằng chứng khác nhau — `là`/`còn`/`đến`/`tới` vì gây hại đo được, `về`/`bằng` vì ca
dương tính của chúng là câu do chính người viết luật tự nghĩ ra. Lý do đầy đủ nằm ở
docstring của `NEO_SO_KHONG`; ở đây khoá bằng
`test_sau_tu_neo_da_loai_khong_duoc_quay_lai`.
"""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src.agents.contracts import ActionPlan
from src.agents.graph import build_graph
from src.agents.nodes.normalize import normalize_vi
from src.agents.policy import materialize_action_plan
from src.agents.question import NEO_SO_KHONG, is_question
from src.agents.router import DeterministicControlRouter
from src.services.vehicle_gateway import InProcessVehicleGateway

router = DeterministicControlRouter()


def _buoc(text: str):
    d = router.route(text)
    return d, [(s.tool, s.args) for s in (d.candidate_plan.steps if d.candidate_plan else [])]


@pytest.mark.parametrize(
    "text",
    [
        "chỉnh quạt gió tôi không biết",
        "bật quạt gió không biết mức nào",
        "đặt âm lượng không cần to lắm",
        "tăng âm lượng không nghe rõ",
        "mở cửa sổ bên lái không cần nhiều",
    ],
)
def test_khong_phu_dinh_khong_bao_gio_thanh_so_0(text):
    """Không có từ neo thì `"không"` không phải số — và tuyệt đối không được ra 0."""
    quyet_dinh, buoc = _buoc(text)
    for _, args in buoc:
        assert 0 not in args.values(), f"{text!r} đọc `không` thành số 0: {args}"
    assert quyet_dinh.disposition != "control" or not buoc


@pytest.mark.parametrize(
    ("text", "mong_doi"),
    [
        ("đặt quạt gió mức không", ("set_hvac_fan_level", {"level": 0})),
        ("chỉnh quạt gió mức không", ("set_hvac_fan_level", {"level": 0})),
    ],
)
def test_co_tu_neo_thi_khong_dung_la_so_0(text, mong_doi):
    """Chiều ngược lại: có neo thì phải đọc được, nếu không thì nói số 0 ra miệng
    là bất khả — mà STT **luôn** chép số 0 nói ra thành chữ này."""
    _, buoc = _buoc(text)
    assert buoc == [mong_doi], text


def test_dang_nghi_van_van_khong_phai_so():
    """`"được không"` là tiểu từ nghi vấn — không neo, nên không phải 0.

    Nếu đọc thành 0 thì `"mở cửa sổ bên lái được không"` thành lời đề nghị **đóng**
    kính, ngược hẳn ý người hỏi.
    """
    _, buoc = _buoc("mở cửa sổ bên lái được không")
    for _, args in buoc:
        assert args.get("percent") != 0


# --- Điều kiện 1 & 2 của review #268 --------------------------------------------
#
# Tập neo là quyết định SẢN PHẨM: mỗi từ thêm vào là một chỗ mà chữ `"không"` thôi
# là phủ định và thành một con số đi vào lệnh. Nên nó phải chịu hai phép thử ngược
# chiều nhau — có ca dương tính thật, và không nuốt câu không phải lệnh.


@pytest.mark.parametrize(
    ("neo", "text", "mong_doi"),
    [
        ("mức", "đặt quạt gió mức không", ("set_hvac_fan_level", {"level": 0})),
    ],
)
def test_tung_tu_neo_deu_co_ca_duong_tinh(neo, text, mong_doi):
    """Điều kiện 2: mỗi từ neo phải **thực sự đặt được giá trị 0**, nếu không thì nó
    chỉ mở rộng bề mặt sinh lệnh mà không mua lại gì.

    `mức` là từ duy nhất còn lại, và nó ở lại vì nguồn độc lập: câu do người khác viết
    trong `eval/datasets/agent/` đã dùng đúng cấu trúc ấy (`"Bật sưởi ghế lái mức 2"`).
    """
    assert neo in NEO_SO_KHONG
    _, buoc = _buoc(text)
    assert buoc == [mong_doi], f"neo {neo!r} không có ca dương tính: {text!r} -> {buoc}"


def test_moi_tu_neo_deu_duoc_mot_ca_duong_tinh_o_tren_bao_ve():
    """Khoá chiều còn lại của điều kiện 2: thêm một từ vào `NEO_SO_KHONG` mà quên ca
    dương tính thì test này đỏ, chứ không lặng lẽ trôi qua review."""
    co_ca = {"mức"}
    assert set(NEO_SO_KHONG) == co_ca, (
        "NEO_SO_KHONG đổi mà bảng ca dương tính ở trên chưa đổi theo — "
        f"thừa: {set(NEO_SO_KHONG) - co_ca}, thiếu: {co_ca - set(NEO_SO_KHONG)}"
    )


@pytest.mark.parametrize(
    "text",
    [
        # `là` — trùng "vấn đề là không...". Đo 26/08 khi `là` còn là neo:
        # ra `denied / temperature_out_of_range`, một lý do 0 °C KHÔNG CÓ THẬT.
        "bật điều hòa lên đi vấn đề là không ai chịu được",
        "điều hòa vấn đề là không mát",
        # `còn` — trùng dạng hỏi thông dụng nhất.
        "quạt gió còn không",
        "âm lượng còn không",
        "mở nhạc lên xem còn không",
        # `đến` / `tới` — đứng ngay trước "không gian"/"không khí", nơi "không" là
        # âm tiết đầu của từ ghép.
        "dẫn đường đến không gian xanh",
        "đưa tôi tới không gian bốn mùa",
        # `bằng` ở ngữ cảnh không phải mệnh lệnh gán giá trị.
        "chỉnh gió lấy bằng không khí ngoài trời",
    ],
)
def test_ngu_canh_khong_phai_menh_lenh_khong_bao_gio_sinh_gia_tri_0(text):
    """Điều kiện 1: các câu này không phải lệnh "đặt về 0", nên **không** kế hoạch nào
    được mang giá trị 0."""
    quyet_dinh, buoc = _buoc(text)
    for tool, args in buoc:
        assert 0 not in args.values(), f"{text!r} sinh giá trị 0 ở {tool}: {args}"


@pytest.mark.parametrize(
    "text",
    ["quạt gió còn không", "âm lượng còn không", "xăng còn không"],
)
def test_cau_hoi_con_khong_van_duoc_nhan_la_cau_hoi(text):
    """Thiệt hại đo được của neo `còn`, khoá lại để nó không quay về: khi `còn` còn
    nằm trong tập neo, cả ba câu này `is_question` trả **False** — một câu hỏi rõ ràng
    thôi được nhận là câu hỏi, nên nó không đi đường tắt sổ tay nữa."""
    assert is_question(normalize_vi(text), text) is True


def test_sau_tu_neo_da_loai_khong_duoc_quay_lai():
    """Sáu từ bị loại theo điều kiện 2 của review #268, theo hai lớp bằng chứng:

    - `là`, `còn`, `đến`, `tới` — **gây hại đo được** (xem docstring `NEO_SO_KHONG`).
    - `về`, `bằng` — không hại, nhưng ca dương tính duy nhất của chúng là câu do chính
      người viết luật tự nghĩ ra; grep `eval/datasets/` + corpus sổ tay ra 0.

    Thêm lại thì phải kèm bằng chứng từ nguồn độc lập — test này là chỗ bắt buộc đọc
    trước khi làm thế.
    """
    for tu in ("đến", "tới", "còn", "là", "về", "bằng"):
        assert tu not in NEO_SO_KHONG


def test_gia_phai_tra_cua_viec_loai_ve_va_bang_di_so_tay_chu_khong_phai_lam_sai():
    """Chi phí đo được của quyết định trên, viết thành test để nó không bị quên.

    Bỏ `về`/`bằng` nghĩa là `"đặt âm lượng về không"` không còn đọc ra số 0. Chiều hỏng
    ấy phải là chiều **an toàn** — đi sổ tay, chứ không phải đặt nhầm một giá trị khác.
    """
    quyet_dinh, buoc = _buoc("đặt âm lượng về không")

    assert buoc == []
    assert quyet_dinh.disposition == "not_control"
    assert quyet_dinh.reason == "manual_question"


def test_no_cua_am_luong_0_da_tra_o_tat_tieng_con_lai_mot_nua():
    """Nợ mà #268 ghi lại ở đây đã trả được một nửa — và nửa còn lại là cố ý.

    Tên cũ: `test_am_luong_0_khong_con_duong_nao_khac_va_do_la_no_da_ghi`. Đổi tên vì
    mệnh đề "không còn đường nào khác" giờ sai: #320 mở cửa trước.

    Bối cảnh cũ giữ nguyên giá trị: `"tắt quạt gió"` đã đặt `set_hvac_fan_level(level=0)`
    mà không cần từ neo nào, nên bỏ `về`/`bằng` khỏi `NEO_SO_KHONG` không làm mất tính
    năng của quạt. Âm lượng thì mất đường **nói ra miệng**, vì STT chép số 0 người ta đọc
    thành chữ `"không"` chứ không thành ký tự `0`.

    Nợ ấy nay trả bằng chính chỗ #268 chỉ ra là đúng chỗ — cửa trước, không phải một từ
    neo cứng nhắc ở cửa sau: `"tắt tiếng"` ra `set_volume: 0` qua luật.

    `"im lặng đi"` giờ ra `pause`, và **nó không suy ra được từ code** — PO chốt ở review
    #340 (2026-08-28) rằng câu ấy được hiểu là yêu cầu tắt nhạc. Bản đầu của PR để nó ở
    `not_control` vì câu có hai nghĩa và nghĩa kia (*"VIVI đừng đọc nữa"*, tức ngắt TTS)
    chưa có lệnh thoại nào phục vụ. Quyết định ấy đã được đưa ra, nên phần còn lại của
    lập luận cũ chỉ còn là một **giới hạn phải nói ra**: `pause` dừng dàn nhạc chứ không
    ngắt TTS, nên nói câu này giữa lúc VIVI đang đọc thì nhạc dừng còn VIVI đọc tiếp.

    Đừng "sửa lại cho nhất quán" bằng cách trả câu này về `not_control`: nó là **tiêu chí
    đóng** của issue #320 (*"ba câu ở trên ra `control`"* — `tắt tiếng`, `tắt nhạc`,
    `im lặng đi`).
    """
    _, buoc_quat = _buoc("tắt quạt gió")
    assert buoc_quat == [("set_hvac_fan_level", {"level": 0})]

    quyet_dinh, buoc = _buoc("tắt tiếng")
    assert quyet_dinh.disposition == "control"
    assert buoc == [("media_control", {"action": "set_volume", "volume": 0})]

    quyet_dinh, buoc = _buoc("im lặng đi")
    assert quyet_dinh.disposition == "control"
    assert buoc == [("media_control", {"action": "pause"})]


# --- Điều kiện 3: đi hết đường tới executor --------------------------------------


async def test_ca_nguy_hiem_khong_cham_toi_executor():
    """Điều kiện 3 của review #268: khẳng định ở tầng router là chưa đủ.

    Lý do phải chạy hết đường, chứ không phải để cho đủ lớp: plan mà bug này dựng ra
    là `set_hvac_fan_level(level=0)` — **S1**, tức chạy thẳng **không** qua HITL. Tầng
    an toàn không hề chặn nó, nên "router không ra control" và "xe không nhận lệnh" là
    hai mệnh đề khác nhau, và chỉ mệnh đề thứ hai mới là điều tài xế quan tâm.

    Đo bằng `command_count` của gateway — đúng cái đếm lệnh publish, nên số 0 ở đây
    nghĩa là không có side effect nào, không phải "không tìm thấy assertion nào để sai".
    """
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, checkpointer=InMemorySaver())

    ket_qua = await graph.ainvoke(
        {"query": "chỉnh quạt gió tôi không biết", "session_id": "ses-neo", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-neo"}},
    )

    assert gateway.command_count == 0, "một câu KHÔNG phải lệnh vừa chạm tới xe"
    assert ket_qua["outcome"] != "completed"
    assert ket_qua.get("action_plan") is None


async def test_doi_chung_lenh_that_van_toi_duoc_executor():
    """Đối chứng bắt buộc cho ca trên: không có nó thì `command_count == 0` có thể xanh
    vì một lý do hoàn toàn khác — gateway trong test này chưa bao giờ nhận lệnh nào."""
    gateway = InProcessVehicleGateway.new()
    graph = build_graph(gateway, checkpointer=InMemorySaver())

    await graph.ainvoke(
        {"query": "đặt quạt gió mức không", "session_id": "ses-neo2", "vehicle_id": "veh-1"},
        config={"configurable": {"thread_id": "t-neo2"}},
    )

    assert gateway.command_count == 1


def test_neu_van_ra_control_thi_policy_van_phai_thay_dung_gia_tri():
    """Ca dương tính ở tầng policy: `"đặt quạt gió mức không"` **là** lệnh thật, nên nó
    phải qua được policy với đúng `level=0` và mức S1 — không bị luật mới chặn nhầm."""
    quyet_dinh = router.route("đặt quạt gió mức không")
    assert quyet_dinh.candidate_plan is not None

    plan: ActionPlan = materialize_action_plan(
        quyet_dinh.candidate_plan,
        {"speed_kph": 0, "gear": "P", "state_version": 1},
        "ses-neo",
        "veh-1",
    )

    assert [(b.tool, dict(b.args)) for b in plan.steps] == [("set_hvac_fan_level", {"level": 0})]
    assert [b.safety_level for b in plan.steps] == ["S1"]
    assert plan.requires_approval is False
