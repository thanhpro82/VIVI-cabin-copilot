"""S3 — tài xế nói "đọc tiếp" và xe đọc nốt phần còn lại.

Lời mời *"Bạn có muốn nghe tiếp nguyên văn không?"* đã phát ra từ 13/08, nhưng nửa
còn lại thì chưa có: "đọc tiếp" rơi xuống `default_to_manual`, đi tra sổ tay lần nữa
bằng chính chữ "đọc tiếp", và trả về một đoạn khác hẳn. Xe tự hỏi rồi tự lờ.

Vì sao S3 mới là chỗ đáng làm, chứ không phải S2: sau khi nới cờ biến thể (14/08),
**39/40 ca có câu trả lời nằm ngay trong đoạn tài xế đang nghe** — cột "+một phần"
đạt 97,5%. Nút thắt không còn là *chọn nhầm câu* mà là *nói 240 ký tự rồi dừng*.
Chọn câu khéo hơn không vượt được trần đó; đọc tiếp thì có.

Trạng thái đọc dở sống ở `AgentState` qua checkpoint LangGraph, khoá theo
`thread_id = session_id` (`src/api/session_state.py:thread_config`). Không cần kho
mới: nó **phải** chết cùng tiến trình, y như checkpoint giữ `interrupt()` của HITL.
"""

import pytest

from src.agents.nodes.compose import compose_node
from src.agents.nodes.speech_policy import _INVITE, cau_noi_hoan_chinh, chon_cau_de_noi, doc_tiep
from src.rag.models import Evidence

DOAN = (
    "Khởi tạo cửa sổ điện. "
    "Nếu không thể tự động đóng các cửa sổ thông qua chức năng nhanh, hãy làm như sau. "
    "Kéo công tắc cửa sổ lên và đóng hoàn toàn cửa sổ. "
    "Giữ công tắc ở trạng thái kéo trong hai giây. "
    "Nhả công tắc ra. "
    "Nhấn hoàn toàn công tắc cửa sổ xuống để mở cửa sổ tự động. "
    "Kéo hoàn toàn công tắc cửa sổ lên để đóng cửa sổ tự động. "
    "Lặp lại cho mỗi cửa sổ trên xe. "
    # Đoạn phải đủ dài cho **ít nhất ba lát** ở trần 240 ký tự, nếu không lát thứ hai
    # vét hết và test "đọc tiếp có tiến không" mất nghĩa — nó sẽ đo nhánh dọn trạng
    # thái thay vì nhánh đọc tiếp. Đoạn sổ tay thật dài p50 950 ký tự, nên đây mới là
    # kích thước điển hình chứ không phải trường hợp biên.
    "Trong quá trình khởi tạo, cửa sổ điện không có chức năng cảm biến chống kẹp. "
    "Đảm bảo không có bộ phận cơ thể hoặc vật nào cản trở việc đóng cửa sổ điện. "
    "Nếu không, sẽ gây hư hỏng và ảnh hưởng đến kết quả của quá trình khởi tạo. "
    "Nếu hệ thống cửa sổ điện bị hỏng, vui lòng đến trung tâm dịch vụ gần nhất."
)


def _luot_dau(text: str = DOAN) -> dict:
    return {
        "outcome": "grounded_answer",
        "query": "cách khởi tạo cửa sổ điện",
        "evidence": [Evidence(section="Cửa sổ điện", page=3, text=text, chunk_id="c1", score=0.9)],
    }


@pytest.mark.asyncio
async def test_luot_so_tay_ghi_lai_cho_dang_doc_do():
    """Không ghi lại thì lượt sau không có gì để tiếp — và lời mời thành lời hứa suông."""
    out = await compose_node(_luot_dau())

    assert out["speech_source_text"] == DOAN
    assert out["speech_da_doc"], "phai ghi lai cau nao da doc"
    # Chỗ dừng phải trùng đúng phần đã nói, nếu không lượt sau sẽ nhảy cóc hoặc lặp.
    # Cau da ghi phai dung la cau da noi ra.
    from src.agents.nodes.speech_policy import _cau

    for i in out["speech_da_doc"]:
        assert _cau(DOAN)[i][:30] in out["speak_text"]


