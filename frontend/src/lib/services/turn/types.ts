export interface SeatState {
  heating: number;
  foreAft: number;
  recline: number;
  height: number;
}

export interface VehicleState {
  vehicleId: string;
  stateVersion: number;
  observedAt: string;
  motion: { speedKph: number; gear: string; ignition: string };
  hvac: { power: boolean; temperatureC: number; fanLevel: number };
  windows: { frontLeft: number; frontRight: number; rearLeft: number; rearRight: number };
  doors: { frontLeft: string; frontRight: string; rearLeft: string; rearRight: string };
  media: { status: string; volume: number; track: string | null };
  navigation: { status: string; destinationId: string | null };
  /** Domain thật của backend (api_spec.md:294-297, data_model.md:221-230) — 2 ghế trước, không phải GAP như lights/trunk. */
  seat: { frontLeft: SeatState; frontRight: SeatState };
  /**
   * KHÔNG còn là GAP. Trước 2026-08-15 hai field `lights`/`trunk` là "P1/demo
   * enhancement" chỉ tồn tại phía FE và `real.ts` luôn trả mặc định an toàn.
   * PR #92 (issue #65) đã mở rộng control surface ở backend: `vehicle_state`
   * thật giờ có đủ 9 domain, gồm cả hai field này, và có tool canonical điều
   * khiển chúng (`set_headlight_mode`, `set_interior_light`,
   * `set_trunk_state`). Xem ADR-020. Kiểu ở đây bám đúng payload thật, không
   * phải phiên bản rút gọn cũ (issue #115).
   *
   * `headlight` là enum 3 trạng thái, **không** phải boolean, và **không có
   * `off`**: UNECE R48 cấm tắt thủ công trên xe có DRL, nên router trả
   * `denied/headlight_off_not_permitted` cho "tắt đèn pha". Một toggle
   * bật/tắt không biểu diễn được enum này — UI phải chọn chế độ.
   */
  lights: { headlight: HeadlightMode; interior: boolean };
  /**
   * Cốp là actuator thật từ 2026-08-12 (`set_trunk_state`, domain `trunk`,
   * ADR-020) — S2/S3 cùng mức an toàn với cửa. Dùng "closed"/"open", không
   * dùng "unlocked" vì cốp có bộ truyền động mở từ xa thật, không giống khoá
   * cửa.
   */
  trunk: { position: TrunkPosition };
}

/**
 * Enum `headlight` của backend (`src/agents/router.py::_match_lights`,
 * `schemas/mqtt/`). Tên dân dã tương ứng theo sổ tay VF9: `low_beam` =
 * đèn chiếu gần/đèn cốt/"đèn pha" cách gọi thông thường, `high_beam` =
 * đèn chiếu xa. Cố ý không có `off` — xem comment ở `VehicleState.lights`.
 */
export type HeadlightMode = "auto" | "low_beam" | "high_beam";

export type TrunkPosition = "closed" | "open";

/**
 * Nhãn tiếng Việt cho từng chế độ đèn, và **câu lệnh** gửi cho router để chọn
 * chế độ đó. Để chung một chỗ vì cả UI lẫn `mock.ts` đều cần, và vì câu lệnh
 * phải khớp đúng từ khoá `router.py::_match_lights` đọc — lệch một chữ là rơi
 * về `clarify/missing_light_target` (cùng lớp lỗi đã ghi ở POSITIONS trong
 * VehicleControlView.tsx).
 */
export const HEADLIGHT_LABEL: Record<HeadlightMode, string> = {
  auto: "chế độ tự động",
  low_beam: "đèn chiếu gần",
  high_beam: "đèn chiếu xa",
};

export const HEADLIGHT_COMMAND: Record<HeadlightMode, string> = {
  auto: "chuyển đèn sang chế độ tự động",
  low_beam: "bật đèn chiếu gần",
  high_beam: "bật đèn chiếu xa",
};

