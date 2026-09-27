# Issue #207 — `committed` trong `approval.intent.detected`, và mic của lượt phê duyệt

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đóng lỗ hổng #207(a) ở phía backend — nói cho IVI biết lượt phê duyệt bằng lời **đã chốt hay chưa**, và đọc đúng câu cho từng nhánh — rồi dọn phần trùng việc #207(b) ở frontend bằng cách port `choDuyet` vào bản #203 đã merge và mở lại mic khi lượt trả lời hỏng.

**Architecture:** Payload `approval.intent.detected` thêm một trường `committed: bool` do chính kết quả của `chot_da_xac_thuc` quyết định, không do nhánh mã nào tự khai. `_chot_neu_du_dieu_kien` đổi từ `bool` sang ba trạng thái, vì có ba câu thoại khác nhau phải đúng. Phía FE, `openVoice` nhận cờ `choDuyet` để mở mic **mà không tuyên bố một lượt mới**, và effect tự-mở-mic có thêm một mốc đếm để chạy lại sau khi lượt trả lời hỏng.

**Tech Stack:** FastAPI + Pydantic (Python 3.11.9), pytest/anyio; Next.js 16 + React 19, Vitest + Testing Library.

## Global Constraints

- Chạy Python qua `.\.venv\Scripts\python.exe` (phải in `3.11.9`); test backend đặt `MQTT_ENABLED=false`.
- `ruff check src/ tests/` và `ruff format src/ tests/` phải sạch; line-length 120.
- Test FE: `cd frontend; npm run test`. Không sửa `frontend/PROGRESS.md` bằng tay.
- Không sửa/xoá gì trong `.ai-log/`; không tự gọi `scripts/log_antigravity.py` hay `scripts/log_manual.py`; hook pre-push hỏng thì **báo**, không `--no-verify`.
- PR body dùng `Closes #207` (từ khoá tiếng Anh — "Đóng #207" GitHub không hiểu, đó là lý do 4 issue nằm mở sau khi PR đã merge).
- PR body/comment không chứa link `claude.ai/code/session_...`.
- Xưng "tôi – cậu" trong mọi văn bản đối thoại.
- Mọi thay đổi hợp đồng sự kiện phải kèm sửa `docs/api_spec.md` trong **cùng** PR.

---

## Những gì đã kiểm trước khi viết kế hoạch

Bốn điều dưới đây là kết quả đọc mã hôm nay, không phải trích lại issue:

1. **`committed` không suy ra được từ ý định.** `_chot_neu_du_dieu_kien` hiện trả `True` ngay cả khi `store.decide()` từ chối (bản ghi vừa hết hạn giữa lúc đọc và lúc chốt). Nên `committed` phải lấy từ `decided.status` chứ không từ nhánh `if`.
2. **Cửa sổ đua ấy hẹp nhưng thật.** `_pending_locked` **có** tự CAS `pending → expired` khi đọc, nên ca "hết hạn" thường rơi vào nhánh `pending is None` trước (đã có test `test_phe_duyet_het_han_thi_noi_dong_y_khong_thuc_thi`). Còn lại đúng một khe: hết hạn *sau* lúc `pending_for_session` trả về. Kế hoạch xử đúng khe ấy bằng cách rẽ về nhánh "không có gì đang chờ" đã có sẵn.
3. **`docs/api_spec.md` đang tự mâu thuẫn.** Dòng 287 đã sửa cho #191, nhưng dòng **591** (bảng allowlist: *"handoff only, never commits"*), dòng **660** (bảng sự kiện terminal: *"IVI then calls REST"*) và dòng **670** (*"IVI—not the intent turn—calls the REST decision endpoint"*) vẫn giữ luật cũ. Ba chỗ ấy phải sửa trong Task 3, nếu không thì spec nói ngược với chính nó ở cùng một tài liệu.
4. **Bản #203 đã merge KHÔNG thiếu điểm hẹn hai chiều.** Effect đọc `activeSpeechRef.current` **tại lúc effect chạy**, nên audio đọc xong trước khi `pendingApproval` được set vẫn rơi vào nhánh `shouldStartCloseTimerImmediately` → mở mic ngay. Toàn bộ bộ máy ref + hẹn giờ 1200 ms của branch chưa merge tồn tại chỉ vì branch ấy móc vào `onDriverEvent` thay vì effect. **Phần thật sự còn thiếu ở bản đã merge đúng bằng một cờ: `choDuyet`.**

---

## File Structure