@pytest.mark.asyncio
async def test_doc_tiep_noi_dung_phan_ke_sau_khong_lap_lai():
    dau = await compose_node(_luot_dau())
    tiep = await compose_node(
        {
            "outcome": "not_control",
            "intent": "manual_continue",
            "query": "đọc tiếp",
            "speech_source_text": dau["speech_source_text"],
            "speech_da_doc": dau["speech_da_doc"],
        }
    )

    assert tiep["speak_text"]
    assert tiep["speak_text"] not in dau["speak_text"]
    assert set(tiep["speech_da_doc"]) > set(dau["speech_da_doc"])
    # Nguyên văn, không diễn đạt lại — bất biến của cả nhánh sổ tay (ADR-015).
    phan_noi = tiep["speak_text"].split(" Bạn có muốn")[0].strip()
    assert phan_noi in DOAN


@pytest.mark.asyncio
async def test_doc_het_thi_noi_la_het_va_don_trang_thai():
    """Đọc hết mà vẫn mời "nghe tiếp" là mời vào chỗ trống."""
    out = await compose_node(_luot_dau())
    so_lat = 1
    # Tín hiệu "hết" là **trạng thái đã dọn**, không phải offset chạm cuối: lát cuối vét
    # hết thì dọn ngay về rỗng, nên offset quay về 0 chứ không bằng len(nguồn).
    for _ in range(20):
        if not out["speech_source_text"]:
            break
        out = await compose_node(
            {
                "outcome": "not_control",
                "intent": "manual_continue",
                "query": "đọc tiếp",
                "speech_source_text": out["speech_source_text"],
                "speech_da_doc": out["speech_da_doc"],
            }
        )
        so_lat += 1
    else:
        pytest.fail("khong bao gio doc het — vong lap khong tien")

    assert so_lat >= 3, f"doan {len(DOAN)} ky tu chi chia {so_lat} lat — fixture qua ngan de test S3"
    assert "nghe tiếp" not in out["speak_text"]
    assert out["speech_da_doc"] == []

    # Bảo "đọc tiếp" thêm lần nữa: phải nghe "đã đọc hết", không được đọc lại lát cuối.
    lai = await compose_node(
        {
            "outcome": "not_control",
            "intent": "manual_continue",
            "query": "đọc tiếp",
            "speech_source_text": "",
            "speech_da_doc": [],
        }
    )
    assert "hết" in lai["speak_text"].lower()


@pytest.mark.asyncio
async def test_doc_tiep_khi_chua_hoi_gi_thi_noi_khong_co_gi_de_tiep():
    """Trạng thái đọc dở chết cùng tiến trình. Sau khi backend restart, "đọc tiếp"
    phải trả lời tử tế chứ không được vỡ hay im lặng."""
    out = await compose_node({"outcome": "not_control", "intent": "manual_continue", "query": "đọc tiếp"})

    assert out["speak_text"]
    assert "nghe tiếp" not in out["speak_text"]


@pytest.mark.asyncio
async def test_luot_dieu_khien_khong_dung_toi_trang_thai_doc_do():
    """Bật điều hoà giữa chừng không được xoá chỗ đang đọc dở.

    Tài xế hỏi sổ tay, nghe một đoạn, bảo xe bật điều hoà, rồi nói "đọc tiếp" — chuỗi
    đó là bình thường trong xe, và nó phải chạy được.
    """
    out = await compose_node({"outcome": "executed", "query": "bật điều hoà", "step_results": []})

    assert "speech_source_text" not in out
    assert "speech_da_doc" not in out