/**
 * 6 cờ chính sách UI an toàn do backend tính (docs/api_spec.md:572,584) —
 * backend là nguồn duy nhất, FE không bao giờ tự suy các cờ này từ
 * speed_kph (docs/technical_spec.md:74).
 *
 * Trạng thái consumer, rà lại 2026-08-15 cho issue #111 (đừng đoán từ tên cờ):
 *
 * - `enlargeMicButton` → `HomeView.tsx`
 * - `lockSmallControls` → `VehicleControlView.tsx` (slider kính/ghế)
 * - `preferVoiceConfirmation` → `HitlModal.tsx`
 * - `allowDetailedDocumentBrowsing` → `CitationList.tsx`: nguồn sổ tay luôn
 *   hiện, nhưng chỉ bung được đoạn trích khi cờ bật.
 * - `maxVisibleActions` → `CitationList.tsx` giới hạn số nguồn hiện cùng lúc.
 *   **KHÔNG** áp cho lưới ứng dụng ở `HomeView`: backend gửi 3 ở CẢ hai chế độ
 *   (`src/services/ui_policy.py`), nên làm vậy sẽ ẩn vĩnh viễn 3 trong 6 ứng
 *   dụng kể cả lúc đỗ xe — đó là bug, không phải chính sách an toàn.
 * - `allowTextInput` → **chưa có consumer, và không phải do quên**: driver UI
 *   không có ô nhập chữ tự do nào (chủ đích voice-first). Hai `<input>` duy
 *   nhất trong `/driver` là slider `type=range` (đã do `lockSmallControls` lo)
 *   và ô số trong `SpeedDebugDrawer` (dev-only). Cờ này chỉ có việc khi nào
 *   sản phẩm quyết định thêm đường nhập chữ.
 */
export interface UiPolicy {
  allowTextInput: boolean;
  lockSmallControls: boolean;
  enlargeMicButton: boolean;
  maxVisibleActions: number;
  preferVoiceConfirmation: boolean;
  allowDetailedDocumentBrowsing: boolean;
  /**
   * Fail-closed thuần FE cho MẤT KẾT NỐI (issue #241, UAT-007/008) — KHÁC
   * `lockSmallControls`: cờ đó phản ánh xe đang chạy (backend tính theo tốc
   * độ, AC/đèn vẫn phải dùng được khi đang chạy) còn cờ này khoá TOÀN BỘ control
   * surface (cửa/cốp, AC, đèn, gửi turn mới) vì không còn kênh tin cậy để biết
   * xe đang ở trạng thái gì. Backend không biết khái niệm này — chỉ real.ts đặt
   * `true` khi WS đóng/lỗi xác thực, mock.ts/mapServerEvent luôn đặt `false` vì
   * cả hai chỉ chạy khi kết nối còn sống.
   */
  controlsLocked: boolean;
}

/**
 * Default trước khi nhận `ui.policy` đầu tiên — cố ý là biến thể SIẾT CHẶT
 * NHẤT (như xe đang chạy), không phải biến thể mở. Mở lúc chưa biết xe đang
 * thế nào là kiểu hỏng tệ nhất có thể chọn (đối xứng với backend fail-closed).
 *
 * Khớp đúng hằng `_MOVING` của backend (`src/services/ui_policy.py`, PR #77)
 * — `maxVisibleActions` là 3 ở CẢ HAI chế độ đứng yên/đang chạy trong bản
 * hiện tại (giá trị thấp hơn dành cho tình huống độ tin cậy ASR thấp trong
 * MỘT lượt cụ thể, chưa implement, không phải trạng thái mặc định của app).
 */
export const LOCKED_UI_POLICY: UiPolicy = {
  allowTextInput: false,
  lockSmallControls: true,
  enlargeMicButton: true,
  maxVisibleActions: 3,
  preferVoiceConfirmation: true,
  allowDetailedDocumentBrowsing: false,
  controlsLocked: true,
};

/**
 * Đối xứng của LOCKED_UI_POLICY: kênh sự kiện còn sống và xe đứng yên — không
 * siết gì cả. `mock.ts` phát đúng giá trị này sau "handshake", và test dùng nó
 * làm bằng chứng "backend khoẻ" thay vì mỗi file tự chép một object 7 trường.
 *
 * Giữ nguyên các giá trị mock đã dùng từ trước (`maxVisibleActions: 3` — xem
 * chú thích của LOCKED_UI_POLICY về vì sao cả hai chế độ đều là 3).
 */