| File | Trách nhiệm sau khi xong |
|---|---|
| `src/services/ivi_events.py` | `emit_approval_intent_handoff` nhận và phát thêm `committed` |
| `src/api/turns.py` | `_chot_neu_du_dieu_kien` trả ba trạng thái; `_phat_y_dinh_phe_duyet` chọn câu thoại và rẽ nhánh đua |
| `tests/test_api/test_approval_voice_intent.py` | Khoá 5 trường payload, khoá `committed` cho từng nhánh, khoá câu thoại |
| `docs/api_spec.md` | Bốn chỗ nói về voice-first confirmation nói cùng một luật |
| `frontend/src/components/ivi/DriverShellProvider.tsx` | `openVoice({choDuyet})`; effect tự-mở-mic chạy lại được sau lượt hỏng |
| `frontend/src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx` | Thêm ca `choDuyet` và ca mở lại mic |

---

# PHẦN A — Backend (PR 1, nhánh `feat/issue-207-committed-trong-approval-intent`)

Tách khỏi phần B vì hai lý do: nó là lỗ hổng an toàn (ưu tiên cao hơn), và PR FE của @danggiap123 chờ đúng trường này.

### Task 1: `_chot_neu_du_dieu_kien` trả ba trạng thái thay vì `bool`

**Files:**
- Modify: `src/api/turns.py` (`_chot_neu_du_dieu_kien`, `_phat_y_dinh_phe_duyet`, khối hằng `_LOI_*`)
- Test: `tests/test_api/test_approval_voice_intent.py`

**Interfaces:**
- Consumes: `chot_da_xac_thuc(approval_id, *, approve, schedule, khi_loi=None) -> ApprovalRecord | None` (`src/api/approvals.py`)
- Produces: `_chot_neu_du_dieu_kien(y_dinh, approval_id) -> Literal["da_chot", "can_ro_hon", "khong_chot_duoc"]`

- [ ] **Step 1: Tạo nhánh từ `develop`**

```bash
git fetch origin
git switch -c feat/issue-207-committed-trong-approval-intent origin/develop
```

- [ ] **Step 2: Viết test cho ba trạng thái, chạy để thấy nó đỏ**

Thêm vào cuối `tests/test_api/test_approval_voice_intent.py` (dùng lại helper `_auth`, `_owned_session`, `_xin_duyet`, `_noi`, `_bat_su_kien` đã có trong file):

```python
async def test_cum_ro_rang_thi_bao_da_chot(client):
    """`committed` là **kết quả của store**, không phải nhãn của nhánh mã.

    FE dùng đúng trường này để quyết định có gọi REST hay không (#207a), nên nó sai là
    tài xế mất một quyết định — hoặc được chốt hộ một việc S2.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        await _xin_duyet(client, headers, sid)
        await _noi(client, headers, sid, "Đồng ý")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["committed"] is True


async def test_tieng_tran_thi_bao_chua_chot_va_noi_ro_cach_tra_loi(client):
    """Tiếng trần không chốt (bất đối xứng của #191) — và câu thoại phải nói thật.

    `"Bạn đã đồng ý. Tôi sẽ thực hiện ngay."` ở nhánh này là một lời hứa suông: không
    có gì được chốt cả. Câu thay thế phải gọi tên đúng cụm cần nói, vì cụm ấy chính là
    thứ phân biệt hai nhánh.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        approval_id, _ = await _xin_duyet(client, headers, sid)
        r = await _noi(client, headers, sid, "Được")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["committed"] is False
    assert get_store().get(approval_id).status == "pending"
    noi = r.json()["data"]["response"]["speak_text"]
    assert "đồng ý" in noi.lower() and "nút" in noi.lower(), noi
    assert "sẽ thực hiện" not in noi.lower(), noi


async def test_tu_choi_tran_van_bao_da_chot(client):
    """Nửa kia của bất đối xứng: từ chối trần **có** chốt, nên `committed` phải là True.

    Nếu trường này bị cột vào `ro_rang_ve_phe_duyet` thay vì vào kết quả store thì ca
    này là ca lộ ra.
    """
    async with _bat_su_kien() as nhan:
        headers = await _auth(client)
        sid = _owned_session()
        approval_id, _ = await _xin_duyet(client, headers, sid)
        await _noi(client, headers, sid, "Thôi")

    intent = [e for e in nhan if e["type"] == "approval.intent.detected"]
    assert intent[0]["payload"]["committed"] is True
    assert get_store().get(approval_id).status == "rejected"
```