@pytest.mark.asyncio
async def test_lat_ke_tiep_khong_bat_dau_bang_dau_cau_mo_coi():
    """Gặp thật khi chạy end-to-end qua HTTP (14/08): lát thứ tư phát ra
    *". - Kéo hoàn toàn công tắc cửa sổ lên..."* — một dấu chấm mồ côi ở đầu.

    Sinh ra khi lát trước bị cắt ở ranh giới **mệnh đề** (giữa câu), nên phần còn lại
    mở đầu bằng chính dấu kết của câu đó. `.strip()` dọn khoảng trắng chứ không dọn
    dấu câu. Nghe thì thành một quãng vấp ngay đầu lượt.

    Mô hình chỉ số câu làm lỗi này **bất khả thi về cấu trúc**: mỗi lát là một hoặc
    vài câu **trọn vẹn**, nên nó luôn bắt đầu ở ranh giới câu. Test giữ lại để khoá
    đúng tính chất đó — nếu ai đó quay về cắt giữa câu, đây là chỗ báo.

    Không xoá dấu `-`: đó là bullet thật của sổ tay, bỏ nó đi là mất cấu trúc các bước.
    """
    nguon = "Câu một dài, có mệnh đề phụ ở giữa, rồi kết thúc. - Kéo công tắc lên và giữ hai giây."
    ke_hoach = doc_tiep(nguon, [0])

    assert not ke_hoach.spoken.startswith((".", ",", ";", ":", "!", "?"))
    assert ke_hoach.spoken.startswith("-")


def test_moi_cau_duoc_doc_dung_mot_lan_va_khong_sot_cau_nao():
    """Bất biến thay cho **hai** test cũ về trôi offset — cả hai đã hết lý do tồn tại.

    Mô hình cũ cộng ký tự, và phép cộng ấy lệch được: nối câu bằng dấu cách trong khi
    nguồn ngăn bằng xuống dòng, hoặc cộng nhầm độ dài lời mời. Cả hai lỗi đều đã xảy
    ra thật trong một ngày, và cả hai đều **không báo lỗi** — chỉ làm lát sau cắt vào
    giữa từ.

    Mô hình chỉ số câu không có phép cộng nào để mà lệch. Nên test không còn canh
    "offset có đúng không" mà canh thứ thật sự quan trọng: **đọc đủ, không lặp**.
    """
    from src.agents.nodes.speech_policy import _cau

    nguon = "\n".join(
        f"Câu số {i} của đoạn sổ tay này mô tả một bước thao tác cụ thể cho tài xế." for i in range(1, 14)
    )
    da_doc: list[int] = []
    for _ in range(30):
        ke_hoach = doc_tiep(nguon, da_doc)
        if not ke_hoach.spoken:
            break
        moi_them = [i for i in ke_hoach.chi_so if i not in da_doc]
        assert moi_them, "khong tien — lat nay khong doc them cau nao"
        for i in ke_hoach.chi_so:
            assert _cau(nguon)[i] in ke_hoach.spoken, "cau phat ra khong nguyen van"
        da_doc.extend(moi_them)
    else:
        raise AssertionError("khong bao gio doc het")

    assert sorted(da_doc) == list(range(13)), f"doc {sorted(da_doc)} — hut hoac lap"


# --- Bon lo hong do chinh phep do lo ra (14/08) -----------------------------


@pytest.mark.asyncio
async def test_doc_tiep_giu_citation_cua_doan_dang_doc():
    """Lỗ thủng nặng nhất: tài xế **nghe nguyên văn sổ tay mà không có nguồn**.

    `normalize` dọn `citations` mỗi lượt và nhánh đọc tiếp không đặt lại, nên
    `assistant_response_payload` phát `citations: []`. Rơi đúng vào những lượt chở
    phần lớn nội dung — p50 là 2 lượt, tức khoảng một nửa nội dung tới ở lượt sau.

    Với một hệ thống mà cả kỷ luật là "grounded answer + citation", đó là lỗ thủng
    ngay giữa.
    """
    cit = [{"citation_id": "cit_1", "section": "Cửa sổ điện", "page": 3}]
    dau = await compose_node({**_luot_dau(), "citations": cit})
    tiep = await compose_node(
        {
            "outcome": "not_control",
            "intent": "manual_continue",
            "query": "nói tiếp đi",
            "speech_source_text": dau["speech_source_text"],
            "speech_da_doc": dau["speech_da_doc"],
            "speech_citations": dau["speech_citations"],
        }
    )
    assert dau["speech_citations"] == cit
    assert tiep["citations"] == cit, "luot doc tiep mat nguon"