export const OPEN_UI_POLICY: UiPolicy = {
  allowTextInput: true,
  lockSmallControls: false,
  enlargeMicButton: false,
  maxVisibleActions: 3,
  preferVoiceConfirmation: false,
  allowDetailedDocumentBrowsing: true,
  controlsLocked: false,
};

export type SafetyLevel = "S0" | "S1" | "S2" | "S3";

export interface ActionPlanStep {
  stepId: string;
  ordinal: number;
  tool: string;
  args: Record<string, unknown>;
  safetyLevel: SafetyLevel;
  dependsOn: string[];
}

export interface ActionPlan {
  planId: string;
  sessionId: string;
  vehicleId: string;
  vehicleStateVersion: number;
  steps: ActionPlanStep[];
  requiresApproval: boolean;
}

export interface Citation {
  citationId: string;
  documentTitle: string;
  section: string;
  page: number;
  excerpt: string;
}

export interface RoutinePreviewStep {
  index: number;
  action: string;
  description: string;
}

export interface RoutinePreview {
  routineId: string;
  routineName: string;
  steps: RoutinePreviewStep[];
}

/**
 * Issue #385: voice-run thiếu địa điểm bắt buộc. Chỉ xuất hiện khi mã lỗi là
 * `"chua_dat_dia_diem"` — ba mã còn lại (Routine tắt/không tồn tại/đang chạy dở) không
 * có màn setup nào để đưa tài xế sang. `thieu` là nhãn máy đọc được (`"home"`/`"office"`),
 * dùng để mở đúng hàng trong `PlacesPanel` — không so khớp câu tiếng Việt bao giờ đổi.
 */
export interface RoutineSetupRequired {
  routineId: string;
  maLoi: string;
  thieu: string[];
}

export interface TurnResult {
  displayText: string;
  speakText: string;
  citations: Citation[];
  outcomes: { stepId: string; status: string }[];
  /**
   * Còn phần sổ tay chưa đọc hết (issue #116). Nhánh tra sổ tay đọc từng đoạn
   * ngắn rồi mời "bạn có muốn nghe tiếp không?" — **lời mời đó chỉ nằm trong
   * kênh nói**, người nhìn màn hình không thấy gì và không có gì để bấm.
   *
   * Chỉ có ở `assistant.response` trên WS. **Không** có trong envelope HTTP của
   * `POST /turns/text`: `TurnResponseData` là `extra="forbid"`, thêm field vào
   * đó là đổi hợp đồng đồng bộ P0.
   *
   * Backend chưa gửi (PR #108 chưa merge) thì luôn là `false` — không có nút,
   * đúng như hôm nay. Thiếu field không được biến thành nút bấm rồi đi vào ngõ
   * cụt.
   */
  hasMoreToRead: boolean;
  /**
   * Backend bảo **còn nghe tiếp** — client được mở mic ngắn cho câu sau, khỏi phải nói
   * lại wake word (spec §3.1). Tính từ **kết cục cuối** của lượt: bật sau `completed` /
   * `offer` / `clarify` có mẫu ngữ pháp / câu hỏi sổ tay trả lời được; tắt khi xe không
   * hiểu, khi nghe hụt, và khi tài xế nói thôi.
   *
   * Vắng field = `false`. Thiếu tín hiệu **không** được biến thành mic mở — cùng quy ước
   * với `hasMoreToRead` ngay trên, và ở đây nó quan trọng hơn: đó là mở đúng cái cửa mà
   * cả spec đang lo cách đóng.
   *
   * **Khác hẳn `hasMoreToRead`.** Cờ kia là của nhánh **sổ tay** (còn đoạn chưa đọc).
   * Trộn hai đường lại thì rào chắn `mau_slot` (#363) mất tác dụng trong im lặng.
   */
  moMicNgan: boolean;
  /** Có cấu trúc khi outcome là routine_preview; vắng/null ở mọi lượt khác. */
  routinePreview?: RoutinePreview | null;
  /** Có cấu trúc khi mã lỗi routine là `chua_dat_dia_diem` (#385); vắng/null ở mọi lượt khác. */
  routineSetupRequired?: RoutineSetupRequired | null;
}