Chạy: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_approval_voice_intent.py -q -k "da_chot or chua_chot"`
Kỳ vọng: FAIL — `KeyError: 'committed'`.

- [ ] **Step 3: Đổi kiểu trả về của `_chot_neu_du_dieu_kien`**

Trong `src/api/turns.py`, thay thân hàm (giữ nguyên docstring hiện có, **thêm** khối "Ba kết cục" vào cuối docstring):

```python
async def _chot_neu_du_dieu_kien(y_dinh, approval_id: str) -> Literal["da_chot", "can_ro_hon", "khong_chot_duoc"]:
    """... (giữ nguyên docstring cũ) ...

    ## Ba kết cục, vì có ba câu thoại phải đúng

    | | khi nào | tài xế nghe gì |
    |---|---|---|
    | `da_chot` | store đã chuyển sang `approved`/`rejected` | "Tôi sẽ thực hiện ngay." |
    | `can_ro_hon` | tiếng trần — **cố ý** không chốt | "Bạn nói 'đồng ý' hoặc chạm nút…" |
    | `khong_chot_duoc` | đã gọi store nhưng nó từ chối (hết hạn/vô hiệu trong cửa sổ đua) | "Hiện không có yêu cầu nào đang chờ…" |

    Trả `bool` được đúng tới lúc `committed` ra tới IVI: `True` cũ nói "đã gọi chốt",
    còn IVI cần biết "đã chốt". Hai câu ấy khác nhau đúng ở nhánh thứ ba.
    """
    from src.api.approvals import chot_da_xac_thuc

    if y_dinh.quyet_dinh == "approve" and not y_dinh.ro_rang_ve_phe_duyet:
        return "can_ro_hon"
    decided = await chot_da_xac_thuc(
        approval_id,
        approve=y_dinh.quyet_dinh == "approve",
        schedule=_chay_nen,
    )
    # `consumed` cũng tính là đã chốt: lệnh chạy xong trước khi ta đọc lại bản ghi thì
    # quyết định của tài xế vẫn đã được ghi nhận — IVI không có việc gì phải gọi REST.
    mong_doi = ("approved", "consumed") if y_dinh.quyet_dinh == "approve" else ("rejected",)
    return "da_chot" if decided is not None and decided.status in mong_doi else "khong_chot_duoc"
```

Thêm `Literal` vào import `typing` ở đầu file nếu chưa có.

- [ ] **Step 4: Thêm câu thoại cho nhánh chưa chốt**

Cạnh khối `_LOI_DA_NHAN` trong `src/api/turns.py`:

```python
#: Nhánh tiếng trần: **chưa** chốt gì cả. Gọi tên đúng cụm cần nói, vì cụm ấy là thứ
#: duy nhất phân biệt hai nhánh — nói "bạn xác nhận lại giúp tôi" thì tài xế lặp lại
#: đúng tiếng trần vừa rồi và kẹt vòng lặp.
_LOI_CAN_NOI_RO = 'Bạn nói "đồng ý" hoặc chạm nút xác nhận giúp tôi.'
```

- [ ] **Step 5: Nối vào `_phat_y_dinh_phe_duyet`**

Thay ba dòng cuối của khối chốt (`await _chot_neu_du_dieu_kien(...)` → `noi = _LOI_DA_NHAN[...]`) bằng:

```python
    ket = await _chot_neu_du_dieu_kien(y_dinh, pending.approval_id)
    if ket == "khong_chot_duoc":
        # Cửa sổ đua: `pending_for_session` còn thấy `pending`, tới lúc `decide()` thì
        # bản ghi đã hết hạn (hoặc bị vô hiệu). Đúng nghĩa "không còn gì chờ xác nhận"
        # nên đi thẳng nhánh ấy — phát một handoff cho phê duyệt đã chết thì IVI làm
        # nổi một cái nút bấm vào sẽ lỗi.
        await emit_approval_intent_not_pending(bus, session_id, turn_id, trace_id, message=_LOI_KHONG_CHO)
        return "canceled", _LOI_KHONG_CHO
    noi = _LOI_DA_NHAN[y_dinh.quyet_dinh] if ket == "da_chot" else _LOI_CAN_NOI_RO
```

Và ở lời gọi `emit_approval_intent_handoff(...)` thêm đối số `committed=ket == "da_chot"`.

- [ ] **Step 6: Thêm `committed` vào emitter**

`src/services/ivi_events.py`, `emit_approval_intent_handoff`: thêm tham số keyword-only `committed: bool` (đặt trước `speak_text`), thêm `"committed": committed` vào dict payload, và sửa docstring — đoạn *"**Không** gọi decision service ở đây"* nay chỉ còn đúng với **hàm này**, không còn đúng với **lượt**:

```python
    """Nhánh thành công: `approval.intent.detected` → `assistant.response` → `turn.completed`.

    Hàm này vẫn không tự chốt gì — nhưng từ #191, **lượt** thì có thể đã chốt trước khi
    gọi tới đây. `committed` nói ra sự khác biệt ấy, và nó là trường DUY NHẤT IVI có để
    biết: hai nhánh giống hệt nhau ở cả bốn trường còn lại. Thiếu nó thì IVI phải đoán,
    và cách đoán rẻ nhất — luôn gọi REST — chính là đường vòng qua bất đối xứng của
    #191 (issue #207a).
    """
