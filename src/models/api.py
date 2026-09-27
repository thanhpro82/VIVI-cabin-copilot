"""Vỏ response chung của REST API.

`docs/api_spec.md` mục "Conventions and common HTTP envelopes" chốt đúng hai hình
dạng: envelope thành công `{data, meta, trace_id, schema_version}` và envelope lỗi
`{error, meta, trace_id, schema_version}`. Cả hai đều **top-level** — không có
tầng bọc nào ở ngoài.

Vì sao khai thành model thay vì trả `dict` trần: `response_model` của FastAPI là
thứ sinh ra OpenAPI ở `/docs`, và `/docs` chính là hợp đồng mà người làm frontend
đọc. Trả `dict` trần thì `/docs` không mô tả gì và hợp đồng phải truyền miệng.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.vehicle import SCHEMA_VERSION, VehicleState


class Meta(BaseModel):
    """`meta` của mọi response. P0 chỉ có `request_id`."""

    model_config = ConfigDict(extra="forbid")

    request_id: str


class ApiErrorBody(BaseModel):
    """Thân `error`. `details` để rỗng chứ không bỏ đi — client đọc `details`
    không điều kiện thì `{}` an toàn hơn `None`."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ApiErrorBody
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class VehicleStateData(BaseModel):
    """`data` của `GET /api/v1/vehicle/state`.

    Tên khoá là `vehicle_state`, và bên trong là `VehicleState` **nguyên vẹn** —
    `api_spec.md:306` chốt `state_version` không bị làm phẳng hay đổi tên.
    """

    model_config = ConfigDict(extra="forbid")

    vehicle_state: VehicleState


class VehicleStateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: VehicleStateData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class LoginUser(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    role: Literal["driver", "engineer"]
    display_name: str


class LoginData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_at: str
    user: LoginUser


class LoginEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: LoginData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class PoolXe(BaseModel):
    """Sức chứa pool xe ảo — để client nói cho người dùng biết trần là bao nhiêu.

    `free` là **dẫn xuất**, không phải một con số thứ ba: server tính sẵn để client khỏi
    trừ (và khỏi trừ sai). Nguồn duy nhất là `VehiclePool.suc_chua()`.
    """

    model_config = ConfigDict(extra="forbid")

    total: int
    in_use: int
    free: int


class SessionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    #: Xe được cấp cho phiên. Khi hết pool, phiên vẫn có `vehicle_id` (bản ghi trong
    #: SQLite đòi NOT NULL) nhưng **không có quyền lái** — `can_drive` mới là thứ quyết
    #: định. Client phải đọc `can_drive`, đừng suy từ sự có mặt của `vehicle_id`.
    vehicle_id: str
    status: str
    started_at: str
    #: `False` = chế độ chỉ xem: vẫn tra sổ tay và đọc trạng thái xe được, nhưng mọi
    #: lệnh điều khiển bị từ chối. Thêm 2026-08-23 cùng pool xe; luôn `True` khi pool
    #: không cấp phát, nên client cũ không đổi hành vi.
    can_drive: bool = True
    pool: PoolXe | None = None


class SessionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: SessionData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class ActionPlanStep(BaseModel):
    """Mirrors `src.agents.contracts.PlanStep`'s public fields exactly."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    ordinal: int
    tool: str
    args: dict[str, Any]
    safety_level: Literal["S0", "S1", "S2", "S3"]
    depends_on: list[str]


class ActionPlanData(BaseModel):
    """Mirrors `src.agents.contracts.ActionPlan`'s public fields exactly —
    docs/api_spec.md:174 requires exactly this field set, no more, no less."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    plan_id: str
    session_id: str
    vehicle_id: str
    vehicle_state_version: int
    steps: list[ActionPlanStep]
    requires_approval: bool


class TurnResponseData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_text: str
    speak_text: str
    citations: list[dict[str, Any]]
    outcomes: list[dict[str, Any]]


class RoutinePreviewStepData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    action: str
    description: str


class RoutinePreviewData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    routine_id: str
    routine_name: str
    steps: list[RoutinePreviewStepData]


class PendingApprovalData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    expires_at: str


class RoutineSetupRequiredData(BaseModel):
    """Issue #385: voice-run thiếu địa điểm bắt buộc.

    Chỉ xuất hiện khi `routine_ma_loi == "chua_dat_dia_diem"` — ba lý do từ chối còn
    lại (`routine_da_tat`, `dang_chay_routine_khac`, `routine_khong_ton_tai`) không có
    màn setup nào để đưa tài xế sang. `thieu` dùng nhãn máy đọc được (`"home"`/
    `"office"`), không phải câu tiếng Việt — client rẽ nhánh bằng đây, không so khớp chữ.
    """

    model_config = ConfigDict(extra="forbid")

    routine_id: str
    ma_loi: str
    thieu: list[str]


class TextTurnData(BaseModel):
    """`action_plan` is null for non-control outcomes (manual/RAG lookup, clarify,
    etc. have no ActionPlan). `pending_approval` is only set when `status ==
    "waiting_approval"` — see design doc mục "POST /turns/text"."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    turn_id: str
    status: str
    action_plan: ActionPlanData | None
    response: TurnResponseData
    routine_preview: RoutinePreviewData | None = None
    routine_setup_required: RoutineSetupRequiredData | None = None
    pending_approval: PendingApprovalData | None = None


class TextTurnEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: TextTurnData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class CitationData(BaseModel):
    """`data` của `GET /api/v1/citations/{citation_id}`.

    Đúng tám field của `docs/api_spec.md:328`; `extra="forbid"` để field lạ bị từ chối
    ngay ở biên thay vì lọt ra hợp đồng.
    """

    model_config = ConfigDict(extra="forbid")

    citation_id: str
    turn_id: str
    document_title: str
    section: str
    page: int
    chunk_id: str
    excerpt: str
    retrieval_score: float


class CitationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: CitationData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class VehicleProfileData(BaseModel):
    """`data` của `GET/PUT /api/v1/vehicle/profile` (issue #123).

    `trim`/`battery` nullable, và `null` **có nghĩa**: chưa khai báo cấu hình. Client
    không được coi `null` là "mặc định" — không có mặc định nào, xem
    `src/services/vehicle_profile.py`.

    `is_complete` là field dẫn xuất, cố ý trả sẵn thay vì bắt client tự suy
    `trim != null && battery != null`. Nó là **cổng fail-closed** của cả nhánh áp
    suất lốp: điều kiện đó phải do backend quyết, đúng như task #123 chốt "backend là
    nơi duy nhất quyết định câu trả lời". Để client tự tính là mời mỗi client tự nghĩ
    ra một luật riêng.
    """

    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    trim: Literal["eco", "plus"] | None
    battery: Literal["sdi", "catl"] | None
    is_complete: bool
    updated_at: str | None


class VehicleProfileEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: VehicleProfileData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class TrangBiItem(BaseModel):
    """Một mục danh mục trang bị, cho client dựng màn khai báo.

    Trả cả `nhom` lẫn `loai_tru` vì UI cần cả hai: `nhom` để gom 65 mục thành mười
    nhóm đọc được, `loai_tru` để không cho tick hai ô mà server sẽ từ chối — thà chặn
    ở đầu ngón tay còn hơn ở 422.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    ten: str
    nhom: str
    loai_tru: list[str]


class VehicleOptionsData(BaseModel):
    """`data` của `GET/PUT /api/v1/vehicle/profile/options`.

    `da_khai` chỉ chứa những trang bị **đã khai báo**. Khoá vắng mặt nghĩa là *chưa
    biết*, và đó là trạng thái mặc định hợp lệ của mọi trang bị — không phải dữ liệu
    khuyết cần vá. Client không được coi khoá vắng là `false`.

    Không có `is_complete` ở đây, và đó là chủ ý. `is_complete` bên `VehicleProfileData`
    là cổng của **nhánh áp suất lốp**: nó hỏi "đã đủ để tra bảng bốn ô chưa". Không có
    câu hỏi tương đương cho trang bị — không tồn tại một tập "đủ", vì giá trị đến từng
    trường một. Bịa ra một cờ `is_complete` cho tập này là mời client chờ một trạng
    thái sẽ không bao giờ tới.
    """

    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    da_khai: dict[str, bool]
    #: Toàn bộ danh mục, kèm theo để client không phải nhúng bản sao của
    #: `src/safety/trang_bi.json`. Một bản sao ở FE là một nguồn sự thật thứ hai, và
    #: nó sẽ lệch đúng vào lúc thêm trang bị mới.
    danh_muc: list[TrangBiItem]


class VehicleOptionsEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: VehicleOptionsData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class VehicleOptionsUpdate(BaseModel):
    """Thân `PUT /api/v1/vehicle/profile/options`. Ghi đè **toàn bộ** tập đã khai.

    Khác `VehicleProfileUpdate` ở một chỗ và giống ở một chỗ, cả hai đều có lý do.

    **Giống**: ghi đè cả tập, không vá từng khoá. Vá từng khoá là để một
    `lop_du_phong=true` còn sót của chiếc xe trước ở lại trên chiếc xe sau — đúng lớp
    lỗi mà PUT-thay-vì-PATCH của #123 đã chặn.

    **Khác**: ở đây vắng khoá là hợp lệ và có nghĩa "chưa khai". `VehicleProfileUpdate`
    bắt buộc có mặt cả hai field vì "quên gửi" và "cố ý xoá" phải trông khác nhau; với
    một tập thì không có danh sách field cố định nào để mà quên, nên phân biệt ấy
    không tồn tại. Gửi `{}` là xoá sạch khai báo.
    """

    model_config = ConfigDict(extra="forbid")

    da_khai: dict[str, bool]


class VehicleProfileUpdate(BaseModel):
    """Thân `PUT /api/v1/vehicle/profile`.

    Ghi đè **toàn bộ** cặp, không vá từng phần: một xe nửa khai báo (`trim` mới,
    `battery` còn sót của xe trước) vẫn qua được `is_complete` rồi tra ra số của một
    chiếc xe không tồn tại. PUT nói đúng ngữ nghĩa đó; PATCH thì không.

    Hai trường **bắt buộc có mặt** nhưng được phép `null` — `null` tường minh là cách
    xoá cấu hình. Bỏ hẳn field khỏi body là lỗi 422, vì "quên gửi" và "cố ý xoá" phải
    trông khác nhau.
    """

    model_config = ConfigDict(extra="forbid")

    trim: Literal["eco", "plus"] | None
    battery: Literal["sdi", "catl"] | None


class RoutineData(BaseModel):
    """Một Routine trên dây (issue #282).

    `steps` giữ **nguyên dạng camelCase** mà `frontend/src/lib/services/routines/types.ts`
    khai và `src/agents/routines.py` nhận. Đây là ngoại lệ duy nhất so với snake_case của
    phần còn lại API, và nó có lý do: bảng dịch camelCase → tool canonical đã tồn tại ở
    đúng một chỗ. Đổi dạng ở đây nghĩa là dịch hai lần, và bảng thứ hai sẽ lệch bảng thứ
    nhất đúng vào ngày ai đó thêm một action.

    Ba field dẫn xuất — `needs_preview`, `needs_setup`, `runnable` — trả sẵn thay vì để
    client tự suy, cùng lập luận với `is_complete` của `VehicleProfileData`: điều kiện
    fail-closed do backend quyết, không phải mỗi client tự nghĩ một luật.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    name: str
    icon: Literal["briefcase", "home", "moon", "car", "music", "sun"]
    enabled: bool
    steps: list[dict[str, Any]]
    is_default_template: bool
    template_origin: Literal["di_lam", "ve_nha", "thu_gian"] | None
    version: int
    needs_preview: bool
    needs_setup: bool
    runnable: bool
    created_at: str
    updated_at: str


class RoutineEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: RoutineData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class RoutineListData(BaseModel):
    """`data` của `GET /api/v1/routines`.

    Bọc danh sách trong một object có khoá `items` chứ không trả mảng trần: mảng trần
    ở top-level không thêm được field nào về sau mà không phá client, và envelope của
    `api_spec.md` vốn đã chốt `data` là object.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[RoutineData]


class RoutineListEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: RoutineListData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class RoutineDraftBody(BaseModel):
    """Thân `POST /api/v1/routines` và `PUT /api/v1/routines/{id}`.

    Không nhận `id`, `user_id`, `enabled`, `is_default_template`, `version` hay các mốc
    thời gian: chủ sở hữu đến từ token, còn phần còn lại là thứ server tự quản. Nhận
    chúng từ client là mở đúng đường mà `extra="forbid"` đang đóng — một client gửi
    `user_id` của người khác không được phép trông như một request hợp lệ.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    icon: Literal["briefcase", "home", "moon", "car", "music", "sun"]
    steps: list[dict[str, Any]]


class RoutineEnabledBody(BaseModel):
    """Thân `PUT /api/v1/routines/{id}/enabled` — đúng một trường, bắt buộc có mặt."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool


class PlaceData(BaseModel):
    """Một nhãn địa điểm cá nhân đã gán (issue #283).

    `valid=false` nghĩa là hàng còn trong DB nhưng `destination_id` đã biến mất khỏi
    fixture offline. Không tự xoá dữ liệu người dùng, nhưng cũng **không** tính là đã
    thiết lập: spec §Nhà và Cơ quan chốt Routine ấy quay về "Cần thiết lập".

    `name` lấy từ fixture, và `null` khi `valid=false` — không có tên nào để hiển thị cho
    một id không còn ai biết là gì.
    """

    model_config = ConfigDict(extra="forbid")

    label: Literal["home", "office"]
    destination_id: str
    name: str | None
    valid: bool
    updated_at: str


class PlacesData(BaseModel):
    """`data` của `GET /api/v1/places`.

    Cả hai khoá luôn có mặt; `null` nghĩa là **chưa gán**. Ba trạng thái phân biệt được
    từ phía client: `null` (chưa gán), object `valid=true` (dùng được), object
    `valid=false` (gán rồi nhưng đích đã biến mất). Gộp hai ca cuối lại thành `null` sẽ
    làm màn thiết lập không nói được vì sao lựa chọn cũ biến mất.
    """

    model_config = ConfigDict(extra="forbid")

    home: PlaceData | None
    office: PlaceData | None


class PlacesEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: PlacesData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class PlaceUpdateBody(BaseModel):
    """Thân `PUT /api/v1/places/{label}`.

    Nhãn nằm ở path chứ không trong body: nó là **định danh tài nguyên**, và nhận nó ở
    cả hai chỗ là mời một request tự mâu thuẫn (`PUT /places/home` với `label: "office"`).
    """

    model_config = ConfigDict(extra="forbid")

    destination_id: str


class RoutineStepResultData(BaseModel):
    """Một bước trong sổ sách của lần chạy (issue #286).

    `status` là tập đóng: `completed` / `failed` / `skipped` / `blocked` / `canceled`.
    Bước chưa chạy vẫn **có mặt** với `skipped` chứ không biến mất — hồ sơ là thứ dùng
    để nói cái gì đã xảy ra và cái gì không.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    action: str
    status: Literal["completed", "failed", "skipped", "blocked", "canceled"]
    description: str
    error_code: str | None


class RoutineExecutionData(BaseModel):
    """Một lần chạy Routine.

    `status` gồm hai trạng thái còn sống (`running`, `waiting_approval`) và bốn trạng
    thái cuối (`completed`, `failed`, `blocked`, `user_canceled`) — đúng **một** trạng
    thái cuối cho mỗi lần chạy, kể cả khi hủy.

    `approval_id` chỉ có mặt khi đang chờ phê duyệt, và nó là thẻ của **một bước**, không
    phải của cả Routine: hai bước S2 xin phê duyệt tuần tự.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    routine_id: str
    session_id: str
    routine_version: int
    status: Literal["running", "waiting_approval", "completed", "failed", "blocked", "user_canceled"]
    current_index: int
    approval_id: str | None
    steps_total: int
    results: list[RoutineStepResultData]
    terminal_reason: str | None
    created_at: str
    updated_at: str


class RoutineExecutionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data: RoutineExecutionData
    meta: Meta
    trace_id: str
    schema_version: Literal["1.0"] = SCHEMA_VERSION


class RoutineRunBody(BaseModel):
    """Thân `POST /api/v1/routines/{id}/run`.

    `session_id` bắt buộc: một lần chạy thuộc về một phiên lái cụ thể — đó là thứ ràng
    buộc "tối đa một Routine đang chạy" và là nơi thẻ phê duyệt sẽ xuất hiện.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