/**
 * Câu kích hoạt đọc tiếp. **Không tự đổi chữ**: backend nhận diện intent
 * `manual_continue` theo cách nói, và đây còn là câu chính người dùng phải NÓI
 * khi không bấm nút.
 *
 * Vì sao dài dòng vậy mà không phải "Đọc tiếp": đo trên giọng tổng hợp
 * `vi_VN-piper` qua đúng `voice.transcribe_raw`, chỉ 2/7 câu kích hoạt sống sót
 * qua STT — "Nghe tiếp" nghe thành *"Mê tiết"*, "Đọc tiếp" thành *"Lộc tiết"*.
 * Câu dài lại chính xác. Xem bảng trong issue #116.
 */
export const CONTINUE_READING_COMMAND = "Nói tiếp đi";

export type AssistantState =
  | "transcribing"
  | "routing"
  | "planning"
  | "retrieving"
  | "waiting_approval"
  | "executing"
  | "composing";

export type ToolResultStatus =
  | "completed"
  | "failed"
  | "timeout"
  | "skipped_due_to_prior_failure"
  | "skipped_external_state_change";

export type TurnCancelReason =
  | "approval_rejected"
  | "approval_expired"
  | "approval_invalidated_state"
  | "approval_invalidated_plan"
  | "approval_predicate_failed"
  | "approval_not_pending"
  | "user_canceled";

/**
 * Sự kiện realtime của WS /ws/ivi (Driver server-event allowlist, xem
 * docs/api_spec.md ở repo cha). Component chỉ nên xử lý qua switch/case
 * trên `type`, không tự suy diễn field ngoài danh sách này.
 */
/** Một bước trong `plan.ready.steps`. Đủ để client biết bước nào vừa làm gì mà
 * backend không phải biết tên màn hình nào của frontend. */
export interface PlanReadyStep {
  stepId: string;
  tool: string;
  /** `null` với tool cục bộ của IVI — chúng không có domain MQTT. */
  domain: string | null;
  args: Record<string, unknown>;
}

/** Tập đóng — khoá bởi test backend (`src/services/routine_execution.py`), không phải suy đoán. */
export type RoutineStepStatus = "completed" | "failed" | "skipped" | "blocked" | "canceled" | "waiting_approval";

/** Tập đóng — đúng MỘT trạng thái cuối cho mỗi lần chạy, kể cả khi bị huỷ. */
export type RoutineTerminalStatus = "completed" | "failed" | "blocked" | "user_canceled";

/** Một bước trong `routine.started.steps` — chỉ có index/action/description,
 * CHƯA có status (bước nào cũng "chờ" tới khi `routine.step` đầu tiên tới). */
export interface RoutineStepSummary {
  index: number;
  action: string;
  description: string;
}