```

- [ ] **Step 7: Sửa test hợp đồng 4 trường thành 5 trường**

Trong `tests/test_api/test_approval_voice_intent.py`, đổi tên `test_su_kien_intent_dung_bon_truong_cua_hop_dong` → `test_su_kien_intent_dung_nam_truong_cua_hop_dong`, thêm `"committed"` vào `set(...)` và thêm dòng khoá kiểu:

```python
    assert intent[0]["payload"]["committed"] is True
```

Giữ nguyên phép so **bằng tập hợp** (`==`, không phải `<=`): nó là thứ bắt được mọi lần payload phình ra ngoài spec.

- [ ] **Step 8: Chạy toàn bộ file test và suite backend**

```powershell
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_approval_voice_intent.py -q
$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/ -q
```
Kỳ vọng: PASS toàn bộ; số skip là thuộc tính của máy (xem CLAUDE.md), kiểm bằng `-rs` nếu khác 17.

- [ ] **Step 9: Lint + commit**

```bash
ruff check src/ tests/ && ruff format src/ tests/
git add src/api/turns.py src/services/ivi_events.py tests/test_api/test_approval_voice_intent.py
git commit -m "feat(hitl): approval.intent.detected nói rõ đã chốt hay chưa"
```

---

### Task 2: Ca đua "hết hạn giữa chừng" có test riêng

Tách khỏi Task 1 vì nó cần monkeypatch và một người review có thể bác riêng nó mà vẫn nhận phần trên.

**Files:**
- Test: `tests/test_api/test_approval_voice_intent.py`

- [ ] **Step 1: Viết test, chạy để thấy đỏ nếu Step 5 của Task 1 bị bỏ**

```python
async def test_het_han_giua_luc_chot_thi_ra_nhanh_khong_con_gi_cho(client, monkeypatch):
    """Khe đua duy nhất còn lại sau khi `_pending_locked` đã tự CAS `pending -> expired`.

    Dựng bằng monkeypatch chứ không bằng đồng hồ: khe này rộng vài micro giây, và một
    test phải chờ đúng lúc để đỏ là một test sẽ xanh vì sai lý do.
    """
    from src.api import approvals as mod_approvals

    async def chot_gia(approval_id, *, approve, schedule, khi_loi=None):
        return get_store().get(approval_id).model_copy(update={"status": "expired"})

    monkeypatch.setattr(mod_approvals, "chot_da_xac_thuc", chot_gia)

    headers = await _auth(client)
    sid = _owned_session()
    await _xin_duyet(client, headers, sid)

    r = await _noi(client, headers, sid, "Đồng ý")

    data = r.json()["data"]
    assert data["status"] == "canceled"
    # Không được hứa "sẽ thực hiện ngay" cho một phê duyệt đã chết.
    assert "thực hiện" not in data["response"]["speak_text"].lower()
```

Chạy: `$env:MQTT_ENABLED="false"; .\.venv\Scripts\python.exe -m pytest tests/test_api/test_approval_voice_intent.py -q -k het_han_giua`
Kỳ vọng: PASS (Task 1 Step 5 đã làm phần mã).

- [ ] **Step 2: Commit**

```bash
git add tests/test_api/test_approval_voice_intent.py
git commit -m "test(hitl): khe đua hết hạn giữa lúc chốt rẽ về nhánh không-còn-gì-chờ"
```

---

### Task 3: `docs/api_spec.md` nói cùng một luật ở cả bốn chỗ

**Files:**
- Modify: `docs/api_spec.md` (dòng ~287, ~591, ~660, ~670)

- [ ] **Step 1: Dòng 591 — hàng allowlist**

Thay đuôi `; handoff only, never commits` bằng:

```
; `committed:boolean` — true when this turn already committed the decision server-side (explicit confirmation phrase, or any rejection phrase), false when the event is handoff only and the IVI must obtain the decision. The other four fields are identical in both cases; `committed` is the only discriminator
```

- [ ] **Step 2: Dòng 660 — hàng bảng sự kiện terminal**

`IVI then calls REST` → `IVI calls REST only when committed=false`.

- [ ] **Step 3: Dòng 670 — câu tổng kết**

Thay cả câu bằng:

```
Voice approval intent is a separate accepted voice turn. It emits typed `approval.intent.detected` carrying `committed`; when `committed` is false the IVI—not the intent turn—calls the REST decision endpoint, and when it is true the IVI must not call it again.
```

- [ ] **Step 4: Dòng ~287 — bổ sung hai câu thoại vào đoạn #191**

Thêm vào cuối gạch đầu dòng thứ ba (nhánh tiếng trần): `The spoken reply on this branch names the phrase to say instead of promising execution.`

- [ ] **Step 5: Kiểm chéo bằng grep rằng không còn chỗ nào giữ luật cũ**

```bash
grep -n "never commits\|IVI then calls REST\|not the intent turn" docs/api_spec.md
```
Kỳ vọng: chỉ còn dòng 670 đã viết lại.

- [ ] **Step 6: Commit + mở PR**

```bash
git add docs/api_spec.md
git commit -m "docs(api-spec): bốn chỗ nói về xác nhận bằng lời nói cùng một luật"
git push -u origin feat/issue-207-committed-trong-approval-intent
```

PR body phải có: `Closes #207` **không** dùng (issue còn phần b) — dùng `Refs #207` và ghi rõ đây là phần BE của (a). Ping @danggiap123 rằng trường `committed` đã có trên `develop` để PR FE dò tính năng chạy được nhánh `true`/`false`.

