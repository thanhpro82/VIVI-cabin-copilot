/**
 * Domain "Routines" (issue #271, epic #270).
 *
 * #272 (BE, PR #359) đã đóng phần lưu trữ qua restart + kiểm tra ownership
 * theo user thật — `real.ts` (issue #370) implement đúng `RoutinesService`
 * này để gọi backend, `index.ts` chọn giữa nó và `mock.ts` (localStorage,
 * dùng khi `NEXT_PUBLIC_USE_MOCK_ROUTINES` không set thành `"false"`) qua
 * cùng khuôn cờ `NEXT_PUBLIC_USE_MOCK_*` với `turn`/`session`/`engineer`.
 *
 * Tên action đặt khớp tool canonical của backend (`src/services/tool_registry.py`)
 * để khi #274 (preview/chạy bằng voice) nối vào, không phải đổi tên gì — chỉ
 * đúng allowlist MVP mà PM/PO đã chốt ở epic #270: HVAC power/nhiệt độ/quạt,
 * media, cửa sổ, sưởi/chỉnh ghế trước, dẫn đường Nhà/Cơ quan, đèn cabin.
 */

/** Tập đóng, giống quy ước `OpenAppArgs`/`SearchNearbyPoiArgs` phía backend — không cho icon tuỳ ý. */
export type RoutineIcon = "briefcase" | "home" | "moon" | "car" | "music" | "sun";

export type WindowKey = "frontLeft" | "frontRight" | "rearLeft" | "rearRight";
export type FrontSeatKey = "frontLeft" | "frontRight";

export type RoutineStep =
  | { action: "hvac_power"; enabled: boolean }
  | { action: "hvac_temperature"; temperatureC: number } // 16-30, khớp SetHvacTemperatureArgs
  | { action: "hvac_fan_level"; level: number } // 0-3, khớp SetHvacFanLevelArgs
  | {
      action: "media_control";
      controlAction: "play" | "pause" | "next" | "previous" | "set_volume";
      volume?: number; // 0-100, bắt buộc iff controlAction === "set_volume"
    }
  | { action: "window_position"; window: WindowKey; percent: number } // 0-100
  | { action: "seat_heating"; seat: FrontSeatKey; level: number } // 0-3
  | { action: "seat_position"; seat: FrontSeatKey; axis: "fore_aft" | "recline" | "height"; value: number } // 0-100
  | { action: "navigation"; destination: "home" | "office" }
  | { action: "interior_light"; enabled: boolean };

/** `templateOrigin` neo Routine đã sửa về đúng mẫu gốc để "khôi phục mặc định" — chỉ 3 mẫu MVP. */
export type RoutineTemplateOrigin = "di_lam" | "ve_nha" | "thu_gian";

export interface Routine {
  id: string;
  userId: string;
  name: string;
  icon: RoutineIcon;
  enabled: boolean;
  /** 1-4 bước — rỗng hoặc >4 không được phép lưu (acceptance criteria #271). */
  steps: RoutineStep[];
  /** true = một trong ba mẫu mặc định (Đi làm/Về nhà/Thư giãn) — không xoá được, chỉ tắt/khôi phục. */
  isDefaultTemplate: boolean;
  templateOrigin: RoutineTemplateOrigin | null;
  /**
   * true khi vừa tạo hoặc vừa sửa và CHƯA từng chạy lần nào ở dạng hiện tại —
   * #274 (preview/chạy bằng voice) sẽ đọc cờ này để bắt buộc preview lượt đầu.
   * #271 chỉ có trách nhiệm BẬT cờ đúng lúc; tắt cờ (sau khi chạy) thuộc #274.
   */
  needsPreview: boolean;
  /**
   * Ba field dẫn xuất do backend quyết (issue #370/#272) — KHÔNG tự tính lại
   * ở FE, đó là cổng fail-closed của server. `mock.ts` chỉ xấp xỉ chúng vì
   * không có service địa điểm (#284) để hỏi thật.
   */
  needsSetup: boolean;
  runnable: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
}

/** Input tạo/sửa Routine — không có id/userId/isDefaultTemplate/needsPreview/timestamps, service tự gán. */
export interface RoutineDraft {
  name: string;
  icon: RoutineIcon;
  steps: RoutineStep[];
}