@pytest.mark.asyncio
async def test_doc_tiep_co_outcome_rieng_khong_muon_o_not_control():
    """`not_control` là ô nghĩa *"tôi chưa hiểu bạn muốn gì"*.

    Một lượt đọc tiếp **thành công** rơi vào ô đó thì `/metrics/summary` và màn hình
    engineer đếm mọi lượt S3 như một lượt không hiểu — càng nhiều S3 bảng càng sai.
    """
    out = await compose_node(
        {
            "outcome": "not_control",
            "intent": "manual_continue",
            "query": "nói tiếp đi",
            "speech_source_text": DOAN,
            "speech_da_doc": [],
        }
    )
    assert out["outcome"] == "grounded_continue"


@pytest.mark.asyncio
async def test_con_phan_du_bao_ra_ngoai_cho_ca_man_hinh_lan_fe():
    """Người nhìn màn hình phải biết còn nữa, và FE phải có cờ để dựng nút.

    Bản trước dán thêm một dấu `(còn tiếp — …)` vào riêng `display_text`, vì lời mời
    *"Bạn có muốn nghe tiếp nguyên văn không?"* chỉ nằm ở kênh nói. Từ 21/08 hai kênh
    dùng chung một chuỗi (yêu cầu nhóm — xem `test_mot_chuoi_cho_hai_kenh.py`), nên
    **lời mời tự nó** là thứ màn hình đọc được, và dấu ngoặc kia chỉ còn là bản sao
    thứ hai của cùng một thông tin.

    Vế `has_more_to_read` giữ nguyên và mới là vế quan trọng: nút của FE bám cờ này,
    không bám chuỗi.
    """
    out = await compose_node(
        {
            "outcome": "not_control",
            "intent": "manual_continue",
            "query": "nói tiếp đi",
            "speech_source_text": DOAN,
            "speech_da_doc": [],
        }
    )
    assert out["has_more_to_read"] is True
    assert "nghe tiếp" in out["display_text"].lower()
    assert out["display_text"] == out["speak_text"]

    het = await compose_node(
        {
            "outcome": "not_control",
            "intent": "manual_continue",
            "query": "nói tiếp đi",
            "speech_source_text": "",
            "speech_da_doc": [],
        }
    )
    assert het["has_more_to_read"] is False
    assert "nghe tiếp" not in het["display_text"].lower()


@pytest.mark.asyncio
async def test_luot_so_tay_dau_cung_bao_con_phan_du():
    """Nút "nghe tiếp" phải xuất hiện ngay từ lượt đầu, không đợi tới lượt thứ hai."""
    out = await compose_node(_luot_dau())
    assert out["has_more_to_read"] is True


# --- Loi moi phai di kem trang thai de doc tiep (bug tim thay khi test tay 15/08) ---

#: Rút gọn từ đoạn "Áp suất lốp" thật (`chunk_1148033_003`, trang 2): một câu chỉ nguồn
#: sạch số, rồi tới bảng mang bốn cột giá trị. Đây đúng là hình dạng làm nhánh `can_than`
#: chạy, và cũng đúng đoạn người dùng hỏi khi phát hiện bug.
BANG_AP_SUAT = (
    "Áp suất lốp\n"
    "Nhãn Thông tin về lốp và Tải trọng trên xe cho biết thông tin lốp nguyên bản ban đầu "
    "và áp suất lốp nguội chính xác. "
    "Áp suất lốp lạnh | Phía trước | 240 KPA,35 PSI, (SDI) 260 KPA,38 PSI, (CATL) | "
    "260 KPA,38 PSI, (SDI) 260 KPA,38 PSI, (CATL) | 420 KPA, 61 PSI, "
    "Phía Sau | 260 KPA,38 PSI, (SDI) 280 KPA,40 PSI, (CATL) | "
    "270 KPA,39 PSI, (SDI) 270 KPA,39 PSI, (CATL) "
    "Người lái xe có thể theo dõi áp suất lốp thông qua màn hình cảm ứng."
)