---

# PHẦN B — Frontend (PR 2, nhánh `fix/issue-207-mic-cho-duyet-va-mo-lai`)

**Quyết định đề xuất cho (b): port `choDuyet`, đóng `feat/191-mic-tu-mo-khi-cho-duyet` mà không merge.**

Lý do — bản đã merge (#203) **không** thiếu điểm hẹn hai chiều (xem mục "đã kiểm" số 4), nên toàn bộ phần ref + hẹn giờ 1200 ms của branch chưa merge là mã chỉ tồn tại vì kiến trúc khác, không phải vì tính năng. Rebase là mang về ~90 dòng để rồi xoá gần hết. Port là một cờ, và giữ được phần test của branch cũ.

### Task 4: `openVoice({ choDuyet: true })` — mở mic mà không tuyên bố lượt mới

**Files:**
- Modify: `frontend/src/components/ivi/DriverShellProvider.tsx`
- Test: `frontend/src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx`

**Interfaces:**
- Produces: `openVoice(tuyChon?: { choDuyet?: boolean }) => void`

- [ ] **Step 1: Nhánh mới từ `develop`**

```bash
git switch -c fix/issue-207-mic-cho-duyet-va-mo-lai origin/develop
```

- [ ] **Step 2: Viết hai test, chạy để thấy đỏ**

Thêm vào `DriverShellProvider.autoListenApproval.test.tsx` (theo đúng mẫu dựng harness đã có trong file — `it(...)` hiện tại là bản tham chiếu cho cách bắn event và cách chờ recorder):

```tsx
it("mic tự mở cho lượt duyệt KHÔNG đẩy câu trả lời của lượt gốc vào lịch sử", async () => {
  // `openVoice()` trần dọn `lastTurn` vào `turnHistory` — nó khai báo "một lượt MỚI".
  // Câu hỏi duyệt LÀ lượt hiện tại; đẩy nó đi là xoá đúng thứ tài xế đang trả lời.
  await guiSuKien({ type: "assistant.response", ...traLoiLenhGoc });
  await guiSuKien({ type: "approval.required", ...phêDuyệt });
  await vi.waitFor(() => expect(manHinh.getByTestId("last-turn")).toHaveTextContent(traLoiLenhGoc.result.text));
});

it("mic tự mở cho lượt duyệt KHÔNG vô hiệu hoá câu trả lời tới sau khi duyệt xong", async () => {
  // `openVoice()` trần tăng `turnGenerationRef`. `revealPendingResponse` có kiểm
  // generation, nên câu trả lời của lượt lệnh gốc (tới SAU khi duyệt) bị bỏ im lặng —
  // tài xế duyệt xong, xe làm, và màn hình không nói gì.
  await guiSuKien({ type: "approval.required", ...phêDuyệt });
  await guiSuKien({ type: "turn.completed", ...luotYDinh });
  await guiSuKien({ type: "assistant.response", ...traLoiSauKhiDuyet });
  await vi.waitFor(() => expect(manHinh.getByTestId("last-turn")).toHaveTextContent(traLoiSauKhiDuyet.result.text));
});
```

Chạy: `cd frontend; npx vitest run src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx`
Kỳ vọng: FAIL cả hai.

- [ ] **Step 3: Thêm cờ vào `openVoice`**

Trong `DriverShellProvider.tsx`, đổi chữ ký và bọc ba khối bằng `if (!choDuyet)` — đúng ba khối, không hơn:

```tsx
  //: Mở mic cho lượt phê duyệt **khác** mở mic bình thường ở ba chỗ, và cả ba đều là
  //: "đừng bắt đầu lượt mới": không tăng `turnGenerationRef` (tăng là vô hiệu hoá chính
  //: hộp thoại duyệt vừa hiện và bỏ luôn câu trả lời tới sau khi duyệt), không xoá
  //: `pendingResponseRef`, không dọn `lastTurn` (câu hỏi duyệt LÀ lượt hiện tại).
  //: Cũng không `stopSpeech()` — ta chỉ mở mic SAU khi audio đọc xong, nên không có gì
  //: để ngắt, và ngắt ở đây là ngắt chính câu hỏi vừa đọc nếu thứ tự đổi.
  const openVoice = useCallback((tuyChon?: { choDuyet?: boolean }) => {
    const choDuyet = tuyChon?.choDuyet === true;
    if (voiceStartingRef.current || recorderRef.current) return;
    voiceStartingRef.current = true;
    if (!choDuyet) {
      turnGenerationRef.current += 1;
      pendingResponseRef.current = null;
      stopSpeech();
    }
    setVoiceOpen(true);
    setTranscript(null);
    transcriptShownAtRef.current = null;
    if (!choDuyet) {
      setLastTurn((prev) => {
        if (prev?.vivi) setTurnHistory((history) => [...history, prev.vivi as string].slice(-MAX_TURN_HISTORY));
        return null;
      });
    }
    // ... phần còn lại giữ nguyên
```

- [ ] **Step 4: Sửa effect tự-mở-mic gọi qua cờ**

**Đây là chỗ dễ hỏng im lặng:** effect hiện truyền thẳng `openVoice` làm listener, nên đối số nó nhận là `Event` của DOM, và `tuyChon?.choDuyet` sẽ là `undefined` → chạy nhánh lượt-mới. Phải bọc, và phải **cùng một tham chiếu** cho `add`/`removeEventListener`:

```tsx
  useEffect(() => {
    if (!pendingApproval) return;
    const moMicChoDuyet = () => openVoice({ choDuyet: true });
    const audio = activeSpeechRef.current;
    if (audio === null || shouldStartCloseTimerImmediately(audio)) {
      moMicChoDuyet();
      return;
    }
    audio.addEventListener("ended", moMicChoDuyet);
    audio.addEventListener("error", moMicChoDuyet);
    return () => {
      audio.removeEventListener("ended", moMicChoDuyet);
      audio.removeEventListener("error", moMicChoDuyet);
    };
  }, [pendingApproval, openVoice]);
```

- [ ] **Step 5: Chạy test FE**

```bash
cd frontend && npx vitest run src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx
```
Kỳ vọng: PASS. Sau đó `npm run test` toàn bộ (mốc hiện tại 212/212).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/ivi/DriverShellProvider.tsx frontend/src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx
git commit -m "fix(fe): mic của lượt duyệt không được tuyên bố một lượt mới"
```

- [ ] **Step 7: Đóng branch trùng việc**

```bash
git push origin --delete feat/191-mic-tu-mo-khi-cho-duyet
```
Trước khi xoá, ghi vào #207 một comment nói rõ: đã port `choDuyet`, phần còn lại của branch là mã của kiến trúc cũ, và hai ca test đã được mang sang (Step 2).

---

### Task 5: Mở lại mic khi lượt trả lời phê duyệt hỏng

**Files:**
- Modify: `frontend/src/components/ivi/DriverShellProvider.tsx`
- Test: `frontend/src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx`

**Interfaces:**
- Produces: state `lanMoLaiMic: number` nằm trong deps của effect tự-mở-mic

- [ ] **Step 1: Viết ba test, chạy để thấy đỏ**

```tsx
it("câu mơ hồ thì mic mở lại — lời mời nói lại phải nói vào một cái mic đang mở", async () => {
  // `pendingApproval` KHÔNG đổi tham chiếu ở nhánh này (cố ý giữ hộp thoại), nên effect
  // không chạy lại và mic đã tắt. Backend mời "Bạn nói lại giúp tôi nhé" vào chỗ trống.
  await guiSuKien({ type: "approval.required", ...phêDuyệt });
  await dungGhiVaGui();
  await guiSuKien({ type: "error", code: "APPROVAL_INTENT_AMBIGUOUS", message: "..." });
  await guiSuKien({ type: "turn.failed", code: "APPROVAL_INTENT_AMBIGUOUS" });
  await vi.waitFor(() => expect(startWavRecording).toHaveBeenCalledTimes(2));
});

it("bản ghi không vượt ngưỡng tiếng nói thì mic mở lại", async () => {
  // Không gửi lên BE ⇒ không có sự kiện nào từ server để kích effect. Nếu chỉ nghe
  // `turn.failed` thì ca này rơi vào khoảng trống.
  hadSpeech.mockReturnValue(false);
  await guiSuKien({ type: "approval.required", ...phêDuyệt });
  await dungGhiVaGui();
  await vi.waitFor(() => expect(startWavRecording).toHaveBeenCalledTimes(2));
});

it("mở lại tối đa 2 lần rồi trả về cho nút bấm", async () => {
  // Không có trần thì mic-im-lặng tự nuôi chính nó: mở → không có tiếng → mở lại →…
  // cho tới lúc phê duyệt hết hạn, và tài xế không hiểu vì sao mic cứ bật.
  hadSpeech.mockReturnValue(false);
  await guiSuKien({ type: "approval.required", ...phêDuyệt });
  for (let i = 0; i < 4; i += 1) await dungGhiVaGui();
  expect(startWavRecording).toHaveBeenCalledTimes(3); // 1 lần đầu + 2 lần mở lại
});
```

- [ ] **Step 2: Thêm mốc đếm và trần**

Cạnh `MAX_RECORDING_MS` trong `DriverShellProvider.tsx`:

```tsx
/** Mở lại mic tối đa mấy lần cho MỘT phê duyệt trước khi trả về cho nút bấm.
 *
 * Có trần vì vòng lặp im lặng tự nuôi chính nó: mic mở, không ai nói, `hadSpeech()`
 * false, mở lại. Hai lần là đủ cho ca thật (nói lí nhí, hoặc nói lẫn lộn một lần), còn
 * quá hai lần thì vấn đề không phải cách nói và hộp thoại vẫn còn đó để chạm.
 */
const MAX_MO_LAI_MIC = 2;
```

Trong component:

```tsx
  // Đổi giá trị là tín hiệu DUY NHẤT để effect tự-mở-mic chạy lại: `pendingApproval`
  // cố ý không đổi tham chiếu khi lượt trả lời hỏng (xem nhánh `moHoConCho`).
  const [lanMoLaiMic, setLanMoLaiMic] = useState(0);
  const moLaiMicChoRef = useRef<string | null>(null);

  const xinMoLaiMic = useCallback(() => {
    const approval = pendingApprovalRef.current;
    if (!approval) return;
    // Trần đếm theo TỪNG phê duyệt, không theo phiên.
    if (moLaiMicChoRef.current !== approval.approvalId) {
      moLaiMicChoRef.current = approval.approvalId;
      soLanMoLaiRef.current = 0;
    }
    if (soLanMoLaiRef.current >= MAX_MO_LAI_MIC) return;
    soLanMoLaiRef.current += 1;
    setLanMoLaiMic((n) => n + 1);
  }, []);
```

(kèm `const soLanMoLaiRef = useRef(0);`)

- [ ] **Step 3: Gọi `xinMoLaiMic` ở đúng hai chỗ**

1. Trong `stopVoiceAndSend`, ngay trong nhánh `if (!recorder.hadSpeech())`, sau `setToast(...)`:

```tsx
      xinMoLaiMic(); // còn phê duyệt đang chờ thì hỏi lại bằng mic, không bắt chạm nút
```

2. Trong `onDriverEvent`, nhánh `turn.failed`, trong đúng khối `if (moHoConCho)`:

```tsx
          if (moHoConCho) xinMoLaiMic();
```

- [ ] **Step 4: Đưa mốc vào deps của effect**

```tsx
  }, [pendingApproval, openVoice, lanMoLaiMic]);