export type DriverEvent =
  | { type: "turn.accepted"; turnId: string; inputMode: "voice" | "text" }
  | { type: "transcript.partial"; turnId: string; text: string }
  | { type: "transcript.final"; turnId: string; text: string; confidence: number }
  | { type: "assistant.status"; turnId: string; state: AssistantState }
  | {
      /** Kế hoạch vừa được lập — `docs/api_spec.md` §Driver server-event allowlist.
       *
       * ⚠️ **`steps` KHÔNG phải tín hiệu để đổi màn.** Event này phát ở giai đoạn định
       * tuyến, *trước* nhánh chính sách, nên backend bắn nó cả cho lượt bị chặn S3.
       * Đổi màn ngay khi nhận nó nghĩa là mở YouTube xong rồi mới bị chặn — luật an
       * toàn thành trang trí. Mốc đúng là `tool.result` với `status: "completed"`,
       * mà lượt bị chặn không bao giờ sinh ra. Xem ADR-023.
       *
       * `domain` là `null` với tool cục bộ của IVI (không đi qua MQTT); phân biệt
       * chúng bằng `tool` + `args`.
       */
      type: "plan.ready";
      turnId: string;
      routeKind: "action" | "manual" | "response";
      planId: string | null;
      summary: string;
      requiresApproval: boolean;
      steps: PlanReadyStep[];
    }
  | {
      type: "approval.required";
      turnId: string;
      approvalId: string;
      planId: string;
      approvedVehicleStateVersion: number;
      expiresAt: string;
    }
  | {
      /** Handoff của lượt phê duyệt bằng lời — `api_spec.md:576`.
       *
       * Chú thích cũ ở đây ("backend **không** commit quyết định") đã lạc hậu từ #191:
       * backend giờ tự chốt, nhưng **bất đối xứng** — mọi cụm từ chối, còn phía chấp
       * nhận chỉ cụm rõ ràng (`đồng ý`, `xác nhận`, `chấp nhận`, `duyệt`). Đồng ý trần
       * (`ừ`, `vâng`, `ok`) cố ý KHÔNG chốt: chúng xuất hiện quá nhiều trong hội thoại
       * thường, và nghe nhầm một tiếng "ừ" là xe tự làm một việc S2.
       *
       * Xem `committed` — nó là thứ duy nhất phân biệt hai ca ấy.
       */
      type: "approval.intent.detected";
      turnId: string;
      approvalId: string;
      originalTurnId: string;
      decision: "approve" | "reject";
      approvedVehicleStateVersion: number;
      /**
       * Backend đã chốt quyết định chưa. **Ba trạng thái, không phải hai** — và
       * `undefined` không phải thiếu sót:
       *
       * | | nghĩa | IVI làm gì |
       * |---|---|---|
       * | `true` | đã chốt server-side | không gọi REST, chờ event của lượt gốc |
       * | `false` | cố ý không chốt (đồng ý trần) | mời tài xế chạm nút "Đồng ý" |
       * | `undefined` | BE chưa phát trường này | giữ hành vi cũ: IVI gọi REST |
       *
       * Nhánh `undefined` là **đường lui theo phiên bản**, không phải code chết: phần
       * BE của issue #207 chưa merge lúc file này viết ra. Không có nhánh ấy thì thứ
       * tự merge quyết định hành vi — FE vào trước là "ừ" thành không-ai-chốt trong
       * khi xe vẫn đọc "Tôi sẽ thực hiện ngay". Bỏ nhánh này khi BE đã vào `develop`.
       */
      committed?: boolean;
    }
  | { type: "action.blocked"; turnId: string; reason: string }
  | {
      type: "tool.result";
      turnId: string;
      stepId: string;
      status: ToolResultStatus;
      /** null chỉ với "completed"; bắt buộc với failed/timeout/skipped (api_spec.md). */
      errorCode: string | null;
    }
  /** Phát TRƯỚC assistant.response cùng turn (issue #66) — best-effort: vắng
   * mặt hoàn toàn (không phải event rỗng/lỗi) khi TTS thất bại hoặc response
   * text rỗng, xem docs/api_spec.md. Không được coi vắng mặt là lỗi giao thức. */
  | { type: "assistant.speech"; turnId: string; audioBase64: string; mimeType: string }
  | { type: "assistant.response"; turnId: string; result: TurnResult }
  | { type: "turn.completed"; turnId: string }
  | { type: "turn.failed"; turnId: string; code: string }
  | { type: "turn.canceled"; turnId: string; reason: TurnCancelReason }
  | { type: "error"; code: string; message: string; retryable: boolean }
  /**
   * Sự kiện cấp session, KHÔNG thuộc lượt nào (`turn_id` luôn null ở wire
   * format) — đừng lọc theo turnId hiện tại. Payload thô còn có
   * `active`/`speed_kph` nhưng cố ý không mang sang đây: `speed_kph` ở
   * event này có thể cũ (chỉ phát khi policy đổi, không phải mỗi tick tốc
   * độ) — cần tốc độ tươi thì đọc `VehicleState.motion.speedKph` qua
   * `getVehicleState()`/polling, không phải từ event này.
   */
  | { type: "ui.policy"; uiPolicy: UiPolicy }
  /**
   * Ba sự kiện Routine (#290) ride CHUNG `/ws/ivi` với mọi event khác —
   * `execution_id` nằm ở đúng vị trí `turn_id` của khung sự kiện, nên một
   * lần chạy Routine đóng vai một "lượt" trên stream (ADR-014 lo sequence/
   * event_id/replay sẵn, không cần cơ chế riêng). Map sang `executionId`
   * thay vì `turnId` ở đây vì đó mới là tên đúng ngữ nghĩa cho consumer.
   *
   * `routine.started` phát đúng một lần khi lần chạy được nhận. `steps` chỉ
   * gồm `{index, action, description}` — CHƯA có status; mọi bước "chờ" tới
   * khi `routine.step` đầu tiên khớp `index` đó tới.
   */
  | {
      type: "routine.started";
      executionId: string;
      routineId: string;
      routineName: string;
      routineVersion: number;
      steps: RoutineStepSummary[];
      startedAt: string;
    }
  /** Một bước vừa đổi trạng thái. `approvalId` chỉ có mặt khi `status === "waiting_approval"`. */
  | {
      type: "routine.step";
      executionId: string;
      index: number;
      action: string;
      status: RoutineStepStatus;
      description: string;
      errorCode: string | null;
      approvalId?: string;
    }
  /** Đúng MỘT lần cho mỗi lần chạy (khoá bởi test backend) — không có update nào sau nó. */
  | {
      type: "routine.finished";
      executionId: string;
      routineId: string;
      status: RoutineTerminalStatus;
      terminalReason: string | null;
      results: (RoutineStepSummary & { status: RoutineStepStatus; errorCode: string | null })[];
      completedAt: string;
      /** Câu tổng kết đọc to (issue #396) — `null` khi TTS lỗi/rỗng, fail-open như `assistant.speech`. */
      audioBase64: string | null;
      mimeType: string | null;
    };