/** Tập đóng — khoá bởi test backend, không phải suy đoán (issue #286/#290). */
export type RoutineExecutionStepStatus = "completed" | "failed" | "skipped" | "blocked" | "canceled" | "waiting_approval";

/** Hai trạng thái còn sống, bốn trạng thái cuối — đúng MỘT trạng thái cuối cho mỗi lần chạy. */
export type RoutineExecutionStatus =
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "blocked"
  | "user_canceled";

export interface RoutineExecutionStepResult {
  index: number;
  action: string;
  status: RoutineExecutionStepStatus;
  description: string;
  errorCode: string | null;
}

/**
 * Snapshot REST của một lần chạy — dùng làm phản hồi tức thì cho `runRoutine`
 * (202, chưa xong khi trả về) và cho `getExecution` (nguồn sự thật fail-open
 * khi kênh WS gián đoạn, xem `docstring GET /routine-executions/{id}` phía
 * backend). KHÔNG có `routineName`/mô tả từng bước — đó là lý do UI nên seed
 * bằng chính `Routine.steps` đã có sẵn phía client, không đợi snapshot này.
 */
export interface RoutineExecution {
  id: string;
  routineId: string;
  sessionId: string;
  routineVersion: number;
  status: RoutineExecutionStatus;
  currentIndex: number;
  /** Chỉ có mặt khi `status === "waiting_approval"`. */
  approvalId: string | null;
  stepsTotal: number;
  results: RoutineExecutionStepResult[];
  terminalReason: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface RoutinesService {
  /** Danh sách Routine của user hiện tại (gồm cả 3 mẫu mặc định), mới sửa nhất trước. */
  listRoutines(): Promise<Routine[]>;
  /** Tạo Routine tự tạo mới từ đầu. Ném `ServiceError` nếu rỗng, >4 bước, hoặc tên trùng sau chuẩn hoá. */
  createRoutine(draft: RoutineDraft): Promise<Routine>;
  /** Sửa Routine đã có (mặc định hoặc tự tạo đều sửa được) — cùng validate như tạo mới. */
  updateRoutine(id: string, draft: RoutineDraft): Promise<Routine>;
  /** Bật/tắt Routine — không đổi `needsPreview`. */
  setEnabled(id: string, enabled: boolean): Promise<Routine>;
  /** Chỉ xoá được Routine tự tạo (`isDefaultTemplate === false`) — ném `ServiceError` nếu không. */
  deleteRoutine(id: string): Promise<void>;
  /** Khôi phục một mẫu mặc định đã sửa về đúng nội dung gốc — ném `ServiceError` nếu không phải mẫu mặc định. */
  restoreDefault(id: string): Promise<Routine>;
  /**
   * Bắt đầu chạy một Routine (issue #292). Ném `ServiceError` nếu Routine bị
   * tắt (`ROUTINE_DISABLED`), thiếu địa điểm (`ROUTINE_NEEDS_SETUP`), hoặc
   * phiên đang có một Routine khác chạy dở (`ROUTINE_ALREADY_RUNNING`).
   */
  runRoutine(id: string, sessionId: string): Promise<RoutineExecution>;
  /** Trạng thái một lần chạy — fallback không cần WS. Ném `ServiceError` `ROUTINE_EXECUTION_NOT_FOUND` nếu không thấy. */
  getExecution(executionId: string): Promise<RoutineExecution>;
  /**
   * Yêu cầu dừng tại điểm dừng an toàn (issue #298) — idempotent, gọi lại
   * hoặc gọi trên lần chạy đã kết thúc cho cùng kết quả, không lỗi. Trả về
   * ngay khi yêu cầu ĐÃ ĐƯỢC GHI NHẬN — `status` trong kết quả có thể vẫn là
   * `"running"`; trạng thái cuối thật tới qua sự kiện WS `routine.finished`
   * (`DriverShellProvider`'s `routineExecution.terminal`), không phải qua
   * promise này. KHÔNG rollback bước đã chạy xong.
   */
  cancelExecution(executionId: string): Promise<RoutineExecution>;
}