```

- [ ] **Step 5: Chạy test**

```bash
cd frontend && npx vitest run src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx && npm run test && npm run lint
```

- [ ] **Step 6: Commit + PR**

```bash
git add frontend/src/components/ivi/DriverShellProvider.tsx frontend/src/components/ivi/DriverShellProvider.autoListenApproval.test.tsx
git commit -m "fix(fe): mở lại mic khi lượt trả lời phê duyệt hỏng, có trần 2 lần"
git push -u origin fix/issue-207-mic-cho-duyet-va-mo-lai
```

PR body: `Closes #207` (đóng nốt phần còn lại — với điều kiện PR phần A đã merge; nếu chưa thì `Refs #207` và đóng tay sau).

---

## Kiểm bằng tay trước khi xin merge (không thay thế test)

Chạy backend `.\.venv\Scripts\python.exe -m src.serve` + `cd frontend; npm run dev` với ba cờ mock đặt `false`, rồi:

1. Ra lệnh S2 bằng giọng ("hạ kính xuống"), nghe câu hỏi duyệt đọc xong → mic **tự mở**.
2. Nói **"ừ"** → nghe *"Bạn nói đồng ý hoặc chạm nút xác nhận giúp tôi."*, kính **không** hạ, `committed=false` trong tab Network/WS.
3. Nói **"đồng ý"** → kính hạ, `committed=true`, và FE (bản của @danggiap123) **không** gọi `POST /approvals/.../decision`.
4. Nói **"đồng ý nhưng hủy"** → toast mời nói lại, mic mở lại, hộp thoại còn nguyên.
5. Im lặng ba lần liên tiếp → mic thôi mở lại ở lần thứ ba, hộp thoại vẫn chạm được.