/**
 * Số của hộp số xe ảo — đúng tập giá trị `MotionState.gear` của hợp đồng xe, và
 * đúng `Gear` mà `src/models/sim_harness.py` khai. Cố ý viết lại chứ không suy
 * từ `VehicleState.motion.gear` (kiểu `string`): body gửi lên bị
 * `extra="forbid"` + enum kiểm ở backend, sai một chữ là 422.
 */
export type SimGear = "P" | "R" | "N" | "D";

/**
 * Trần của thanh trượt. Bằng đúng `SPEED_MAX_KPH` phía backend — vượt là 422.
 * Đây là trần của **bàn đạo diễn kịch bản**, không phải thông số VF9.
 */
export const SIM_SPEED_MAX_KPH = 200;

/**
 * Thân của `202 Accepted` từ `POST /api/v1/sim/motion` — trả **thô**, không bọc
 * envelope `{data:...}` như các interface P0 (route harness nằm ngoài bảng 14).
 *
 * `gear` là `null` khi client không gửi số: backend echo lại đúng thứ nó nhận,
 * còn việc suy ra `D`/`P` là do **xe ảo** làm lúc gọi `set_motion(gear=None)`.
 * Đừng đọc field này như "số hiện tại của xe" — số thật đọc ở
 * `VehicleState.motion.gear` sau khi poll.
 */
export interface SimMotionResult {
  accepted: boolean;
  speedKph: number;
  gear: SimGear | null;
}

/**
 * Mã lỗi FE dùng để nhận ra "kênh harness không tồn tại trên backend này".
 *
 * Hai đường cùng dẫn tới đây và cả hai đều **bình thường**, không phải sự cố:
 * cờ `SIM_CONTROL_ENABLED=false` (mặc định) khiến route trả 404 có envelope
 * `{"error":{"code":"NOT_FOUND"}}`; còn backend chưa có PR #206 thì FastAPI trả
 * 404 mặc định `{"detail":"Not Found"}` không có `error.code`. `throwIfError`
 * dùng đúng chuỗi này làm fallbackCode nên hai ca cho cùng một mã — UI chỉ cần
 * một nhánh.
 */
export const SIM_HARNESS_ABSENT_CODE = "NOT_FOUND";