def _evidence_bien_the(text: str = BANG_AP_SUAT) -> Evidence:
    return Evidence(
        section="Áp suất lốp",
        page=2,
        text=text,
        chunk_id="chunk_1148033_003",
        score=0.9,
        is_table=True,
        has_variant_condition=True,
    )


def test_nhanh_bien_the_van_luu_duoc_cho_doc_tiep():
    """Bug thật, người dùng gặp khi test tay 15/08: hỏi áp suất lốp thì nghe câu chỉ
    nguồn kèm lời mời "Bạn có muốn nghe tiếp nguyên văn không?", nói "nghe tiếp" thì
    nhận lại "Tôi đã đọc hết phần này rồi."

    Nguyên nhân: nhánh `can_than` trả `remainder_chars > 0` — nên `cau_noi_hoan_chinh`
    gắn lời mời — nhưng để `chi_so` rỗng, và `_moc_doc_do` bỏ qua khi `chi_so` rỗng.
    Lời mời hứa một thứ không được lưu ở đâu cả.

    Sửa theo hướng nối lời mời vào trạng thái chứ không bỏ lời mời đi: chú thích của
    `_VARIANT_FALLBACK` nói rõ nó "mời nghe nguyên văn — để tài xế quyết định", và trích
    nguyên văn chính là hình thức ADR-015 đo được 0/40 gây hiểu lầm. Thứ bị cấm là tóm
    tắt, không phải đọc đủ.
    """
    ke_hoach = chon_cau_de_noi(_evidence_bien_the(), "áp suất lốp bao nhiêu")

    assert ke_hoach.reason in ("pointer", "variant_fallback")
    assert ke_hoach.remainder_chars > 0, "còn phần dư thì lời mời mới xuất hiện"
    assert _INVITE in cau_noi_hoan_chinh(ke_hoach), "tiền đề của bug: lời mời có mặt"

    tiep = doc_tiep(BANG_AP_SUAT, tuple(ke_hoach.chi_so))
    assert tiep.spoken, "hứa nghe tiếp thì phải còn thứ để đọc"


@pytest.mark.asyncio
async def test_compose_luu_trang_thai_cho_doan_bien_the():
    """Vế đầu bên trên kiểm `speech_policy`; vế này kiểm chỗ thật sự hỏng — `compose`.

    `_moc_doc_do` từng `return {}` khi `chi_so` rỗng. Guard đó có lý cho lượt điều khiển
    ("bật điều hoà" không được xoá chỗ đang đọc dở), nhưng ở đây nó gộp nhầm "chưa đọc
    câu nào của nguồn" với "không phải lượt sổ tay".
    """
    out = await compose_node(
        {
            "outcome": "grounded_answer",
            "query": "áp suất lốp khi lốp nguội là bao nhiêu",
            "evidence": [_evidence_bien_the()],
        }
    )

    assert out["speech_source_text"] == BANG_AP_SUAT
    assert out["has_more_to_read"] is True


def test_cau_chi_nguon_da_doc_khong_bi_doc_lai_o_luot_sau():
    """Nhánh `pointer` **có** đọc một câu của nguồn, nên câu ấy phải nằm trong `chi_so`.

    Bỏ trống thì lượt "nghe tiếp" đọc lại đúng câu tài xế vừa nghe — nghe như hệ thống
    bị kẹt, khó chịu hơn hẳn so với bỏ sót một câu.
    """
    ke_hoach = chon_cau_de_noi(_evidence_bien_the(), "áp suất lốp bao nhiêu")
    if ke_hoach.reason != "pointer":
        pytest.skip("đoạn này không đi nhánh pointer")

    tiep = doc_tiep(BANG_AP_SUAT, tuple(ke_hoach.chi_so))
    assert ke_hoach.spoken not in tiep.spoken