Bước 2 và 3 kiểm luôn được rằng Piper đọc dấu ngoặc kép trong `_LOI_CAN_NOI_RO` không thành tiếng lạ; nếu có thì bỏ ngoặc ở `speak_text` và giữ ở `display_text`.

---

## Kết quả thực thi (20/08) — ba chỗ kế hoạch nói sai

Ghi lại ở đây thay vì sửa đè lên phần trên: kế hoạch được duyệt theo đúng chữ của nó, nên phần lệch phải đọc được.

**1. `choDuyet` không cứu `turnGenerationRef` như kế hoạch nói.** Tôi dựng ca tái hiện và không dựng được: `revealPendingResponse(generation)` chụp `turnGenerationRef.current` **tại lúc sự kiện tới**, tức là *sau* cú tăng của mic tự mở — nên câu trả lời của lượt gốc không bị bỏ. Ý số 2 của issue #207(b) (bản chưa merge kỹ hơn ở chỗ này) là **không đúng ở phần lý do**.

**Nhưng cái hại thì có thật, chỉ nằm chỗ khác:** `openVoice()` trần dọn `lastTurn` về `null`, mà lệnh S2 **gõ bằng chữ** đặt `lastTurn = {user: "Mở kính bên lái 30%", vivi: null}`. Tới lúc câu trả lời tới, `setLastTurn` đọc `prev?.user ?? ""` và thẻ kết quả hiện ra với ô "bạn đã nói" trống trơn. Test đầu tiên của file mới là đúng ca ấy, và nó đỏ trên `develop`.