/**
 * `tool.result.error_code` khi phiên chỉ-xem (pool xe ảo hết, issue #261) cố
 * gửi lệnh điều khiển — không có `VehicleCommand` nào được publish. Dịch sang
 * tiếng Việt ở đây thay vì hiện mã kỹ thuật thô cho tài xế.
 */
export const VEHICLE_POOL_EXHAUSTED_CODE = "vehicle_pool_exhausted";
export const VEHICLE_POOL_EXHAUSTED_MESSAGE =
  "Hết xe mô phỏng khả dụng — bạn đang ở chế độ chỉ xem, không thể gửi lệnh điều khiển.";

/**
 * Event `error` khi lease xe hết hạn GIỮA CHỪNG (issue #351) — khác hẳn
 * `VEHICLE_POOL_EXHAUSTED_CODE`: mã này là người VỪA MẤT chiếc xe mình đang
 * lái, không phải người chưa từng được cấp. Cố ý không gộp hai mã — gộp là ép
 * một trong hai câu thông báo hiển thị sai ngữ cảnh. `message` backend gửi đã
 * là câu tiếng Việt đúng, không cần hằng message riêng như cặp ở trên.
 */
export const VEHICLE_LEASE_EXPIRED_CODE = "VEHICLE_LEASE_EXPIRED";

export interface TurnService {
  /** Đọc trạng thái xe — gọi lúc khởi tạo /driver, và lại sau mỗi tool.result/turn.completed. */
  getVehicleState(): Promise<VehicleState>;
  /** Dùng cho CẢ lệnh gõ tay lẫn lệnh do UI tự dựng câu khi bấm nút (xem ARCHITECTURE.md mục 4). */
  sendText(
    text: string,
  ): Promise<{ turnId: string; routinePreview?: RoutinePreview | null; routineSetupRequired?: RoutineSetupRequired | null }>;
  /**
   * `opts.auto` = lượt này do **cửa sổ nghe tiếp tự bắt**, không phải tài xế chủ động.
   * Backend dùng nó để **im lặng** thay vì đọc câu từ chối khi không hiểu (spec §3.5) —
   * nếu không, một câu tài xế nói với người ngồi cạnh sẽ khiến xe chen vào cuộc nói
   * chuyện của họ.
   *
   * Vắng = `manual`. Fail về phía **nói**: một trợ lý câm khó chẩn đoán hơn nhiều một
   * trợ lý nói thừa.
   */
  sendVoice(audio: Blob, opts?: { auto?: boolean }): Promise<{ turnId: string }>;
  decideApproval(
    approvalId: string,
    decision: "approve" | "reject",
    approvedVehicleStateVersion: number,
  ): Promise<void>;
  getCitation(citationId: string): Promise<Citation>;
  /**
   * Đặt tốc độ/số của **xe ảo** qua kênh harness `v1/sim` (issue #183, ADR-024).
   *
   * KHÔNG phải lệnh điều khiển xe: nó không đi qua router/policy/HITL và không
   * sinh ra lượt nào. Đây là bàn đạo diễn để dựng ca S3 ("mở cửa khi xe đang
   * chạy") mà trước đây chỉ gõ được vào stdin của `python -m src.vehicle_sim`.
   *
   * Bỏ trống `gear` nghĩa là "chọn hộ tôi" — xe ảo lấy `D` khi tốc độ > 0 và
   * `P` khi bằng 0, đúng quy ước `speed 45` gõ tay ở console.
   *
   * Backend trả **202**, không phải 200: xe đổi state bất đồng bộ qua MQTT nên
   * lúc lời gọi này resolve thì `getVehicleState()` chưa chắc đã thấy giá trị
   * mới. Người gọi phải poll, đừng coi kết quả trả về là state.
   *
   * Ném `ServiceError` với `code === SIM_HARNESS_ABSENT_CODE` khi backend không
   * bật kênh này — **ca bình thường, không phải lỗi để báo toast**.
   */
  setSimSpeed(speedKph: number, gear?: SimGear): Promise<SimMotionResult>;
  /** Trả về hàm unsubscribe. */
  subscribe(onEvent: (event: DriverEvent) => void): () => void;
}