**2. Kế hoạch bỏ sót một lỗ nặng hơn cả hai lỗ nó liệt kê.** `shouldStartCloseTimerImmediately` trả `false` cho audio **bị autoplay policy chặn** (element vẫn nằm trong ref: `ended=false`, `error=null`), nên effect của #203 đăng ký nghe một `ended` **không bao giờ phát** — mic không mở, không có gì báo. Chú thích của #203 ghi "bị chặn autoplay đều phải ghi ngay" nhưng mã không làm được điều đó. Đây mới là giá trị thật của branch chưa merge: hẹn giờ `CHO_AM_THANH_MS`. Bản port thêm một cổng branch cũ không có — hết giờ vẫn hỏi `paused`, vì "đang đọc thật" và "bị chặn" nhìn từ effect giống hệt nhau và chỉ khác đúng cờ ấy.

**3. `openVoice({choDuyet})` đổi thành `batDauNghe(choDuyet)`.** Chữ ký công khai phải giữ `() => void`: `Dock.tsx` và `HomeView.tsx` truyền thẳng `openVoice` vào `onClick`, nên một tham số tuỳ chọn sẽ nhận `MouseEvent` làm đối số — im lặng chạy nhánh sai.

Phần A không lệch. `2008 passed, 17 skipped` (BE), `219 passed` (FE), `tsc --noEmit` sạch.

## Ba chỗ cần cậu chốt trước khi tôi làm

1. **(b): port hay rebase?** Tôi đề xuất **port + xoá branch** (lý do ở đầu Phần B). Nếu cậu muốn giữ branch thì Task 4 đổi thành một cuộc rebase và sẽ tốn thêm một vòng đọc lại toàn bộ 98 dòng.
2. **Task 2 (khe đua hết hạn)** có thừa không? Nó thêm ~15 dòng cho một cửa sổ vài micro giây. Tôi nghiêng về **giữ**, vì phần mã của nó gần như bằng 0 (chỉ là một nhánh `if` đã cần có để `committed` không nói dối), phần thêm chỉ là test.
3. **Nhánh mơ hồ hiện KHÔNG có tiếng.** `emit_approval_intent_ambiguous` chỉ phát `error` + `turn.failed`, mà `error` không đi kèm TTS — nên *"Tôi chưa rõ bạn đồng ý hay không"* chỉ hiện chữ. Sau Task 5 thì mic sẽ mở lại **trong im lặng**, và đó là một cái mic mở không lời giải thích. Sửa được bằng cách cho nhánh ấy đi qua `assistant.response`, nhưng thế là đổi hợp đồng ở `api_spec.md:661` (bảng đang chốt nhánh mơ hồ đúng hai sự kiện). Tôi đề xuất **tách issue riêng**, không nhét vào #207.
