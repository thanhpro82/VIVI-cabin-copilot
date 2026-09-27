"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { startWavRecording, type WavRecording } from "@/lib/audio/wavRecorder";
import { MicrophonePipeline } from "@/lib/audio/microphonePipeline";
import { createOnnxWakeWordDetector } from "@/lib/wake-word/onnxWakeWordDetector";
import { ARM_BEEP_DURATION_MS, WakeWordController } from "@/lib/wake-word/WakeWordController";
import type { WakeState } from "@/lib/wake-word/wakeWordState";
import { sessionService } from "@/lib/services/session";
import type { VehiclePoolStatus } from "@/lib/services/session";
import { turnService } from "@/lib/services/turn";
import {
  LOCKED_UI_POLICY,
  VEHICLE_LEASE_EXPIRED_CODE,
  VEHICLE_POOL_EXHAUSTED_CODE,
  VEHICLE_POOL_EXHAUSTED_MESSAGE,
} from "@/lib/services/turn/types";
import type {
  AssistantState,
  Citation,
  DriverEvent,
  PlanReadyStep,
  RoutinePreview,
  RoutineSetupRequired,
  RoutineStepStatus,
  RoutineStepSummary,
  RoutineTerminalStatus,
  UiPolicy,
  VehicleState,
} from "@/lib/services/turn/types";
import { viewForStep } from "@/lib/ivi/viewMapping";
import { shouldStartCloseTimerImmediately } from "./voiceOverlayClose";

/** Chặn ghi vô hạn nếu người dùng quên chạm để dừng. */
const MAX_RECORDING_MS = 12_000;

/**
 * Thời gian tối thiểu transcript phải "đứng yên" trên overlay trước khi bị
 * câu trả lời thay vào. Với lệnh đơn giản (vd "bật điều hòa"), backend xử lý
 * xong nhanh tới mức `transcript.final` và `assistant.response` tới cách
 * nhau vài mili-giây — React 18 gộp 2 lần setState đó vào cùng 1 lượt vẽ,
 * nên trình duyệt nhảy thẳng sang câu trả lời, không kịp vẽ khung hình nào
 * chỉ hiện transcript (tài xế không có cách nào thấy được máy đã nghe đúng
 * chưa). Không sửa được bằng cách gộp/tách state — phải ép có khoảng nghỉ
 * thật trên đồng hồ giữa 2 lần vẽ.
 */
const MIN_TRANSCRIPT_VISIBLE_MS = 2000;

/**
 * Overlay tự đóng bao lâu SAU KHI audio TTS phát xong (`ended`) — không phải
 * sau khi text hiện ra. Trước đây đóng cố định 1.8s tính từ lúc có text, mà
 * đó cũng là lúc audio `assistant.speech` bắt đầu phát (2 event tới gần như
 * cùng lúc) — câu dài thì audio còn đang đọc dở overlay đã tắt gần hết giờ.
 * Fallback (không có audio/audio lỗi, xem `shouldStartCloseTimerImmediately`)
 * vẫn đếm từ lúc text hiện như cũ.
 */
const CLOSE_AFTER_AUDIO_MS = 4500;

/** Tối đa bao nhiêu câu trả lời gần nhất giữ lại để xem lại trong lúc overlay còn mở. */
const MAX_TURN_HISTORY = 3;

/** Nới bao lâu sau `expires_at` mới tự gỡ hộp thoại duyệt — xem effect hết hạn. */
const GRACE_HET_HAN_MS = 2000;

/**
 * Nhớ tối đa bao nhiêu turnId "đã bị thay thế" (xem `turnIdDaThayTheRef`).
 *
 * Trần chứ không phải `Set` mọc mãi: một phiên IVI sống suốt chuyến đi và không có gì
 * dọn tập ấy. 32 là rộng hơn nhiều lần số lượt có thể còn event bay trên đường — một
 * lượt đủ già để rụng khỏi danh sách thì mọi event của nó đã tới từ lâu.
 */
const GIOI_HAN_LUOT_CU = 32;

/**
 * Chờ audio câu hỏi duyệt đọc xong bao lâu trước khi tự mở mic mà không cần nó (#207b).
 *
 * Đường lui cho một ca im lặng: `play()` bị autoplay policy chặn thì element vẫn nằm
 * trong `activeSpeechRef` với `ended=false`, `error=null` — `shouldStartCloseTimerImmediately`
 * trả false và effect đăng ký nghe một sự kiện **không bao giờ phát**. Mic không mở, và
 * không có gì báo. Đó là kiểu hỏng tệ nhất: nó xảy ra đúng trên máy dễ hỏng nhất (trang
 * chưa có cử chỉ người dùng nào) và nhìn như chưa ai làm tính năng.
 *
 * 1200 ms: đủ để audio kịp bắt đầu phát nếu nó phát được, đủ ngắn để lượt không có audio
 * không bắt tài xế ngồi chờ. Hết giờ vẫn phải hỏi `paused` trước khi mở — audio đang đọc
 * thật thì để `ended` lo, không thì micro thu đúng giọng của xe.
 */
const CHO_AM_THANH_MS = 1200;

/** Mở lại mic tối đa mấy lần cho MỘT phê duyệt trước khi trả về cho nút bấm (#207b). */
const MAX_MO_LAI_MIC = 2;

/** Throttle mức mic đẩy ra UI (issue #342) — ~20Hz, đủ mượt cho mắt và tránh ghi
 * DOM ở tần suất frame worklet thật (hàng chục lần/giây). */
const MIC_LEVEL_THROTTLE_MS = 50;

/**
 * Beep ngắn báo tài xế bắt đầu nói, phát ngay khi controller vào ARMING (trước
 * cả khi bắt đầu ghi câu lệnh) — dùng Web Audio oscillator, không thêm asset.
 * Best-effort: không nghe được beep thì vẫn thấy overlay mở.
 */
function playArmBeep(): void {
  try {
    const AudioContextCtor =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    const context = new AudioContextCtor();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const durationSeconds = ARM_BEEP_DURATION_MS / 1000;
    oscillator.frequency.value = 880;
    gain.gain.setValueAtTime(0.15, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + durationSeconds);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + durationSeconds);
    oscillator.onended = () => void context.close();
  } catch {
    // Chỉ là tín hiệu âm thanh phụ trợ; lỗi ở đây không ảnh hưởng tính đúng
    // đắn của capture.
  }
}

/**
 * Beep trầm hơn arm beep (440Hz thay vì 880Hz), phát khi cửa sổ nghe tiếp
 * (issue #343) hết giờ mà không ai nói — tài xế nhiều lúc không nhìn màn
 * hình, đây là cách duy nhất báo "hết giờ rồi" mà không cần liếc mắt.
 */
function playCloseBeep(): void {
  try {
    const AudioContextCtor =
      window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AudioContextCtor) return;
    const context = new AudioContextCtor();
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const durationSeconds = ARM_BEEP_DURATION_MS / 1000;
    oscillator.frequency.value = 440;
    gain.gain.setValueAtTime(0.15, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + durationSeconds);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start();
    oscillator.stop(context.currentTime + durationSeconds);
    oscillator.onended = () => void context.close();
  } catch {
    // Chỉ là tín hiệu âm thanh phụ trợ; lỗi ở đây không ảnh hưởng tính đúng
    // đắn của việc đóng cửa sổ nghe tiếp.
  }
}

export type ViewName = "home" | "vehicle" | "music" | "map" | "youtube" | "spotify" | "tiktok" | "routines";

/**
 * Sức khoẻ của kênh sự kiện `/ws/ivi` — nguồn duy nhất để biết có được phép gửi
 * lượt mới hay không (issue #241, UAT-007/UAT-008).
 *
 * Ba giá trị chứ không phải hai, và `connecting` mới là giá trị đắt nhất:
 *
 * - `connecting` — **chưa có bằng chứng nào** rằng backend còn sống: chưa nhận
 *   `ui.policy` đầu tiên kể từ khi subscribe. Đây là trạng thái lúc mới mở app,
 *   và cũng là trạng thái vĩnh viễn khi backend chết ngay từ đầu tới mức
 *   `createDriverSession()` trượt, `subscribe()` không mở nổi socket và không có
 *   sự kiện nào để phân biệt "đang chờ" với "hỏng" (real.ts, nhánh `if (!session)`).
 *   Fail-closed.
 * - `online` — đã nhận `ui.policy` THẬT từ backend (`controlsLocked === false`).
 *   Chỉ trạng thái này mới được gửi lệnh.
 * - `offline` — đã từng biết, giờ mất: real.ts phát `LOCKED_UI_POLICY` khi socket
 *   đóng/lỗi xác thực, hoặc quá `XAC_NHAN_KET_NOI_MS` mà vẫn chưa xác nhận được.
 *
 * Bản đầu của PR #246 chỉ có hai trạng thái (cờ `hasReceivedUiPolicyRef`) và coi
 * "chưa biết gì" là **cho phép gửi** — mở app khi backend đã chết sẵn thì
 * `send()` vẫn bắn `POST /turns/text` ra network và ăn `ERR_CONNECTION_REFUSED`,
 * đúng thứ UAT-008 cấm (PM/PO review 2026-08-23).
 */
export type ConnectionState = "connecting" | "online" | "offline";

/**
 * Chờ `ui.policy` đầu tiên bao lâu trước khi kết luận là hỏng.
 *
 * Cần vì `connecting` có một ngõ cụt im lặng: `subscribe()` của real.ts return
 * ngay khi chưa có driver session, và `bootstrap()` chỉ subscribe đúng một lần —
 * backend chết lúc khởi động ⇒ không sự kiện nào tới, mãi mãi. Không có mốc này
 * thì màn hình đứng ở "Đang kết nối…" vô hạn trong khi thực tế **không có ai
 * đang kết nối cả** — nói dối tài xế theo hướng lạc quan.
 *
 * 8000 ms khớp trần backoff reconnect của real.ts (`Math.min(1000 * attempt, 8000)`),
 * nên một lần rớt-rồi-nối-lại bình thường không chạm tới nó.
 */
const XAC_NHAN_KET_NOI_MS = 8000;

/** Vì sao lệnh bị chặn — `Record` để TypeScript bắt lỗi nếu thêm trạng thái mới. */
const TOAST_CHUA_ONLINE: Record<Exclude<ConnectionState, "online">, string> = {
  connecting: "Đang kết nối với hệ thống — chưa gửi được lệnh, vui lòng đợi một chút.",
  offline: "Mất kết nối với hệ thống — vui lòng thử lại sau.",
};

// P0 là demo 1 xe duy nhất — khớp src/config.py:vehicle_id và mock.ts, không có
// UI chọn xe. Không có bước này thì currentSessionId() trong turn/real.ts luôn
// throw (chưa từng có session), send()/openVoice()/approve() nuốt lỗi qua
// void nên bấm gì cũng như không, không có thông báo nào cho người dùng biết.
const DEMO_VEHICLE_ID = "vehicle-demo-01";

interface PendingApproval {
  approvalId: string;
  approvedVehicleStateVersion: number;
  summary: string;
  expiresAt: string;
  /** `turn_id` của lượt lệnh **đã sinh ra** phê duyệt này.
   *
   * Không phải để hiển thị: nó là thứ phân biệt "lượt của tôi vừa kết thúc" với "một
   * lượt nào đó vừa kết thúc". Thiếu nó thì mọi sự kiện terminal đều đóng hộp thoại,
   * kể cả của một câu tán gẫu — xem nhánh `turn.completed`. */
  turnId: string;
}

/** Kết quả một bước, đã biết (từ `routine.step` hoặc `routine.finished.results`). */
export interface RoutineExecutionStepResult {
  index: number;
  action: string;
  status: RoutineStepStatus;
  description: string;
  errorCode: string | null;
  approvalId?: string;
}

/**
 * Trạng thái sống của lần chạy Routine gần nhất trên phiên này (#290/#292).
 *
 * Đúng MỘT execution tại một thời điểm — khớp bất biến backend "tối đa một
 * Routine đang chạy mỗi phiên" (`dang_chay_routine_khac`, `src/api/routine_
 * routes.py`). `routine.started` THAY THẾ hoàn toàn state cũ (không merge):
 * một lần chạy mới bắt đầu nghĩa là lần trước, nếu còn, đã không còn là lần
 * "gần nhất" nữa.
 *
 * `stepResults` là map rời theo `index`, không phải mảng — `routine.step` tới
 * không theo thứ tự bảo đảm nào khác ngoài tuần tự thật của backend, và tra
 * theo index tránh phải tìm kiếm tuyến tính mỗi lần cập nhật.
 */
export interface RoutineExecutionState {
  executionId: string;
  routineId: string;
  routineName: string;
  routineVersion: number;
  steps: RoutineStepSummary[];
  stepResults: Record<number, RoutineExecutionStepResult>;
  startedAt: string;
  terminal: { status: RoutineTerminalStatus; terminalReason: string | null; completedAt: string } | null;
}

export interface ActiveRoutinePreview {
  turnId: string;
  preview: RoutinePreview;
}

export interface ActiveRoutineSetupRequired {
  turnId: string;
  setup: RoutineSetupRequired;
}

interface LastTurn {
  user: string;
  vivi: string | null;
  /**
   * Trích dẫn sổ tay kèm câu trả lời, rỗng với lượt điều khiển. Trước đây
   * `assistant.response` mang sẵn mảng này nhưng Provider vứt đi, nên FE không
   * có gì để áp cờ `allowDetailedDocumentBrowsing` (issue #111).
   */
  citations: Citation[];
  /** Còn phần sổ tay chưa đọc — VoiceOverlay hiện nút "Nghe tiếp" (issue #116). */
  hasMoreToRead: boolean;
}

interface DriverShellValue {
  vehicleState: VehicleState | null;
  /** Chính sách UI an toàn do backend phát qua ui.policy (docs/api_spec.md:572) — luôn ở trạng thái siết (LOCKED_UI_POLICY) cho tới khi nhận event đầu tiên. */
  uiPolicy: UiPolicy;
  /**
   * Sức khoẻ kênh `/ws/ivi` (issue #241) — dùng để khoá mặt điều khiển và nói
   * rõ vì sao. Đọc cờ này chứ đừng suy từ `uiPolicy.lockSmallControls`: cờ kia
   * phản ánh **xe đang chạy**, không phải mất kết nối.
   */
  connectionState: ConnectionState;
  /**
   * Quyền lái của phiên hiện tại (pool xe ảo, issue #261). `false` = chế độ
   * chỉ xem: vẫn tra sổ tay/đọc trạng thái xe, lệnh điều khiển bị khoá — LÝ DO
   * KHÁC `connectionState`, đừng gộp chung một cờ hay một thông điệp.
   */
  canDrive: boolean;
  /** null = pool không cấp phát (`VEHICLE_POOL_SIZE=1`), không có trần nào để hiện. */
  vehiclePool: VehiclePoolStatus | null;
  activeView: ViewName;
  setActiveView: (view: ViewName) => void;
  lastTurn: LastTurn | null;
  /**
   * Tối đa MAX_TURN_HISTORY câu trả lời gần nhất (không tính lượt hiện tại, đã
   * có trong lastTurn.vivi) — mới nhất ở cuối mảng.
   *
   * HIỆN KHÔNG CÓ UI NÀO TIÊU THỤ, và đó là chủ ý: VoiceOverlay đổi sang thẻ
   * nổi chỉ hiện lượt hiện tại (quyết định UX ghi ở
   * `docs/tasks/TASK-FE-BE-004-...md` mục 4.1). Giữ lại vì rẻ và là chỗ nối
   * sẵn cho khung hội thoại "đọc lại nhiều lượt" nếu làm sau này — đọc mục
   * 4.1 trước khi xoá, đừng coi là code sót.
   */
  turnHistory: string[];
  assistantState: AssistantState | null;
  pendingApproval: PendingApproval | null;
  /**
   * Tài xế đã đồng ý bằng lời trần ("ừ", "vâng", "ok") và backend cố ý không chốt
   * (#191) — `HitlModal` dùng để làm nổi nút "Đồng ý", đúng hành vi `api_spec.md`
   * mô tả cho ca này. Không phải trạng thái lỗi: hệ thống hiểu đúng, chỉ đang đòi
   * một cử chỉ có chủ ý hơn cho một lệnh S2.
   */
  approvalNeedsTap: boolean;
  approve: () => void;
  reject: () => void;
  voiceOpen: boolean;
  openVoice: () => void;
  /** true trong lúc mic đang thu — VoiceOverlay dùng để hiện waveform + cho chạm dừng. */
  recording: boolean;
  /** Dừng ghi và gửi WAV thu được lên BE. Không làm gì nếu chưa/không còn đang ghi. */
  stopVoice: () => void;
  transcript: string | null;
  send: (text: string) => void;
  /** true từ lúc gọi send() tới khi turn.completed/canceled — dùng làm phản hồi tức thì cho nút bấm. */
  pending: boolean;
  /** Toast tạm thời hiện kết quả lệnh (kể cả khi bị chặn S3) — hiện bất kể voice overlay có mở hay không. */
  toast: string | null;
  /** Đọc lại vehicleState ngay — dùng cho debug drawer: đổi tốc độ xe ảo (`setSimSpeed`) không sinh event nào trên WS, cả ở mock lẫn real, nên phải tự đọc lại. */
  refreshVehicleState: () => void;
  /** Đóng overlay ngay lập tức — chạm ra ngoài scrim, không đợi hẹn giờ. Cũng tắt tiếng nếu VIVI đang đọc. */
  closeVoice: () => void;
  /** true khi audio TTS đang phát — VoiceOverlay dùng để hiện nút "Dừng đọc" (issue #106). */
  speaking: boolean;
  /**
   * Ngắt lời VIVI mà KHÔNG đóng thẻ trả lời — người dùng muốn im tiếng nhưng
   * vẫn đọc tiếp phần chữ. Đóng thẻ (`closeVoice`) cũng tắt tiếng, nhưng lúc đó
   * mất luôn phần chữ.
   */
  stopSpeaking: () => void;
  wakeWordAvailable: boolean;
  wakeWordEnabled: boolean;
  wakeState: WakeState;
  setWakeWordEnabled: (enabled: boolean) => void;
  /**
   * Đang trong cửa sổ nghe tiếp không cần "Hey Vi Vi" (issue #343) — VIVI vừa mời
   * "nghe tiếp?" và mic đang chờ tài xế nói tiếp trong `FOLLOW_UP_WINDOW_MS`. UI
   * dùng để vẽ vòng đếm ngược quanh nút mic; tự tắt khi nghe được tiếng nói, hết
   * giờ, hoặc overlay bị đóng tay.
   */
  followUpWindowActive: boolean;
  /**
   * Đăng ký nhận mức âm lượng mic thật (0..1), cho vạch sóng phản ứng theo
   * giọng nói thay vì nhịp CSS cố định (issue #342). KHÔNG phải React state —
   * mức mới tới nhiều lần/giây (mỗi frame worklet), setState ở tần suất đó sẽ
   * render lại cả overlay. Trả về hàm huỷ đăng ký.
   */
  subscribeMicLevel: (listener: (level: number) => void) => () => void;
  /** null = chưa có lần chạy Routine nào trên phiên này (hoặc đã điều hướng đi rồi quay lại — state KHÔNG persist qua reload). */
  routineExecution: RoutineExecutionState | null;
  /** Preview Routine mới nhất do Agent phân giải; RoutinesView dùng để cuộn/highlight đúng thẻ. */
  routinePreview: ActiveRoutinePreview | null;
  /** #385: voice-run vừa bị chặn vì thiếu địa điểm; RoutinesView dùng để mở đúng hàng Nhà/Cơ quan. */
  routineSetupRequired: ActiveRoutineSetupRequired | null;
}

const DriverShellContext = createContext<DriverShellValue | null>(null);

export function useDriverShell(): DriverShellValue {
  const ctx = useContext(DriverShellContext);
  if (!ctx) throw new Error("useDriverShell phải dùng trong DriverShellProvider");
  return ctx;
}

/**
 * Orchestrator state cho toàn bộ /driver — 1 lần subscribe turnService.subscribe
 * ở đây, mọi component con (StatusBar/Content/RightPanel/Dock/HitlModal/
 * VoiceOverlay) đọc qua useDriverShell() thay vì tự subscribe riêng lẻ.
 */
export function DriverShellProvider({ children }: { children: ReactNode }) {
  const [vehicleState, setVehicleState] = useState<VehicleState | null>(null);
  const [uiPolicy, setUiPolicy] = useState<UiPolicy>(LOCKED_UI_POLICY);
  // Xem docstring ConnectionState. Giữ song song state (để render) và ref (để
  // `send`/`stopVoiceAndSend`/`batDauNghe` đọc — chúng là callback ổn định, cố ý
  // không có `uiPolicy` trong dependency array, nên đọc state React trong đó sẽ
  // luôn thấy giá trị của lần dựng closure, không phải giá trị hiện tại).
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const connectionStateRef = useRef<ConnectionState>("connecting");
  const capNhatKetNoi = useCallback((next: ConnectionState) => {
    connectionStateRef.current = next;
    setConnectionState(next);
  }, []);
  // Hết giờ chờ mà vẫn chưa xác nhận được: hạ xuống `offline` để UI nói đúng sự
  // thật (xem XAC_NHAN_KET_NOI_MS). Không đổi gì về quyền gửi — cả hai trạng
  // thái đều đã bị chặn — chỉ đổi câu chữ hiện cho tài xế.
  useEffect(() => {
    if (connectionState !== "connecting") return;
    const timer = setTimeout(() => capNhatKetNoi("offline"), XAC_NHAN_KET_NOI_MS);
    return () => clearTimeout(timer);
  }, [connectionState, capNhatKetNoi]);
  /**
   * Quyền lái của PHIÊN hiện tại (pool xe ảo, issue #261/ADR-028) — KHÁC lý do
   * khoá của `connectionState`: kết nối vẫn tốt, chỉ là hết xe trong pool.
   * Mặc định `true`/`null` khớp `VEHICLE_POOL_SIZE=1` (pool không cấp phát,
   * không có trần nào để hiện) cho tới khi bootstrap() đọc được phiên thật.
   */
  const [canDrive, setCanDrive] = useState(true);
  const [vehiclePool, setVehiclePool] = useState<VehiclePoolStatus | null>(null);
  const [activeView, setActiveView] = useState<ViewName>("home");
  const [lastTurn, setLastTurn] = useState<LastTurn | null>(null);
  const [turnHistory, setTurnHistory] = useState<string[]>([]);
  const [assistantState, setAssistantState] = useState<AssistantState | null>(null);
  const [pendingApproval, setPendingApproval] = useState<PendingApproval | null>(null);
  const [routineExecution, setRoutineExecution] = useState<RoutineExecutionState | null>(null);
  const [routinePreview, setRoutinePreview] = useState<ActiveRoutinePreview | null>(null);
  const routinePreviewTurnIdsRef = useRef<string[]>([]);
  const applyRoutinePreview = useCallback((turnId: string, preview: RoutinePreview | null | undefined) => {
    if (!preview || routinePreviewTurnIdsRef.current.includes(turnId)) return;
    routinePreviewTurnIdsRef.current = [...routinePreviewTurnIdsRef.current.slice(-(GIOI_HAN_LUOT_CU - 1)), turnId];
    setRoutinePreview({ turnId, preview });
    setActiveView("routines");
  }, []);
  /**
   * Issue #385: voice-run thiếu địa điểm bắt buộc — cùng khuôn `applyRoutinePreview`
   * ngay trên (dedupe theo turnId, mở `RoutinesView`). RoutinesView đọc `setup.thieu`
   * để mở đúng hàng Nhà/Cơ quan trong `PlacesPanel`, không phải cả màn hình trần.
   */
  const [routineSetupRequired, setRoutineSetupRequired] = useState<ActiveRoutineSetupRequired | null>(null);
  const routineSetupRequiredTurnIdsRef = useRef<string[]>([]);
  const applyRoutineSetupRequired = useCallback(
    (turnId: string, setup: RoutineSetupRequired | null | undefined) => {
      if (!setup || routineSetupRequiredTurnIdsRef.current.includes(turnId)) return;
      routineSetupRequiredTurnIdsRef.current = [
        ...routineSetupRequiredTurnIdsRef.current.slice(-(GIOI_HAN_LUOT_CU - 1)),
        turnId,
      ];
      setRoutineSetupRequired({ turnId, setup });
      setActiveView("routines");
    },
    [],
  );
  // `onDriverEvent` được đăng ký một lần, nên cần bản đồng bộ để bỏ qua terminal
  // replay/trễ trước khi chúng phát audio hoặc ngắt lời nói đang có.
  const routineExecutionRef = useRef<RoutineExecutionState | null>(null);
  /**
   * `approval_id` mà tài xế vừa đồng ý bằng lời TRẦN ("ừ", "vâng", "ok") — backend cố
   * ý không chốt (#191), nên còn thiếu đúng một cử chỉ có chủ ý.
   *
   * Giữ `approval_id` chứ không phải `boolean`: một phiên đi qua nhiều lượt S2, và
   * một cờ boolean sót lại từ lượt trước sẽ làm hộp thoại của lượt SAU hiện ra trong
   * trạng thái "đang chờ bạn chạm" ngay từ giây đầu, trước khi tài xế nói gì.
   */
  const [canChamXacNhan, setCanChamXacNhan] = useState<string | null>(null);
  /** Bản ref của `canChamXacNhan` — `onDriverEvent` là closure dựng một lần, đọc state
   * trong đó sẽ luôn thấy giá trị CŨ. Cùng lý do và cùng cặp với `pendingApprovalRef`. */
  const canChamXacNhanRef = useRef<string | null>(null);
  /** Hạ cờ "đang chờ chạm". Một hàm chứ không phải hai lệnh rải rác: ref và state phải
   * đi cùng nhau, lệch nhau là hộp thoại và điều kiện giữ hộp thoại nói hai chuyện. */
  const hetChoCham = useCallback(() => {
    canChamXacNhanRef.current = null;
    setCanChamXacNhan(null);
  }, []);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [transcript, setTranscript] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const planSummaryRef = useRef<string>("");
  /**
   * `stepId` -> bước kế hoạch, ghi lại từ `plan.ready` để tra khi `tool.result` tới.
   *
   * `tool.result` chỉ mang `stepId` và `status`, không mang tool/domain — nên
   * không có bảng này thì không biết bước vừa xong là việc gì.
   */
  const planStepsRef = useRef(new Map<string, PlanReadyStep>());
  /**
   * Mã lỗi của bước `tool.result` gần nhất trong lượt hiện tại (issue #261) —
   * `assistant.response` tới SAU `tool.result` trong pipeline
   * (execute → compose), nên đây là chỗ duy nhất biết cần dịch `displayText`
   * hay không lúc `revealPendingResponse` chạy. Reset về `null` sau khi dùng
   * để không dính sang lượt kế tiếp.
   */
  const lastToolErrorCodeRef = useRef<string | null>(null);
  /**
   * Gộp lời gọi `createDriverSession()` giữa 2 lần React StrictMode double-
   * invoke effect lúc dev (issue #261 — phát hiện lúc pool có trần: mỗi lần
   * tải trang từng âm thầm tạo 2 session, tốn 2 slot pool thay vì 1). Cờ
   * `cancelled` trong effect chỉ chặn CẬP NHẬT STATE sau khi hủy, không chặn
   * được REQUEST đã bắn — cả 2 lần effect đều thấy `getCurrentDriverSession()`
   * là `null` vì lần đầu chưa kịp lưu. Giữ chung 1 Promise ở đây để lần thứ
   * hai CHỜ kết quả lần đầu thay vì tự gọi lại.
   */
  const createSessionPromiseRef = useRef<ReturnType<typeof sessionService.createDriverSession> | null>(null);
  /**
   * Đã tự chuyển màn cho lượt này chưa.
   *
   * Kế hoạch nhiều bước ("bật điều hòa rồi mở nhạc") phải dừng ở màn của bước
   * completed ĐẦU TIÊN có ánh xạ. Không có cờ này thì màn nháy hai lần và tài
   * xế không kịp đọc gì.
   */
  const daChuyenManRef = useRef(false);
  /**
   * Routine có bước `navigation` hoàn tất chưa — đợi tới `routine.finished` mới
   * đổi màn (khác `daChuyenManRef` ở chỗ đó: Routine có panel tiến độ riêng của
   * chính nó — #276 "UI giữ chi tiết" — đổi màn giữa chừng sẽ unmount panel đó,
   * tài xế mất luôn dấu vết các bước còn lại/kết quả cuối. Đợi hết routine mới
   * đổi là đánh đổi có chủ ý: chậm hơn lệnh đơn một nhịp, nhưng không cắt ngang
   * thứ Routine đang cố hiện ra.
   *
   * Lưu `executionId` thay vì boolean thuần: một `routine.step` trễ của lần
   * chạy CŨ có thể tới sau `routine.started` của lần chạy MỚI (#395 review) —
   * nếu chỉ lưu true/false thì `routine.finished` của lần chạy mới sẽ đổi màn
   * nhầm dựa trên bước navigation của lần chạy khác. So khớp executionId ở cả
   * hai đầu (lúc set và lúc đọc) để sự kiện trễ không lẫn giữa hai lần chạy.
   */
  const routineNavCompletedRef = useRef<string | null>(null);
  // Chờ ở đây trước khi gọi send()/openVoice() — tạo session là async (round-trip
  // HTTP thật ở real mode) nhưng UI render xong và bắt tương tác được ngay từ
  // frame đầu. Bấm nút trước khi round-trip xong từng khiến currentSessionId()
  // trong turn/real.ts throw "Chưa có session..." và nuốt vào toast lỗi — chỉ hết
  // khi reload (session đã kịp tạo xong từ lần trước, đọc lại từ localStorage).
  const sessionReadyRef = useRef<Promise<unknown> | null>(null);
  const recorderRef = useRef<WavRecording | null>(null);
  const autoStopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * Người nghe mức mic (issue #342) — `Set` chứ không phải state, vì mức mới tới
   * theo mỗi frame worklet (nhiều lần/giây); qua `subscribeMicLevel` bên dưới,
   * `VoiceOverlay` tự viết thẳng vào CSS custom property trên DOM, không qua
   * setState/re-render.
   */
  const micLevelListenersRef = useRef(new Set<(level: number) => void>());
  const micLevelThrottleAtRef = useRef(0);
  // Đồng bộ thật sự (không như state React, cập nhật ngay lập tức, không đợi
  // batch/render) — cần vì `startWavRecording()` async, khoảng chờ xin quyền
  // mic có thể vài trăm ms tới vài giây; check qua `voiceOpen`/`recorderRef`
  // không đủ, cả hai đều chưa kịp cập nhật trong khoảng chờ đó.
  const voiceStartingRef = useRef(false);
  const [recording, setRecording] = useState(false);
  // Mốc thời gian lần cuối transcript được vẽ lên màn hình — dùng để ép tối
  // thiểu MIN_TRANSCRIPT_VISIBLE_MS trước khi cho câu trả lời thay vào (xem
  // docstring hằng số). null = turn này chưa từng hiện transcript (vd. gửi
  // bằng chữ qua send(), không phải bằng giọng nói) — không cần ép độ trễ.
  const transcriptShownAtRef = useRef<number | null>(null);
  // Bản sao đồng bộ của `pendingApproval` — `onDriverEvent` được tạo lúc
  // effect chạy lần đầu (đóng gói/closure 1 lần) nên đọc thẳng state React
  // trong đó sẽ luôn thấy giá trị CŨ. Cần ref để biết ĐÚNG lúc này overlay có
  // đang bị hộp thoại HITL che hay không (xem revealPendingResponse bên dưới).
  const pendingApprovalRef = useRef<PendingApproval | null>(null);
  /** `approval_id` đã gửi quyết định — chặn gọi REST hai lần cho cùng một phê duyệt.
   *
   * Cần vì event có thể tới hai lần: WS nối lại sẽ **replay** ring buffer (ADR-014), và
   * `approval.intent.detected` là event thật của stream nên nó nằm trong buffer. Gọi
   * `decideApproval` lần thứ hai trên một approval đã consume sẽ trả 409 và bắn toast
   * lỗi cho tài xế, dù chẳng có gì sai. `Set` chứ không phải một biến: một phiên có thể
   * đi qua nhiều lượt S2. */
  const daGuiQuyetDinhRef = useRef<Set<string>>(new Set());
  /**
   * Xin mở lại mic cho phê duyệt đang chờ (#207b). Đổi giá trị `lanMoLaiMic` là tín
   * hiệu **duy nhất** đánh thức effect tự mở mic: `pendingApproval` cố ý giữ nguyên
   * tham chiếu khi lượt trả lời hỏng (xem nhánh `moHoConCho`), mà nó là dependency
   * duy nhất — nên không có cái này thì xe mời "bạn nói lại giúp tôi nhé" vào một
   * cái mic đã tắt, và tài xế không có cách nào biết ngoài việc tự chạm nút.
   *
   * Trần đếm theo TỪNG phê duyệt vì vòng lặp im lặng tự nuôi chính nó: mic mở, không
   * ai nói, `hadSpeech()` false, mở lại. Quá hai lần thì vấn đề không còn nằm ở cách
   * nói, và hộp thoại vẫn ở đó để chạm — đó mới là đường lui đúng.
   */
  const [lanMoLaiMic, setLanMoLaiMic] = useState(0);
  const soLanMoLaiRef = useRef(0);
  const moLaiMicChoRef = useRef<string | null>(null);
  const xinMoLaiMic = useCallback(() => {
    const approval = pendingApprovalRef.current;
    if (!approval) return;
    if (moLaiMicChoRef.current !== approval.approvalId) {
      moLaiMicChoRef.current = approval.approvalId;
      soLanMoLaiRef.current = 0;
    }
    if (soLanMoLaiRef.current >= MAX_MO_LAI_MIC) return;
    soLanMoLaiRef.current += 1;
    setLanMoLaiMic((n) => n + 1);
  }, []);
  // Câu trả lời đã nhận nhưng CHƯA cho hiện — kẹt lại khi overlay đang bị
  // hộp thoại HITL che (lệnh S2). Xem docstring `revealPendingResponse`.
  const pendingResponseRef = useRef<{
    text: string;
    citations: Citation[];
    hasMoreToRead: boolean;
  } | null>(null);
  // Tăng mỗi khi một lượt mới bắt đầu CỤC BỘ (openVoice()/send()) — PM/PO
  // review PR0: câu trả lời của lượt CŨ có thể tới muộn (đang bị hoãn qua
  // afterTranscriptHold) sau khi lượt MỚI đã bắt đầu, ghi đè nhầm UI đang
  // hiện của lượt mới. Không dùng turnId từ server vì cần biết ngay LÚC
  // NGƯỜI DÙNG bắt đầu lượt mới (đồng bộ, không đợi round-trip) — generation
  // cục bộ tăng đúng thời điểm đó, turnId chỉ tới sau qua WS.
  const turnGenerationRef = useRef(0);
  /**
   * turnId của những lượt đã bị một lượt MỚI thay thế — kết quả của chúng không
   * được phép hiện lên nữa.
   *
   * Vì sao `turnGenerationRef` một mình không đủ, dù nó sinh ra đúng để chống ghi
   * đè: nó được **chụp lúc event tới** (`revealPendingResponse(turnGenerationRef.current)`),
   * không phải lúc lượt sinh ra event bắt đầu. Nên khi câu trả lời của lượt 1 tới
   * SAU khi lượt 2 đã bắt đầu, generation chụp được đã là generation của lượt 2 →
   * phép so bằng chính nó → guard cho qua → text của lượt 1 đè lên UI của lượt 2.
   * Đúng ca @danggiap123 báo 24/08: nói "bật điều hòa" (không nhận), nói tiếp "mở
   * cửa" — cửa mở đúng, nhưng màn hình hiện "đã bật điều hòa".
   *
   * `assistant.speech` thì trước đây không có guard NÀO, nên giọng của lượt cũ cũng
   * phát đè lên lượt mới.
   *
   * Lọc theo turnId chữa đúng chỗ đó, vì mọi event lượt đều mang `turnId` sẵn
   * (`lib/services/turn/types.ts`). Hai giới hạn cố ý, cả hai để **không** phá hành
   * vi đang đúng:
   *
   * 1. Chỉ chặn turnId **ta biết chắc là lượt cũ của chính máy này**. Lượt do thiết
   *    bị khác trên cùng session tạo ra mang turnId lạ — không nằm trong tập này —
   *    nên vẫn hiện như cũ (nhánh `turn.accepted` cố ý bắt cả lượt ấy, issue #106).
   * 2. Lượt đang chờ phê duyệt KHÔNG bao giờ vào tập này. Trả lời phê duyệt bằng
   *    lời là một lượt **khác** với lượt đã sinh ra approval; kết quả sau khi duyệt
   *    mang turnId của lượt GỐC, nên xếp lượt gốc vào "đã cũ" là tự cắt mất câu trả
   *    lời của chính việc vừa được đồng ý.
   *
   * Danh sách **có trần** (`GIOI_HAN_LUOT_CU`), không phải `Set` mọc mãi: một phiên IVI
   * chạy suốt chuyến đi, và không có gì dọn nó (điều kiện 3 của review #307). Cũ nhất
   * rụng trước — một turnId đủ già thì mọi event của nó đã tới từ lâu.
   */
  const turnIdDaThayTheRef = useRef<string[]>([]);
  /** turnId của lượt đang chạy do CHÍNH máy này gửi — `null` khi chưa biết. */
  const turnIdHienTaiRef = useRef<string | null>(null);
  /**
   * Máy này vừa bắt đầu một lượt và **chưa** biết turnId của nó.
   *
   * Đây là mảnh còn thiếu của bản đầu, và nó thiếu vì một giả định sai về backend:
   * bản đầu chỉ học turnId từ giá trị `sendText`/`sendVoice` trả về. Với `/turns/voice`
   * (202, bất đồng bộ) thì được — HTTP trả trước mọi event. Với `/turns/text` thì
   * **ngược hẳn**: route đồng bộ, `emit_turn_lifecycle` phát `assistant.response` xong
   * mới trả envelope, nên turnId luôn tới SAU mọi event của chính lượt đó và bộ lọc
   * không bao giờ kịp chạy.
   *
   * Nay `turn.accepted` là mỏ neo (backend phát nó cho cả lượt text từ #307, ngay
   * trước `graph.ainvoke`), còn giá trị HTTP trả về chỉ là đường dự phòng cho lúc
   * WebSocket chưa nối.
   */
  const dangChoTurnIdRef = useRef(false);
  // Audio TTS đang phát (nếu có) — bấm liên tục (vd tăng điều hòa nhiều lần
  // nhanh) từng khiến mỗi `assistant.speech` tạo 1 `Audio` mới và phát chồng
  // lên audio cũ chưa dứt, nghe đè giọng nhau. Giữ đúng 1 audio "đang phát"
  // tại một thời điểm — audio mới tới thì dừng audio cũ trước.
  const activeSpeechRef = useRef<HTMLAudioElement | null>(null);
  // Có đang đọc thành tiếng không — chỉ để VoiceOverlay biết lúc nào hiện nút
  // "Dừng đọc". Không thay được cho `activeSpeechRef`: state React cập nhật
  // theo lượt render, còn các chỗ ngắt lời cần biết NGAY tại thời điểm gọi.
  const [speaking, setSpeaking] = useState(false);
  /**
   * Đếm số lần NGẮT LỜI CHỦ ĐỘNG. Chỉ để đánh thức effect tự đóng overlay.
   *
   * Không dùng thẳng `speaking` làm dependency, dù thoạt nhìn tương đương: audio
   * đọc hết tự nhiên cũng hạ `speaking` xuống false, và lúc đó effect chạy lại
   * sẽ **huỷ luôn cái hẹn giờ mà chính sự kiện `ended` vừa đặt** — overlay treo
   * lại trên màn hình chờ một `ended` thứ hai không bao giờ tới. Bộ đếm này chỉ
   * nhích khi có người/lượt mới cắt ngang, tức đúng trường hợp cần đánh thức.
   */
  const [speechStopCount, setSpeechStopCount] = useState(0);

  // --- Wake word ------------------------------------------------------------
  // Bộ dò tự sở hữu micro RIÊNG (MicrophonePipeline) và tự thu luôn câu lệnh
  // sau khi đánh thức, nên nó KHÔNG dùng chung `recorderRef`/`wavRecorder` với
  // đường chạm-mic. Hai người dùng micro cùng lúc sẽ vọng tiếng vào nhau, nên
  // `batDauNghe` tắt bộ dò trước khi thu tay, và `closeVoice` bật lại.
  const wakeFeatureEnabled = process.env.NEXT_PUBLIC_WAKE_WORD_ENABLED === "true";
  const [wakeWordAvailable, setWakeWordAvailable] = useState(false);
  const [wakeWordEnabled, setWakeWordEnabledState] = useState(wakeFeatureEnabled);
  const [wakeState, setWakeState] = useState<WakeState>("IDLE");
  const wakeControllerRef = useRef<WakeWordController | null>(null);
  const wakeEnabledRef = useRef(wakeFeatureEnabled);
  const wakeCaptureActiveRef = useRef(false);
  const wakeBoundaryNotifiedRef = useRef(false);
  const activeSpeechBoundaryRef = useRef(false);
  /**
   * `hasMoreToRead` của lượt VỪA có `assistant.response` (issue #343) — set ngay khi
   * event đó tới, KHÔNG đợi qua `afterTranscriptHold`/`revealPendingResponse`: bằng lúc
   * `notifyWakeResponseBoundary()` chạy (ở `turn.completed`), reveal có thể chưa xảy ra
   * (câu vừa hiện chưa đủ MIN_TRANSCRIPT_VISIBLE_MS) nên `pendingResponseRef` không phải
   * nguồn đọc lại được ổn định. Reset về `false` ở đúng 3 chỗ `pendingResponseRef.current`
   * bị đặt `null` khi một lượt MỚI bắt đầu — cùng vòng đời, khác biến, vì một lượt điều
   * khiển thuần (không có assistant.response nào) không được giữ giá trị của lượt trước.
   */
  const pendingKeepListeningRef = useRef(false);
  /**
   * Lượt sắp gửi có phải do **cửa sổ nghe tiếp tự bắt** không (spec §3.5) — đi kèm
   * `X-Capture-Mode: auto` để backend **im lặng** thay vì đọc câu từ chối khi không hiểu.
   *
   * Dấu hiệu phân biệt là đường vào `CAPTURING_COMMAND`: cửa sổ nghe tiếp vào thẳng, còn
   * wake word và bấm mic tay đều qua `ARMING` (có beep). Nên bật ở
   * `onFollowUpWindowStarted`, hạ ở `onArming` — không suy ra từ `followUpWindowActive`,
   * vì cờ ấy là **state cho UI** và đã bị dọn trước lúc gửi.
   */
  const batTuDongRef = useRef(false);
  /**
   * Đang trong cửa sổ nghe tiếp (issue #343) — chỉ dùng cho UI (vòng đếm ngược quanh
   * nút mic). Bản thân quyết định "có mở cửa sổ hay không" nằm hết trong
   * WakeWordController; cờ này chỉ phản ánh lại qua onFollowUpWindowStarted/Expired
   * và khi onArming(true) — im lặng đóng lại một khi capture đã thật sự bắt đầu.
   */
  const [followUpWindowActive, setFollowUpWindowActive] = useState(false);

  /** Báo controller rằng TTS đã dứt tiếng — nó chỉ nghe lại sau mốc này, nếu
   * không bộ dò sẽ nghe chính giọng VIVI phát ra loa và tự đánh thức. */
  const notifyWakeTtsEnded = useCallback(() => {
    if (!activeSpeechBoundaryRef.current) return;
    activeSpeechBoundaryRef.current = false;
    wakeControllerRef.current?.ttsEnded();
  }, []);

  /** Mốc "lượt đã có câu trả lời" — controller dùng nó để biết nên chờ TTS hay
   * nghe lại ngay, và (issue #343) có nên mở cửa sổ nghe tiếp sau cooldown hay
   * không. Gọi đúng một lần cho mỗi lượt. */
  const notifyWakeResponseBoundary = useCallback(() => {
    if (wakeBoundaryNotifiedRef.current) return;
    wakeBoundaryNotifiedRef.current = true;
    wakeControllerRef.current?.responseBoundary(activeSpeechRef.current !== null, pendingKeepListeningRef.current);
  }, []);

  /**
   * Ngắt lời: dừng audio TTS đang phát, một chỗ duy nhất cho mọi đường ngắt.
   *
   * `pause()` KHÔNG phát `ended`, nên mọi thứ nghe theo `ended` (hẹn giờ tự
   * đóng overlay) phải tự xoay xở — đó là lý do `speaking` nằm trong dependency
   * của effect tự đóng: dừng tay xong overlay vẫn phải đóng như thường.
   *
   * Bỏ tham chiếu sau khi dừng là bắt buộc, không phải dọn dẹp cho đẹp: giữ lại
   * một `Audio` đã pause thì lần ngắt sau gọi `pause()` trên đúng nó, vô hại,
   * nhưng effect tự đóng lại thấy `audio !== null` và ngồi chờ một `ended`
   * không bao giờ tới.
   */
  const stopSpeech = useCallback(() => {
    const audio = activeSpeechRef.current;
    audio?.pause();
    activeSpeechRef.current = null;
    if (audio) notifyWakeTtsEnded();
    setSpeaking(false);
    setSpeechStopCount((n) => n + 1);
  }, [notifyWakeTtsEnded]);

  // Đóng overlay + dọn lịch sử cùng lúc — dùng ở MỌI nơi đóng overlay (tự
  // động qua audio/hẹn giờ, chạm ra ngoài, hay lỗi/im lặng) thay vì gọi thẳng
  // setVoiceOpen(false), để không nơi nào quên dọn "Giữ lịch sử trong lúc
  // overlay còn mở" — lượt kế tiếp phải bắt đầu sạch, không lưu xuyên suốt cả
  // phiên đăng nhập.
  //
  // Blocker (PM/PO review PR #102, 2026-08-14): trước đây hàm này KHÔNG huỷ
  // bản ghi đang chạy — tap-outside lúc đang thu đóng overlay trên màn hình
  // nhưng mic vẫn ghi ngầm, rồi VAD (onSilenceDetected) hoặc timer
  // MAX_RECORDING_MS vẫn gọi được stopVoiceAndSend() và gửi audio lên BE dù
  // người dùng đã "đóng" từ lâu. `recorder.cancel()` disconnect hẳn
  // AudioWorkletNode (xem wavRecorder.ts::teardown) nên VAD không còn cơ hội
  // bắn onSilenceDetected nữa; clear autoStopTimerRef phòng thêm timer 12s
  // dù về lý thuyết stopVoiceAndSend đã tự no-op khi recorderRef rỗng.
  //
  // Đóng thẻ khi VIVI còn đang đọc cũng phải TẮT TIẾNG (issue #106). Trước đây
  // không tắt: chạm ra ngoài hay bấm X thì thẻ biến mất còn giọng vẫn đọc tiếp
  // tới hết — với câu sổ tay dài (đo được 65,6 giây) thì tài xế mất luôn cả
  // đường thoát cuối cùng, vì thẻ đã không còn để bấm gì nữa.
  const closeVoice = useCallback(() => {
    if (autoStopTimerRef.current) {
      clearTimeout(autoStopTimerRef.current);
      autoStopTimerRef.current = null;
    }
    if (recorderRef.current) {
      recorderRef.current.cancel();
      recorderRef.current = null;
      setRecording(false);
    }
    if (wakeCaptureActiveRef.current) {
      wakeCaptureActiveRef.current = false;
      wakeControllerRef.current?.cancelCapture();
      setRecording(false);
    }
    // Đóng bằng bất kỳ đường nào (tay, hết giờ, lỗi) cũng phải tắt vòng đếm
    // ngược nếu đang hiện — không chỉ riêng đường hết giờ tự nhiên
    // (onFollowUpWindowExpired). setState về cùng giá trị false là no-op rẻ.
    setFollowUpWindowActive(false);
    stopSpeech();
    setVoiceOpen(false);
    setTurnHistory([]);
    // Bật lại bộ dò sau khi overlay đóng hẳn. Không bật sớm hơn: trong lúc
    // overlay còn hiện câu trả lời (và có thể còn đang đọc) mà nghe lại thì
    // giọng VIVI qua loa là thứ đầu tiên micro nghe thấy.
    if (wakeEnabledRef.current) void wakeControllerRef.current?.enable();
  }, [stopSpeech]);

  const refreshVehicleState = useCallback(() => {
    turnService.getVehicleState().then((state) => {
      setVehicleState(state);
    }, (error: unknown) => {
      // API từ chối state khi lease đã hết để không rò state của chiếc xe đã
      // được cấp lại cho người khác. Đây không phải một lỗi poll thoáng qua:
      // xoá state cũ và fail-closed ngay, giống nhánh WS `error` bên dưới.
      if (
        typeof error === "object"
        && error !== null
        && "code" in error
        && error.code === VEHICLE_LEASE_EXPIRED_CODE
      ) {
        setVehicleState(null);
        setCanDrive(false);
        return;
      }
      // Các lỗi poll tạm thời khác tự thử lại ở chu kỳ sau, không spam toast.
    });
  }, []);

  // Trạng thái xe có thể đổi từ NGOÀI thao tác của chính người dùng (console
  // vehicle_sim gõ `speed 45`, hoặc một client khác) — không có sự kiện WS
  // nào báo việc đó (chỉ tool.result sau lệnh của chính mình). Poll định kỳ để
  // FE bắt kịp thay vì im lặng đứng yên tới khi người dùng tự F5. Bỏ qua ở mock
  // vì mock không có nguồn ngoài nào đổi state ngầm — mọi thay đổi ở đó đã tự
  // gọi refreshVehicleState() ngay tại chỗ (xem SpeedDebugDrawer).
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_USE_MOCK_TURN === "false") {
      const timer = setInterval(refreshVehicleState, 2000);
      return () => clearInterval(timer);
    }
  }, [refreshVehicleState]);

  useEffect(() => {
    let cancelled = false;
    let unsubscribe: (() => void) | null = null;

    // `turnService.subscribe()` đọc getCurrentDriverSession() ĐỒNG BỘ ngay lúc
    // gọi — ở lần đăng nhập đầu tiên (chưa có session trong localStorage), gọi
    // nó song song với createDriverSession() (async) khiến nó luôn thấy `null`
    // và tự quyết không mở WebSocket (real.ts:257-262), vĩnh viễn không nhận
    // được turn.completed dù lệnh đã gửi thành công — StatusBar kẹt ở "Đang xử
    // lý…". Phải subscribe SAU khi session chắc chắn đã có, không phải song song.
    async function bootstrap() {
      if (!sessionService.getCurrentDriverSession()) {
        // Lần đầu tạo Promise và giữ lại; lần StrictMode gọi lại (hoặc bất kỳ
        // mount chồng lấn nào khác) sẽ thấy Promise đã có và CHỜ chung, không
        // tự bắn thêm request `POST /sessions`.
        if (!createSessionPromiseRef.current) {
          createSessionPromiseRef.current = sessionService.createDriverSession(DEMO_VEHICLE_ID);
        }
        try {
          await createSessionPromiseRef.current;
        } catch (err) {
          setToast(err instanceof Error ? err.message : "Không tạo được phiên làm việc.");
        } finally {
          createSessionPromiseRef.current = null;
        }
      }
      if (cancelled) return;

      const session = sessionService.getCurrentDriverSession();
      setCanDrive(session?.canDrive ?? true);
      setVehiclePool(session?.pool ?? null);

      refreshVehicleState();
      unsubscribe = turnService.subscribe(onDriverEvent);
    }

    /**
     * Hoãn `run` tới khi transcript đã đứng yên đủ MIN_TRANSCRIPT_VISIBLE_MS
     * — dùng cho `approval.required` (hộp thoại HITL) để KHÔNG che mất
     * transcript ngay khi nó vừa hiện: tài xế phải thấy được "mình vừa nói
     * gì" TRƯỚC khi thấy hộp thoại hỏi xác nhận hành động, không phải nhảy
     * thẳng qua hộp thoại như trước.
     */
    function afterTranscriptHold(run: () => void) {
      const shownAt = transcriptShownAtRef.current;
      const elapsed = shownAt === null ? Infinity : Date.now() - shownAt;
      if (elapsed < MIN_TRANSCRIPT_VISIBLE_MS) {
        setTimeout(run, MIN_TRANSCRIPT_VISIBLE_MS - elapsed);
      } else {
        run();
      }
    }

    /**
     * Cho câu trả lời đang kẹt (`pendingResponseRef`, nếu có) hiện ra — hoặc
     * hoãn lại nếu chưa đủ điều kiện. Gọi lại ở 2 nơi: ngay khi
     * `assistant.response` tới, và lại lần nữa khi `pendingApproval` vừa
     * được gỡ (turn.completed/canceled/failed) — lệnh S2 khiến overlay bị
     * hộp thoại HITL che, `assistant.response` có thể tới trong lúc đó.
     *
     * KHÔNG reset lại đồng hồ `transcriptShownAtRef` ở đây (khác bản trước) —
     * `approval.required` giờ đã tự hoãn qua `afterTranscriptHold` TRƯỚC KHI
     * hiện hộp thoại, nên tới lúc hộp thoại đóng, transcript chắc chắn đã
     * đứng đủ MIN_TRANSCRIPT_VISIBLE_MS từ trước rồi (cộng thêm thời gian
     * tài xế cân nhắc duyệt/từ chối) — reset lại chỉ khiến transcript hiện
     * thêm 1 lần nữa sau khi hộp thoại đóng, dư thừa và chậm vô ích.
     *
     * `generation`: chụp `turnGenerationRef.current` lúc GỌI hàm này (không
     * phải lúc apply) — nếu một lượt mới bắt đầu trong lúc đang hoãn (tài xế
     * bấm mic/gõ lệnh tiếp trước khi hoãn xong), generation lúc apply sẽ khác
     * với generation đã chụp, và ta bỏ câu trả lời cũ thay vì ghi đè UI của
     * lượt mới (PM/PO review PR0, điểm 2).
     */
    function revealPendingResponse(generation: number) {
      const response = pendingResponseRef.current;
      if (response === null) return;
      if (pendingApprovalRef.current) return; // vẫn đang bị hộp thoại HITL che — chờ lần gọi sau
      // Lệnh bị chặn vì hết pool xe ảo (issue #261): ưu tiên câu dịch sẵn của
      // FE thay vì hiện thẳng displayText backend — hợp đồng #259 chỉ đóng
      // băng error_code, không đóng băng chữ compose.py soạn cho ca này.
      const bLoaiViHetPool = lastToolErrorCodeRef.current === VEHICLE_POOL_EXHAUSTED_CODE;
      lastToolErrorCodeRef.current = null;
      const { citations, hasMoreToRead } = response;
      const text = bLoaiViHetPool ? VEHICLE_POOL_EXHAUSTED_MESSAGE : response.text;
      afterTranscriptHold(() => {
        pendingResponseRef.current = null;
        if (generation !== turnGenerationRef.current) return; // lượt đã đổi — bỏ, không ghi đè UI lượt mới
        setLastTurn((prev) => ({ user: prev?.user ?? "", vivi: text, citations, hasMoreToRead }));
        setToast(text);
        transcriptShownAtRef.current = null;
      });
    }

    /**
     * Kết quả này thuộc về một lượt đã bị lượt khác thay thế?
     *
     * Chỉ dùng cho hai event **ghi đè UI kết quả**: `assistant.response` (chữ trên
     * màn) và `assistant.speech` (giọng đọc). Cố ý KHÔNG lọc đại trà mọi event:
     *
     * - `ui.policy` không thuộc lượt nào (`turn_id` luôn null ở wire format) —
     *   `types.ts` ghi rõ đừng lọc nó theo turnId;
     * - `turn.accepted` cố ý bắt cả lượt do thiết bị khác trên cùng session tạo ra,
     *   để máy này im tiếng khi nơi khác bắt đầu nói (issue #106);
     * - `tool.result` / `plan.ready` điều khiển màn theo việc **đã thật sự xảy ra**;
     *   ca 24/08 là việc đúng mà chữ sai, nên chữ mới là chỗ phải sửa.
     */
    function laKetQuaLuotDaCu(turnId: string): boolean {
      // Lượt hiện tại thắng danh sách "đã thay thế": nếu server cấp lại đúng id ấy cho
      // lượt đang chạy thì nó không còn là lượt cũ nữa.
      if (turnId === turnIdHienTaiRef.current) return false;
      return turnIdDaThayTheRef.current.includes(turnId);
    }

    function onDriverEvent(event: DriverEvent) {
      switch (event.type) {
        case "approval.intent.detected": {
          // Ba nhánh theo `committed`, xem docstring trường ấy trong
          // `lib/services/turn/types.ts` cho bảng đầy đủ.
          //
          // #191 dựng một cổng bất đối xứng ở BE: đồng ý TRẦN ("ừ", "vâng", "ok") cố
          // ý không được chốt, chỉ cụm rõ ràng mới chốt. Nhánh dưới đây — viết từ
          // #147, hồi BE chưa tự chốt gì — gọi REST cho MỌI event, nên nó chốt hộ
          // đúng cái BE vừa từ chối chốt và vô hiệu hoá toàn bộ phần an toàn ấy
          // (issue #207). Suite FE vẫn xanh suốt thời gian đó vì không test nào
          // nhìn vào chuyện "ai chốt".
          if (event.committed === true) {
            // BE chốt rồi. Gọi thêm REST không sinh lỗi hiển thị — `store.decide()`
            // idempotent và cổng `previous_status == "pending"` chặn resume lần hai —
            // nhưng vẫn là một request thừa cho một quyết định đã xong.
            return;
          }
          if (event.committed === false && event.decision === "approve") {
            // Cố ý KHÔNG chốt. Đây không phải lỗi và cũng không phải im lặng bỏ qua:
            // `api_spec.md` chốt là IVI làm nổi nút để tài xế xác nhận bằng một cử
            // chỉ có chủ ý. Tự gọi REST ở đây là dựng lại đúng lỗ hổng #207.
            canChamXacNhanRef.current = event.approvalId;
            setCanChamXacNhan(event.approvalId);
            return;
          }
          // `committed === undefined` — BE chưa có phần #207. Giữ nguyên hành vi cũ
          // của #147, không thì FE merge trước BE sẽ làm lời đồng ý trần rơi vào
          // khoảng trống: không ai chốt, trong khi xe vừa đọc "Tôi sẽ thực hiện ngay".
          //
          // `committed === false && decision === "reject"` không rơi xuống đây được:
          // BE chốt MỌI cụm từ chối, nên cặp ấy không tồn tại. Nếu nó xuất hiện thật
          // thì gọi REST vẫn là phản ứng đúng — từ chối là kết quả an toàn.
          if (daGuiQuyetDinhRef.current.has(event.approvalId)) return;
          daGuiQuyetDinhRef.current.add(event.approvalId);
          turnService
            .decideApproval(event.approvalId, event.decision, event.approvedVehicleStateVersion)
            .catch((err) => {
              // Cho phép thử lại: quyết định chưa được ghi nhận thì tài xế phải còn
              // đường bấm nút.
              daGuiQuyetDinhRef.current.delete(event.approvalId);
              setToast(err instanceof Error ? err.message : "Không gửi được quyết định.");
            });
          return;
        }
        case "turn.accepted":
          // Đây là **mỏ neo** để biết turnId của lượt vừa gửi, và nó tới ngay đầu lượt
          // — sớm hơn hẳn giá trị HTTP trả về, thứ mà với `/turns/text` còn tới sau cả
          // `assistant.response` (xem `dangChoTurnIdRef`).
          //
          // Chỉ nhận khi máy này **đang chờ** id: một `turn.accepted` tới lúc không chờ
          // là lượt của thiết bị khác trên cùng session, và gán nó làm "lượt hiện tại"
          // là tự nhận vơ một lượt mình không gửi.
          if (dangChoTurnIdRef.current) {
            dangChoTurnIdRef.current = false;
            turnIdHienTaiRef.current = event.turnId;
          }
          // Lượt mới đã được server nhận — im ngay, đừng đọc nốt câu của lượt
          // trước (issue #106). `send()`/`openVoice()` đã ngắt lời từ phía
          // client rồi, nhưng chỉ cho lượt do CHÍNH máy này bắt đầu; nhánh này
          // bắt cả lượt tới từ nơi khác trên cùng session.
          stopSpeech();
          break;
        case "assistant.status":
          setAssistantState(event.state);
          break;
        case "transcript.partial":
        case "transcript.final":
          setTranscript(event.text);
          transcriptShownAtRef.current = Date.now();
          break;
        case "plan.ready":
          planSummaryRef.current = event.summary;
          // GHI NHỚ, KHÔNG ĐỔI MÀN. `plan.ready` thuộc giai đoạn định tuyến,
          // phát TRƯỚC khi rẽ nhánh chính sách, nên nó bắn cho cả lượt S3. Đổi
          // màn ở đây thì nói "mở YouTube" lúc xe đang chạy sẽ mở video xong
          // rồi mới bị chặn — luật an toàn thành trang trí (issue #174).
          planStepsRef.current = new Map(event.steps.map((step) => [step.stepId, step]));
          daChuyenManRef.current = false;
          break;
        case "approval.required": {
          notifyWakeResponseBoundary();
          const approval = {
            approvalId: event.approvalId,
            approvedVehicleStateVersion: event.approvedVehicleStateVersion,
            summary: planSummaryRef.current,
            expiresAt: event.expiresAt,
            turnId: event.turnId,
          };
          const generation = turnGenerationRef.current;
          // Hộp thoại HITL che overlay ngay khi pendingApproval được set — đợi
          // transcript đứng yên đủ lâu trước đã, không thì tài xế chưa kịp đọc
          // "mình vừa nói gì" đã bị nhảy thẳng sang hộp thoại xác nhận.
          afterTranscriptHold(() => {
            // Lượt đã đổi trong lúc hoãn — hộp thoại này thuộc lượt CŨ, bỏ
            // (cùng lý do generation check ở revealPendingResponse).
            if (generation !== turnGenerationRef.current) return;
            pendingApprovalRef.current = approval;
            setPendingApproval(approval);
          });
          break;
        }
        case "assistant.speech": {
          // Giọng của một lượt đã bị thay thế thì không được phát: trước đây nhánh
          // này KHÔNG có guard nào, nên câu trả lời cũ vẫn đọc đè lên lượt mới.
          if (laKetQuaLuotDaCu(event.turnId)) break;
          // Best-effort (issue #66) — phát trước assistant.response cùng
          // turn. `new Audio(...).play()` có thể bị trình duyệt chặn nếu
          // trang chưa từng có tương tác người dùng nào (autoplay policy);
          // nuốt lỗi, không chặn/ảnh hưởng phần text vẫn hiện bình thường.
          // Dừng audio TRƯỚC đó (nếu còn đang phát dở) trước khi phát audio
          // mới — không thì 2 lượt liên tiếp (vd bấm tăng điều hòa nhiều lần
          // nhanh) phát chồng giọng lên nhau.
          stopSpeech();
          const audio = new Audio(`data:${event.mimeType};base64,${event.audioBase64}`);
          activeSpeechRef.current = audio;
          activeSpeechBoundaryRef.current = true;
          setSpeaking(true);
          // Đọc xong/lỗi thì hạ cờ để nút "Dừng đọc" biến đi — nút còn đó
          // trong khi đã im tiếng là nói dối người dùng về trạng thái hệ thống.
          const clearSpeaking = () => {
            setSpeaking(false);
            // KHÔNG xoá `activeSpeechRef` ở đây. Một bản trước của dòng này có
            // xoá, và nó phá hai hành vi mà develop đã khoá bằng test: sau khi
            // `ended` bắn, ref vẫn phải giữ element để (a) `stopSpeech` của
            // lượt sau còn cái để `pause()` — không thì hai giọng chồng nhau,
            // và (b) `shouldStartCloseTimerImmediately` còn đọc được `.ended`.
            // `notifyWakeTtsEnded` tự chống gọi lặp bằng activeSpeechBoundaryRef.
            notifyWakeTtsEnded();
          };
          audio.addEventListener("ended", clearSpeaking, { once: true });
          audio.addEventListener("error", clearSpeaking, { once: true });
          // Optional chaining phòng môi trường không trả Promise chuẩn (jsdom
          // trong test) — trình duyệt thật luôn trả Promise theo spec.
          audio.play()?.catch(clearSpeaking);
          break;
        }
        case "assistant.response":
          // Câu trả lời tới muộn của một lượt đã bị thay thế — bỏ hẳn, đừng nhét vào
          // `pendingResponseRef`: để đó thì `turn.completed` của lượt MỚI sẽ gọi
          // `revealPendingResponse` và hiện nó ra, đúng bug đang sửa.
          if (laKetQuaLuotDaCu(event.turnId)) break;
          applyRoutinePreview(event.turnId, event.result.routinePreview);
          applyRoutineSetupRequired(event.turnId, event.result.routineSetupRequired);
          pendingResponseRef.current = {
            text: event.result.displayText,
            citations: event.result.citations,
            hasMoreToRead: event.result.hasMoreToRead,
          };
          // Đọc ở notifyWakeResponseBoundary (turn.completed) — KHÔNG đợi reveal, xem
          // docstring pendingKeepListeningRef (issue #343).
          pendingKeepListeningRef.current = event.result.moMicNgan;
          revealPendingResponse(turnGenerationRef.current);
          break;
        case "error": {
          // #351: mất xe giữa chừng KHÔNG kết thúc lượt (terminal: false) — lượt
          // vẫn trả lời tiếp ngay sau đó, nên đẩy câu báo mất xe vào lastTurn.vivi
          // rồi để câu trả lời thật đè lên chỉ tạo một nháy hình vô ích. Toast là
          // đủ cho cảnh báo này; mọi mã lỗi khác (đều terminal) giữ nguyên hành vi cũ.
          const matXeGiuaChung = event.code === VEHICLE_LEASE_EXPIRED_CODE;
          if (matXeGiuaChung) setCanDrive(false);
          if (!matXeGiuaChung) {
            setLastTurn((prev) => ({ user: prev?.user ?? "", vivi: event.message, citations: [], hasMoreToRead: false }));
          }
          setToast(event.message);
          break;
        }
        case "tool.result": {
          refreshVehicleState();
          lastToolErrorCodeRef.current = event.errorCode;
          // Chỉ `completed` mới đổi màn: đây là mốc duy nhất chứng minh việc đã
          // thật sự xảy ra. Bước bị từ chối hoặc lượt dừng ở `action.blocked`
          // không bao giờ tới đây, nên màn giữ nguyên — đó là hành vi đúng.
          if (event.status !== "completed" || daChuyenManRef.current) break;
          // Không có bước tương ứng nghĩa là `tool.result` tới mà không có
          // `plan.ready` đi trước — không đoán, giữ nguyên màn đang xem.
          const step = planStepsRef.current.get(event.stepId);
          const view = step ? viewForStep(step) : null;
          if (view) {
            daChuyenManRef.current = true;
            setActiveView(view);
          }
          break;
        }
        case "routine.started":
          // Thay thế hoàn toàn, không merge — một lần chạy mới bắt đầu nghĩa
          // là lần trước (nếu còn) đã không còn là "gần nhất" (#292).
          routineNavCompletedRef.current = null;
          const startedRoutine: RoutineExecutionState = {
            executionId: event.executionId,
            routineId: event.routineId,
            routineName: event.routineName,
            routineVersion: event.routineVersion,
            steps: event.steps,
            stepResults: {},
            startedAt: event.startedAt,
            terminal: null,
          };
          routineExecutionRef.current = startedRoutine;
          setRoutineExecution(startedRoutine);
          break;
        case "routine.step":
          {
            const prev = routineExecutionRef.current;
            // Bỏ qua nếu không khớp execution đang theo dõi — phòng event
            // trễ của một lần chạy cũ tới sau khi lần chạy mới đã bắt đầu.
            if (!prev || prev.executionId !== event.executionId) break;
            // Ghi nhớ, chưa đổi màn — xem lý do ở `routineNavCompletedRef` (#294 review).
            //
            // Đặt SAU cổng khớp execution ngay trên, và đó là toàn bộ nội dung
            // của vòng 2 review #395: bản trước đánh dấu TRƯỚC cổng, nên một bước
            // navigation trễ của lần chạy cũ vẫn để lại dấu, rồi `routine.finished`
            // trễ của chính nó tự khớp với dấu ấy và cướp màn của lần chạy đang chạy.
            if (event.action === "navigation" && event.status === "completed") {
              routineNavCompletedRef.current = event.executionId;
            }
            const next = {
              ...prev,
              stepResults: {
                ...prev.stepResults,
                [event.index]: {
                  index: event.index,
                  action: event.action,
                  status: event.status,
                  description: event.description,
                  errorCode: event.errorCode,
                  approvalId: event.approvalId,
                },
              },
            };
            routineExecutionRef.current = next;
            setRoutineExecution(next);
          }
          break;
        case "routine.finished":
          {
            const prev = routineExecutionRef.current;
            // `routine.finished` có thể tới lại khi reconnect/replay. Chỉ terminal
            // của lần chạy đang hiện và chưa kết thúc mới được đổi UI hay phát tiếng.
            if (!prev || prev.executionId !== event.executionId || prev.terminal) break;
            const next = {
              ...prev,
              terminal: { status: event.status, terminalReason: event.terminalReason, completedAt: event.completedAt },
            };
            routineExecutionRef.current = next;
            setRoutineExecution(next);
            // Đổi màn Bản đồ ở ĐÂY, sau cổng trên — cùng cổng đang bảo vệ audio
            // khỏi replay (#396) thì cũng bảo vệ luôn phép đổi màn: terminal trễ
            // của lần chạy cũ và terminal phát lại của chính lần chạy này đều
            // dừng ở `break` phía trên, không tới được dòng nào dưới đây.
            if (routineNavCompletedRef.current === event.executionId) {
              routineNavCompletedRef.current = null;
              setActiveView("map");
            }
          // Câu tổng kết đọc to (issue #396) — `null` khi TTS lỗi/rỗng (fail-open
          // phía backend), im lặng bỏ qua như `assistant.speech` vẫn làm.
          //
          // CỐ Ý không gọi `notifyWakeTtsEnded()`/không đụng máy trạng thái
          // `WakeWordController` ở đây: audio này không đi qua `responseBoundary()`
          // của một turn, nên mic KHÔNG biết Routine đang nói — chưa có bảo vệ
          // self-echo nào cho tiếng nói này. Đây đúng là khoảng trống #277/#294
          // cần đo sau khi tính năng này merge, không giải quyết trong #396.
          if (event.audioBase64 && event.mimeType) {
            stopSpeech(); // dừng audio lượt trước nếu còn, không phát chồng
            const audio = new Audio(`data:${event.mimeType};base64,${event.audioBase64}`);
            activeSpeechRef.current = audio;
            audio.addEventListener("ended", () => {
              if (activeSpeechRef.current === audio) activeSpeechRef.current = null;
            });
            audio.play().catch(() => {});
          }
          }
          break;
        case "ui.policy":
          // Đây là chỗ DUY NHẤT biết được kênh sự kiện còn sống hay đã đứt:
          // `controlsLocked` chỉ true ở nhánh close/lỗi xác thực của real.ts,
          // còn mọi `ui.policy` thật từ backend đều mang false (xem
          // UiPolicy.controlsLocked). Nhận được sự kiện này = đã xác nhận.
          capNhatKetNoi(event.uiPolicy.controlsLocked ? "offline" : "online");
          setUiPolicy(event.uiPolicy);
          break;
        case "turn.completed":
        case "turn.canceled":
        case "turn.failed": {
          // Trong thân chung, không ở nhãn "turn.completed": vào bằng nhãn
          // "turn.canceled"/"turn.failed" sẽ nhảy qua mọi câu lệnh đặt trên
          // dấu `{`, nên đặt ở đó thì hai lối kết thúc kia im lặng và bộ dò
          // ngồi chờ một mốc không bao giờ tới.
          notifyWakeResponseBoundary();
          // Thiếu "turn.failed" ở đây trước đây khiến voice overlay treo vĩnh
          // viễn: audio rỗng (chưa ghi âm thật, xem openVoice()) luôn kết thúc
          // bằng turn.failed sau khi backend validate audio thất bại — event
          // "error" đã set toast đúng nội dung, chỉ thiếu đóng overlay.
          //
          // Nhưng một lượt kết thúc KHÔNG có nghĩa approval kết thúc: lượt trả lời
          // phê duyệt bằng lời là một lượt khác với lượt đã tạo ra approval. Câu mơ
          // hồ ("Đồng ý nhưng hủy") kết lượt ấy bằng turn.failed trong khi approval
          // vẫn treo nguyên phía server, nên xoá hộp thoại ở đây là cắt mất đường
          // duy nhất để tài xế quyết — và vì mỗi phiên chỉ được một approval chờ,
          // họ cũng không ra được lệnh S2 nào khác cho tới lúc nó hết hạn.
          // `api_spec.md:643` và #147 chốt: giữ hộp thoại, mời nói lại.
          const moHoConCho = event.type === "turn.failed" && event.code === "APPROVAL_INTENT_AMBIGUOUS";
          // Ca thứ HAI của cùng một luật, thêm ở #207: đồng ý bằng lời trần kết lượt
          // handoff bằng `turn.completed` **bình thường** — không mơ hồ, không lỗi —
          // trong khi backend cố ý chưa chốt gì và approval còn treo nguyên ở server.
          // Xoá hộp thoại ở đây là lấy nốt đường cuối cùng để tài xế quyết, rồi khoá
          // luôn phiên khỏi mọi lệnh S2 khác cho tới lúc nó hết hạn (mỗi phiên chỉ
          // được một approval chờ). Đúng thứ đoạn trên vừa mô tả, chỉ khác lối vào.
          const choChamConCho = canChamXacNhanRef.current === pendingApprovalRef.current?.approvalId;
          // Và đây là **luật chung** mà hai ca trên chỉ là hai trường hợp riêng: hộp
          // thoại chỉ được đóng bởi sự kiện terminal của **chính lượt đã sinh ra nó**.
          //
          // Trước bản này, MỌI lượt kết thúc đều đóng hộp thoại — kể cả một câu hỏi sổ
          // tay, một câu tán gẫu, hay một lượt ghi âm hỏng. Tài xế nói chệch một câu
          // giữa lúc chờ duyệt là hộp thoại biến mất, phê duyệt vẫn treo nguyên ở
          // server, và mọi lệnh S2 sau đó nhận "Đang có một lệnh chờ bạn xác nhận" cho
          // tới lúc nó hết hạn 30 giây. Đo được trên máy thật 20/08.
          //
          // Vòng đời đúng: `approve` -> lượt gốc resume rồi `turn.completed`; `reject`
          // -> `turn.canceled(approval_rejected)` của lượt gốc; hết hạn -> không có
          // event nào, nên effect hết-hạn bên dưới lo. Cả ba đều mang `turn_id` của
          // lượt gốc, nên phép so này không cắt mất đường đóng nào.
          const cuaLuotNay = event.turnId === pendingApprovalRef.current?.turnId;
          if (moHoConCho) {
            // Backend vừa mời "bạn nói lại giúp tôi nhé" — mời vào một cái mic
            // đang mở, không phải vào chỗ trống (#207b). Giữ hộp thoại thôi thì
            // chưa đủ: mic đã tắt từ lúc `stopVoiceAndSend`, và `pendingApproval`
            // không đổi tham chiếu nên effect tự mở mic không hề chạy lại.
            //
            // Nhánh `choChamConCho` (tiếng trần, backend cố ý chưa chốt) **không** mở
            // lại mic: nó đã chuyển sang trạng thái chờ chạm của #208. Câu backend đọc
            // lên lại mời cả hai đường ("nói đồng ý **hoặc** chạm nút") — chỗ lệch ấy
            // tách riêng, xem ghi chú ở #211.
            xinMoLaiMic();
          } else if (!choChamConCho && cuaLuotNay) {
            pendingApprovalRef.current = null;
            setPendingApproval(null);
            // Dọn cùng lúc với chính approval nó nói về. Để sót thì lượt S2 sau
            // hiện hộp thoại đã ở trạng thái "đang chờ bạn chạm" từ giây đầu.
            hetChoCham();
          }
          setAssistantState(null);
          setPending(false);
          refreshVehicleState();
          // Lệnh S2: assistant.response tới lúc hộp thoại HITL còn che overlay
          // nên bị revealPendingResponse() giữ lại (xem hàm đó) — gỡ approval
          // xong thì thử hiện tiếp nếu còn kẹt (thường chạy ngay, không hoãn
          // thêm — xem docstring revealPendingResponse).
          revealPendingResponse(turnGenerationRef.current);
          break;
        }
        default:
          break;
      }
    }

    sessionReadyRef.current = bootstrap();

    return () => {
      cancelled = true;
      unsubscribe?.();
    };
  }, [refreshVehicleState, stopSpeech, xinMoLaiMic, hetChoCham, capNhatKetNoi, applyRoutinePreview, applyRoutineSetupRequired]);

  /**
   * Lượt mới bắt đầu — xếp lượt đang chạy vào "đã bị thay thế".
   *
   * Gọi ở đúng ba chỗ tăng `turnGenerationRef` (gõ chữ, chạm mic, wake word), và
   * **không** ở nhánh `choDuyet` của `openVoice`: ở đó tài xế đang trả lời chính
   * lượt hiện tại chứ không bắt đầu lượt khác.
   */
  const themLuotCu = useCallback((turnId: string) => {
    const ds = turnIdDaThayTheRef.current;
    if (turnId === pendingApprovalRef.current?.turnId || ds.includes(turnId)) return;
    ds.push(turnId);
    if (ds.length > GIOI_HAN_LUOT_CU) ds.shift();
  }, []);

  const danhDauLuotCu = useCallback(() => {
    const dangChay = turnIdHienTaiRef.current;
    if (dangChay !== null) themLuotCu(dangChay);
    turnIdHienTaiRef.current = null;
    // Lượt mới bắt đầu chờ turnId của nó. Đặt cờ ở đây — đồng bộ, ngay lúc người
    // dùng bấm — chứ không đợi `sendText`/`sendVoice` trả về: đúng cái độ trễ ấy là
    // thứ làm bản đầu bỏ lọt race.
    dangChoTurnIdRef.current = true;
  }, [themLuotCu]);

  /**
   * Ghi `turnId` server trả về cho lượt vừa gửi.
   *
   * Nhận `string | undefined` và bỏ qua `undefined` **có chủ ý** — không destructure
   * `{ turnId }` tại chỗ gọi. Lý do không phải phòng xa: chuỗi promise này kết bằng
   * một `.catch` hiển thị "Không gửi được lệnh" và đóng overlay giọng nói, nên một
   * `TypeError` do phản hồi thiếu trường sẽ bị báo cho tài xế như một lỗi gửi —
   * trong khi lệnh đã gửi đi rồi và xe vẫn sẽ làm. Ghi nhận turnId là việc phụ; nó
   * không được quyền làm hỏng lượt. (Bản đầu của thay đổi này destructure và làm đỏ
   * đúng hai test overlay-đóng-theo-audio vì `sendVoice` giả trả `undefined`.)
   *
   * **Đường dự phòng, không phải đường chính.** Mỏ neo chính là `turn.accepted` trên
   * WebSocket (xem `dangChoTurnIdRef`); hàm này chỉ cứu trường hợp WS chưa nối kịp.
   *
   * Nhận `theHe` — generation chụp **tại lúc gửi**, không phải lúc promise trả về. Đây
   * là điều kiện approve #2 của review #307: một id về muộn có thể đã thuộc lượt cũ, và
   * cách duy nhất biết chắc là so với generation của chính lời gọi đã sinh ra nó. So
   * với `turnIdHienTaiRef.current === null` như bản đầu thì không đủ — lượt mới cũng
   * đặt ref ấy về `null`, nên id cũ đi vào đúng ô của lượt mới.
   */
  const ghiNhanTurnId = useCallback(
    (turnId: string | undefined, theHe: number) => {
      if (turnId === undefined) return;
      if (theHe !== turnGenerationRef.current) {
        // Lượt sinh ra id này đã bị thay thế trong lúc chờ HTTP.
        themLuotCu(turnId);
        return;
      }
      if (dangChoTurnIdRef.current) {
        dangChoTurnIdRef.current = false;
        turnIdHienTaiRef.current = turnId;
      } else if (turnIdHienTaiRef.current !== turnId) {
        themLuotCu(turnId);
      }
    },
    [themLuotCu],
  );

  const send = useCallback((text: string) => {
    // Fail-closed (issue #241, UAT-008): trước đây fetch() cứ bắn thẳng lên
    // network dù backend đã chết, ra ERR_CONNECTION_REFUSED giữa chừng thay vì
    // chặn ở đây. Điều kiện là "CHƯA xác nhận online", không phải "đã xác nhận
    // offline" — cold start với backend chết sẵn nằm ở `connecting`, và đó
    // chính là ca UAT-008 mà bản đầu của PR này còn để lọt.
    const ketNoi = connectionStateRef.current;
    if (ketNoi !== "online") {
      setToast(TOAST_CHUA_ONLINE[ketNoi]);
      return;
    }
    // Lượt mới bắt đầu — vô hiệu hoá ngay câu trả lời/hộp thoại còn kẹt lại
    // từ lượt trước (xem turnGenerationRef và turnIdDaThayTheRef).
    turnGenerationRef.current += 1;
    const theHe = turnGenerationRef.current;
    danhDauLuotCu();
    pendingResponseRef.current = null;
    pendingKeepListeningRef.current = false;
    // Dừng audio TTS của lượt cũ (nếu còn phát dở) — không thì nó phát mồ côi
    // trong nền chồng lên lượt mới.
    stopSpeech();
    setLastTurn({ user: text, vivi: null, citations: [], hasMoreToRead: false });
    setPending(true);
    Promise.resolve(sessionReadyRef.current)
      .then(() => turnService.sendText(text))
      .then((ketQua) => {
        ghiNhanTurnId(ketQua?.turnId, theHe);
        if (theHe === turnGenerationRef.current && ketQua?.turnId) {
          applyRoutinePreview(ketQua.turnId, ketQua.routinePreview);
          applyRoutineSetupRequired(ketQua.turnId, ketQua.routineSetupRequired);
        }
      })
      .catch((err) => {
        setPending(false);
        setToast(err instanceof Error ? err.message : "Không gửi được lệnh.");
      });
  }, [stopSpeech, danhDauLuotCu, ghiNhanTurnId, applyRoutinePreview, applyRoutineSetupRequired]);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3200);
    return () => clearTimeout(timer);
  }, [toast]);

  // Dừng ghi (chạm lại mic trong overlay, hoặc hết MAX_RECORDING_MS) rồi gửi
  // WAV thật lên BE — sau bước này UI mới chuyển sang state machine
  // transcribing→...→composing dẫn dắt bởi assistant.status thật.
  const stopVoiceAndSend = useCallback(() => {
    if (autoStopTimerRef.current) {
      clearTimeout(autoStopTimerRef.current);
      autoStopTimerRef.current = null;
    }
    const recorder = recorderRef.current;
    if (!recorder) return;
    recorderRef.current = null;
    setRecording(false);
    const ketNoiLucDung = connectionStateRef.current;
    if (ketNoiLucDung !== "online") {
      // Cùng lý do fail-closed của send() ở trên (issue #241, UAT-008) — không
      // gửi WAV lên một backend chưa xác nhận được là còn sống, và phải đóng
      // overlay tường minh (không có event WS nào sẽ tới để tự đóng nó).
      recorder.cancel();
      closeVoice();
      setToast(TOAST_CHUA_ONLINE[ketNoiLucDung]);
      return;
    }
    if (!recorder.hadSpeech()) {
      // Cả đoạn ghi chỉ toàn im lặng/ồn nền (chạm dừng quá sớm, hoặc hết
      // MAX_RECORDING_MS mà chưa nói gì) — không gửi lên BE tốn 1 lượt STT
      // vô ích, báo thẳng để người dùng biết cần nói lại.
      recorder.cancel();
      closeVoice();
      setToast("Mình chưa nghe rõ, bạn thử nói lại nhé.");
      // Còn phê duyệt đang chờ thì mời lại bằng mic, không bắt chạm nút (#207b).
      // Ca này KHÔNG gửi gì lên BE, nên không có sự kiện nào từ server để dựa
      // vào — chỉ nghe `turn.failed` thì nó rơi vào khoảng trống.
      xinMoLaiMic();
      return;
    }
    setPending(true);
    // Generation của lượt ĐANG gửi — `openVoice` đã tăng nó lúc mở mic. Chụp tại đây,
    // trước `await`, vì đó là mốc duy nhất so được khi promise trả về muộn.
    const theHe = turnGenerationRef.current;
    // recorder.stop() là async — đợi nốt buffer PCM cuối cùng từ
    // AudioWorkletNode (postMessage không đồng bộ với disconnect, xem
    // wavRecorder.ts) trước khi encode WAV.
    recorder
      .stop()
      // Đường này là tài xế tự bấm mic hoặc gõ — không bao giờ là bắt tự động.
      .then((wavBlob) => Promise.resolve(sessionReadyRef.current).then(() => turnService.sendVoice(wavBlob, { auto: false })))
      .then((ketQua) => ghiNhanTurnId(ketQua?.turnId, theHe))
      .catch((err) => {
        // Gửi thất bại (mất mạng, chưa có session, BE tắt...) — vẫn phải đóng
        // overlay, không thì nó đứng yên mãi ở trạng thái "chưa ghi" (không
        // recording, không assistantState, không lastTurn) vì không còn gì
        // khác điều khiển voiceOpen nữa. Toast báo lỗi đã đủ, không cần giữ
        // overlay mở chờ một sự kiện WS sẽ không bao giờ tới.
        setPending(false);
        closeVoice();
        setToast(err instanceof Error ? err.message : "Không gửi được lệnh giọng nói.");
      });
  }, [closeVoice, xinMoLaiMic, ghiNhanTurnId]);

  /**
   * Mở mic. `choDuyet` = mở để **trả lời** một phê duyệt đang chờ, không phải bắt đầu
   * một lượt mới (#207b).
   *
   * Ba việc bị bỏ qua khi `choDuyet`, và cả ba đều là "đừng tuyên bố lượt mới":
   *
   * - **không tăng `turnGenerationRef`** — generation là "người dùng vừa bắt đầu lượt
   *   khác", mà ở đây họ đang trả lời đúng lượt hiện tại;
   * - **không xoá `pendingResponseRef`** — câu trả lời đang bị hộp thoại HITL giữ lại
   *   thuộc về chính lượt ấy;
   * - **không dọn `lastTurn`** — đây là chỗ đã hỏng thật, không phải phòng xa: lệnh S2
   *   gõ bằng chữ đặt `lastTurn = {user: "Mở kính bên lái 30%", vivi: null}`, mic tự mở
   *   dọn nó về `null`, rồi câu trả lời tới đọc `prev?.user ?? ""` — thẻ kết quả hiện
   *   ra với ô "bạn đã nói" trống trơn.
   *
   * Cũng không `stopSpeech()`: ta chỉ mở mic SAU khi audio đọc xong, nên không có gì để
   * ngắt, và ngắt ở đây là ngắt chính câu hỏi vừa đọc nếu thứ tự đổi.
   *
   * Chữ ký công khai (`openVoice: () => void`) giữ nguyên có chủ đích — `Dock.tsx` và
   * `HomeView.tsx` truyền thẳng nó vào `onClick`, nên một tham số tuỳ chọn sẽ nhận
   * `MouseEvent` làm đối số.
   */
  const publishMicLevel = useCallback((level: number) => {
    const now = Date.now();
    if (now - micLevelThrottleAtRef.current < MIC_LEVEL_THROTTLE_MS) return;
    micLevelThrottleAtRef.current = now;
    for (const listener of micLevelListenersRef.current) listener(level);
  }, []);

  const subscribeMicLevel = useCallback((listener: (level: number) => void) => {
    micLevelListenersRef.current.add(listener);
    return () => {
      micLevelListenersRef.current.delete(listener);
    };
  }, []);

  const batDauNghe = useCallback((choDuyet: boolean) => {
    // Chốt chặn gọi lặp, đồng bộ TUYỆT ĐỐI (xem voiceStartingRef ở trên) —
    // bấm mic lần 2 trong lúc lần 1 còn đang chờ quyền mic (async, có thể vài
    // trăm ms tới vài giây) từng tạo RECORDER THỨ HAI đè lên
    // `recorderRef.current` mà không huỷ recorder cũ — timer tự-dừng 12s của
    // lần 1 (đặt cho recorder đã bị thay) sau đó cắt ngang recorder MỚI ở
    // thời điểm bất kỳ, ra đúng các bản ghi ngắn/lẻ giây quan sát được khi
    // test tay (1.0s, 0.26s, 2.3s thay vì chờ đủ hoặc chạm dừng thật).
    if (voiceStartingRef.current || recorderRef.current) return;
    // Chặn TRƯỚC khi xin quyền mic (issue #241, UAT-008): để tài xế nói xong cả
    // câu rồi mới báo "không gửi được" là kiểu hỏng tệ nhất — mất thời gian của
    // họ và trông như hệ thống nuốt lệnh. `stopVoiceAndSend` vẫn giữ chốt chặn
    // riêng cho ca rớt kết nối GIỮA CHỪNG lúc đang ghi.
    const ketNoiLucMoMic = connectionStateRef.current;
    if (ketNoiLucMoMic !== "online") {
      setToast(TOAST_CHUA_ONLINE[ketNoiLucMoMic]);
      return;
    }
    voiceStartingRef.current = true;
    if (!choDuyet) {
      // Lượt mới bắt đầu — vô hiệu hoá ngay câu trả lời/hộp thoại còn kẹt lại
      // từ lượt trước (xem turnGenerationRef và turnIdDaThayTheRef).
      turnGenerationRef.current += 1;
      danhDauLuotCu();
      pendingResponseRef.current = null;
      pendingKeepListeningRef.current = false;
      // Bấm mic = ý định ngắt lời (issue #106): im ngay, đừng để giọng của lượt
      // trước đọc chồng lên tiếng người đang nói.
      stopSpeech();
    }
    setVoiceOpen(true);
    setTranscript(null);
    transcriptShownAtRef.current = null;
    // Bắt buộc phải reset — lastTurn.vivi còn sót từ lượt TRƯỚC (vd. bấm nút
    // UI ngay trước đó) khiến effect auto-đóng overlay bên dưới (dựa vào
    // "có lastTurn.vivi thì đóng theo audio/hẹn giờ") kích hoạt NGAY khi mới
    // mở overlay ghi âm mới, đóng lại dù người dùng chưa kịp nói gì — lỗi
    // này có từ bản gửi Blob() rỗng cũ nhưng không lộ ra vì lượt cũ luôn kết
    // thúc rất nhanh; ghi âm thật cần tới MAX_RECORDING_MS mới lộ rõ.
    // Trước khi xoá, đẩy câu trả lời của lượt cũ (nếu có) vào lịch sử — đây
    // là điểm DUY NHẤT lastTurn.vivi thật sự "kết thúc" (bị lượt mới thay).
    if (!choDuyet) {
      setLastTurn((prev) => {
        if (prev?.vivi) setTurnHistory((history) => [...history, prev.vivi as string].slice(-MAX_TURN_HISTORY));
        return null;
      });
    }
    // Ghi âm mic thật (WAV, không phải MediaRecorder — xem wavRecorder.ts vì
    // sao) bắt đầu ngay khi mở overlay; chưa gửi gì lên BE cho tới khi người
    // dùng chạm lại mic (stopVoiceAndSend), im lặng đủ lâu sau khi đã nói
    // (VAD, xem onSilenceDetected trong wavRecorder.ts), hoặc hết
    // MAX_RECORDING_MS.
    startWavRecording({ onSilenceDetected: stopVoiceAndSend, onLevel: publishMicLevel })
      .then((recorder) => {
        recorderRef.current = recorder;
        voiceStartingRef.current = false;
        setRecording(true);
        autoStopTimerRef.current = setTimeout(stopVoiceAndSend, MAX_RECORDING_MS);
      })
      .catch((err) => {
        voiceStartingRef.current = false;
        closeVoice();
        setToast(
          err instanceof DOMException && err.name === "NotAllowedError"
            ? "Chưa được cấp quyền dùng micro — bấm biểu tượng khoá trên thanh địa chỉ để cho phép."
            : err instanceof Error
              ? err.message
              : "Không truy cập được micro.",
        );
      });
  }, [stopVoiceAndSend, closeVoice, stopSpeech, danhDauLuotCu, publishMicLevel]);

  const openVoice = useCallback(() => {
    // Bộ dò giữ micro riêng; để nó nghe tiếp trong lúc thu tay thì hai luồng
    // cùng đọc mic và bộ dò có thể tự đánh thức giữa câu lệnh. `closeVoice`
    // bật lại sau khi overlay đóng.
    void wakeControllerRef.current?.disable();
    batDauNghe(false);
  }, [batDauNghe]);

  const sendWakeCommand = useCallback((wavBlob: Blob, mode: "manual" | "wake_word") => {
    if (!wakeCaptureActiveRef.current) return;
    wakeCaptureActiveRef.current = false;
    wakeBoundaryNotifiedRef.current = false;
    setRecording(false);
    // Wake word cũng là một đường gửi lượt, nên chịu đúng chốt fail-closed của
    // send()/stopVoiceAndSend() (issue #241, UAT-008). Bỏ sót ở đây thì chỉ cần
    // gọi "Hey VIVI" là lại bắn request lên một backend đã chết.
    const ketNoiLucWake = connectionStateRef.current;
    if (ketNoiLucWake !== "online") {
      closeVoice();
      setToast(TOAST_CHUA_ONLINE[ketNoiLucWake]);
      return;
    }
    setPending(true);
    // Generation của lượt này — `onArming` của wake word đã tăng nó lúc bắt đầu thu.
    const theHe = turnGenerationRef.current;
    // Cố ý KHÔNG gửi kèm activation mode. Nhánh #177 thêm header
    // `X-VIVI-Activation-Mode` và một tham số thứ hai cho `sendVoice`, nhưng
    // backend trên `develop` chưa có `parse_activation_mode` — gửi đi thì nó
    // rơi vào hư không. Đó là siêu dữ liệu quan sát, không phải thứ luồng
    // wake word cần để chạy, nên lát cắt này bỏ qua thay vì kéo theo thay đổi
    // ở turn service, types và backend. `mode` vẫn dùng cho phần UI ở trên.
    void mode;
    // Đọc và HẠ ngay: cờ thuộc về đúng một lượt. Không hạ thì một lượt bấm mic tay ngay
    // sau đó vẫn khai `auto` và xe im lặng đúng lúc tài xế đang chờ trả lời.
    const tuDong = batTuDongRef.current;
    batTuDongRef.current = false;
    Promise.resolve(sessionReadyRef.current)
      .then(() => turnService.sendVoice(wavBlob, { auto: tuDong }))
      .then((ketQua) => ghiNhanTurnId(ketQua?.turnId, theHe))
      .catch((err) => {
        setPending(false);
        closeVoice();
        setToast(err instanceof Error ? err.message : "Không gửi được lệnh giọng nói.");
      });
  }, [closeVoice, ghiNhanTurnId]);

  useEffect(() => {
    if (!wakeFeatureEnabled) return;
    const controller = new WakeWordController({
      pipeline: new MicrophonePipeline(),
      detector: createOnnxWakeWordDetector(),
      callbacks: {
        onStateChange: (nextState) => {
          setWakeState(nextState);
          if (nextState === "LISTENING_FOR_WAKEWORD") setWakeWordAvailable(true);
        },
        onArming: (silent) => {
          // Qua ARMING nghĩa là tài xế CHỦ ĐỘNG gọi (wake word hoặc bấm mic) — cửa sổ
          // nghe tiếp vào `CAPTURING_COMMAND` thẳng, không qua đây.
          batTuDongRef.current = false;
          wakeCaptureActiveRef.current = true;
          // Capture đã thật sự bắt đầu — cửa sổ đếm ngược (nếu đang hiện) đã
          // xong việc của nó (issue #343).
          setFollowUpWindowActive(false);
          turnGenerationRef.current += 1;
          danhDauLuotCu();
          pendingResponseRef.current = null;
          pendingKeepListeningRef.current = false;
          stopSpeech();
          setVoiceOpen(true);
          setTranscript(null);
          // silent=true: tới từ cửa sổ nghe tiếp (issue #343) — tài xế vừa được
          // mời nói tiếp, không cần thêm tiếng "bắt đầu nói".
          if (!silent) playArmBeep();
        },
        onCaptureStarted: () => setRecording(true),
        onCommandReady: sendWakeCommand,
        onLevel: publishMicLevel,
        onSilentClose: () => {
          wakeCaptureActiveRef.current = false;
          setRecording(false);
          closeVoice();
        },
        onWakeUnavailable: (message) => {
          // Bộ dò hỏng thì chạm-mic phải sống tiếp: hạ cờ available để nút
          // wake biến đi, và nhả micro của bộ dò.
          console.error("Wake word unavailable:", message);
          const dead = wakeControllerRef.current;
          wakeControllerRef.current = null;
          wakeCaptureActiveRef.current = false;
          setFollowUpWindowActive(false);
          setWakeState("IDLE");
          setWakeWordAvailable(false);
          void dead?.dispose().catch(() => {});
        },
        // Cửa sổ nghe tiếp (issue #343) — mở ngay sau cooldown khi lượt vừa
        // xong mời "nghe tiếp?" (xem notifyWakeResponseBoundary). Mic không hề
        // đóng ở đây, chỉ đổi UI: bật vòng đếm ngược quanh nút mic.
        onFollowUpWindowStarted: () => {
          batTuDongRef.current = true;
          wakeCaptureActiveRef.current = true;
          setFollowUpWindowActive(true);
        },
        // Hết giờ mà không ai nói — về nghe tên gọi như cũ, báo bằng beep trầm
        // hơn (tài xế nhiều lúc không nhìn màn hình để thấy vòng đếm ngược tắt).
        onFollowUpWindowExpired: () => {
          wakeCaptureActiveRef.current = false;
          setFollowUpWindowActive(false);
          playCloseBeep();
          closeVoice();
        },
      },
      // setTimeout/clearTimeout ném "Illegal invocation" khi bị gọi tách khỏi
      // receiver của chúng — bind vào globalThis.
      setTimer: setTimeout.bind(globalThis),
      clearTimer: clearTimeout.bind(globalThis),
      // Phải khớp (hoặc lớn hơn) thời lượng beep thật: thu câu lệnh bắt đầu khi
      // hẹn giờ này bắn, và bắt đầu trước lúc beep dứt thì tiếng beep vọng từ
      // loa vào mic bị hiểu nhầm là tài xế đã nói.
      armLatencyMs: ARM_BEEP_DURATION_MS,
    });
    wakeControllerRef.current = controller;
    if (wakeEnabledRef.current) void controller.enable();
    return () => {
      wakeControllerRef.current = null;
      wakeCaptureActiveRef.current = false;
      void controller.dispose();
    };
    // Vòng đời controller gắn với provider /driver. Bật/tắt đi qua
    // setWakeWordEnabled; dựng lại đồ thị micro mỗi lần gạt là không an toàn.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wakeFeatureEnabled]);

  const setWakeWordEnabled = useCallback((enabled: boolean) => {
    if (!wakeFeatureEnabled) return;
    wakeEnabledRef.current = enabled;
    setWakeWordEnabledState(enabled);
    const controller = wakeControllerRef.current;
    if (!controller) return;
    if (enabled) void controller.enable();
    else void controller.disable();
  }, [wakeFeatureEnabled]);

  // Rời trang/unmount giữa lúc đang ghi (điều hướng đi chỗ khác) — phải nhả
  // mic, không thì icon "đang dùng micro" của trình duyệt treo mãi.
  useEffect(() => {
    return () => {
      recorderRef.current?.cancel();
      if (autoStopTimerRef.current) clearTimeout(autoStopTimerRef.current);
    };
  }, []);

  // Đóng theo audio TTS phát xong (`ended`) thay vì hẹn giờ cố định tính từ
  // lúc CÓ TEXT — xem docstring CLOSE_AFTER_AUDIO_MS. `shouldStartCloseTimerImmediately`
  // xử lý fail-open (không có audio/audio lỗi/bị chặn autoplay).
  useEffect(() => {
    if (!voiceOpen) return;
    if (!lastTurn?.vivi || pendingApproval) return;
    // Còn phần chưa đọc — đừng tự đóng theo audio nữa (issue #343). Cửa sổ
    // nghe tiếp (WakeWordController.onFollowUpWindowStarted/Expired) giờ là
    // thứ quyết định khi nào đóng: tài xế có thể vẫn đang nói tiếp trong
    // FOLLOW_UP_WINDOW_MS đó, và đóng thẻ sớm sẽ giấu mất nút "Nghe tiếp" lẫn
    // vòng đếm ngược ngay lúc chúng còn tác dụng.
    if (lastTurn.hasMoreToRead) return;
    const audio = activeSpeechRef.current;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const startCloseTimer = () => {
      timer = setTimeout(closeVoice, CLOSE_AFTER_AUDIO_MS);
    };
    if (audio === null || shouldStartCloseTimerImmediately(audio)) {
      startCloseTimer();
      return () => {
        if (timer) clearTimeout(timer);
      };
    }
    audio.addEventListener("ended", startCloseTimer);
    audio.addEventListener("error", startCloseTimer);
    return () => {
      audio.removeEventListener("ended", startCloseTimer);
      audio.removeEventListener("error", startCloseTimer);
      if (timer) clearTimeout(timer);
    };
    // `speechStopCount` nằm đây để effect chạy lại sau khi người dùng bấm "Dừng
    // đọc": `pause()` không phát `ended`, nên nhánh nghe `ended` ở trên sẽ chờ
    // mãi. Chạy lại thì `activeSpeechRef` đã null ⇒ rơi vào nhánh hẹn giờ ngay,
    // và thẻ vẫn tự đóng như mọi lượt khác thay vì treo lại (issue #106).
    // Xem docstring `speechStopCount` về việc vì sao KHÔNG dùng `speaking`.
  }, [voiceOpen, lastTurn, pendingApproval, closeVoice, speechStopCount]);

  // Yêu cầu người dùng: "hạn chế bấm nút hết cỡ". `approval.required` tới thì
  // tự bắt đầu ghi lại luôn — tài xế không cần chạm mic để nói "đồng ý"/"từ
  // chối". Đợi TTS hỏi xong (`assistant.speech` đọc "Bạn có đồng ý không?")
  // rồi mới ghi, không thì mic thu đúng giọng của xe đang đọc câu hỏi.
  // `batDauNghe()` tự chốt gọi lặp (voiceStartingRef/recorderRef) nên effect
  // này an toàn dù chạy lại.
  //
  // `choDuyet: true` — đây là mic để TRẢ LỜI lượt đang chờ, không phải một lượt
  // mới; xem docstring `batDauNghe`.
  //
  // `lanMoLaiMic` trong deps là thứ đánh thức effect khi lượt trả lời hỏng:
  // `pendingApproval` cố ý không đổi tham chiếu ở nhánh mơ hồ (#207b).
  useEffect(() => {
    if (!pendingApproval) return;
    const moMic = () => batDauNghe(true);
    const audio = activeSpeechRef.current;
    if (audio === null || shouldStartCloseTimerImmediately(audio)) {
      moMic();
      return;
    }
    // Audio còn đó, chưa `ended`, không `error` — nhìn từ đây thì "đang đọc thật"
    // và "bị autoplay policy chặn ngay ở `play()`" giống hệt nhau, mà ca thứ hai
    // sẽ KHÔNG bao giờ phát `ended`. Đường lui bằng đồng hồ, và hết giờ vẫn phải
    // hỏi `paused`: đang đọc thật thì để `ended` lo (xem CHO_AM_THANH_MS).
    const hetGio = setTimeout(() => {
      // `!paused` MỘT MÌNH là không đủ, và đây là chỗ đo thật bắt được (20/08, khi thẻ
      // ở nền và Chrome bóp timer): một `Audio` có thể ở trạng thái "đã gọi play(),
      // chưa paused, mà **chưa hề tải**" — `readyState=0`, `currentTime=0`, `duration`
      // NaN, và `ended` sẽ không bao giờ tới. Chỉ hỏi `paused` thì đường lui hoãn vô
      // hạn đúng cái ca nó sinh ra để cứu.
      //
      // `currentTime > 0` là bằng chứng **có tiếng thật sự phát ra**, chứ không phải ý
      // định phát. Ai đó có tiếng thì để `ended` lo; còn lại thì mở mic.
      const dangDoc = activeSpeechRef.current;
      if (dangDoc && !dangDoc.paused && dangDoc.currentTime > 0) return;
      moMic();
    }, CHO_AM_THANH_MS);
    audio.addEventListener("ended", moMic);
    audio.addEventListener("error", moMic);
    return () => {
      clearTimeout(hetGio);
      audio.removeEventListener("ended", moMic);
      audio.removeEventListener("error", moMic);
    };
  }, [pendingApproval, batDauNghe, lanMoLaiMic]);

  // Hộp thoại tự hết hạn theo `expires_at` của server.
  //
  // Bắt buộc phải có kể từ khi nhánh terminal chỉ đóng hộp thoại cho **lượt của chính
  // nó**: trước đó, thứ dọn một hộp thoại đã chết là một lượt bất kỳ khác kết thúc —
  // đúng cái hành vi vừa bị bỏ, và nó "dọn" bằng cách cũng xoá luôn những hộp thoại
  // còn sống. Không có effect này thì hộp thoại hết hạn nằm lại trên màn hình mãi, và
  // hai nút của nó chỉ dẫn tới `APPROVAL_EXPIRED`.
  //
  // `GRACE_HET_HAN_MS`: `expires_at` là giờ **server**, còn `Date.now()` là giờ máy
  // trình duyệt. Lệch đồng hồ vài giây là chuyện thường, và lệch theo chiều máy chạy
  // nhanh sẽ xoá một hộp thoại vẫn còn hiệu lực — mất một lệnh của tài xế. Nới hai
  // giây về phía an toàn: giữ lâu hơn một chút thì cùng lắm là bấm vào và nghe
  // "xác nhận đã hết hạn", còn xoá sớm thì không còn gì để bấm.
  useEffect(() => {
    if (!pendingApproval) return;
    const conLai = new Date(pendingApproval.expiresAt).getTime() - Date.now() + GRACE_HET_HAN_MS;
    // Chốt theo `approvalId`: hẹn giờ này chỉ được gỡ **đúng phê duyệt đã đặt ra nó**.
    //
    // Cùng lớp rủi ro với chính bug PR này sửa — một sự kiện muộn tác động lên trạng
    // thái đã đi tiếp. Ca @thanhpro82 nêu: A hết hạn, trong 2 giây nới thì B tới; hẹn
    // giờ của A không được phép xoá hộp thoại của B.
    //
    // `clearTimeout` ở cleanup **đã** che ca ấy: B tới ⇒ `pendingApproval` đổi tham
    // chiếu ⇒ effect chạy lại ⇒ hẹn giờ của A bị huỷ trước khi kịp nổ. Nhưng đó là dựa
    // vào **thứ tự flush của React** chứ không dựa vào mã của ta: giữa `setPendingApproval(B)`
    // và lúc cleanup chạy có một khe, và một `setTimeout` đến hạn đúng khe ấy vẫn nổ.
    // Khe hẹp, nhưng "hẹp" là thứ đã sinh ra bug gốc. Cổng này biến bất biến ngầm thành
    // một dòng đọc được.
    const cuaAi = pendingApproval.approvalId;
    const timer = setTimeout(
      () => {
        if (pendingApprovalRef.current?.approvalId !== cuaAi) return;
        pendingApprovalRef.current = null;
        setPendingApproval(null);
        hetChoCham();
        setToast("Hết thời gian xác nhận. Bạn ra lệnh lại giúp tôi nhé.");
      },
      Math.max(0, conLai),
    );
    return () => clearTimeout(timer);
  }, [pendingApproval, hetChoCham]);

  // Approval.required luôn thắng voice overlay (HITL modal hiện đè lên) —
  // dẫn xuất trực tiếp khi render thay vì đặt lại state trong effect riêng.
  const effectiveVoiceOpen = voiceOpen && !pendingApproval;

  const approve = useCallback(() => {
    if (!pendingApproval) return;
    // Ghi vào cùng sổ với nhánh voice: bấm nút xong mà event `approval.intent.detected`
    // của lượt nói tới sau (hoặc replay khi nối lại) thì không được gọi REST lần nữa.
    daGuiQuyetDinhRef.current.add(pendingApproval.approvalId);
    // Cú chạm CHÍNH LÀ thứ `committed === false` đang chờ — hạ cờ ngay, không đợi
    // event. Còn treo thì `turn.completed` của lượt lệnh gốc sẽ bị `choChamConCho`
    // giữ lại, và hộp thoại đứng vĩnh viễn trên màn hình sau khi lệnh đã chạy xong.
    hetChoCham();
    turnService
      .decideApproval(pendingApproval.approvalId, "approve", pendingApproval.approvedVehicleStateVersion)
      .catch((err) => {
        setToast(err instanceof Error ? err.message : "Không duyệt được lệnh.");
      });
  }, [pendingApproval, hetChoCham]);

  const reject = useCallback(() => {
    if (!pendingApproval) return;
    daGuiQuyetDinhRef.current.add(pendingApproval.approvalId);
    hetChoCham();
    turnService
      .decideApproval(pendingApproval.approvalId, "reject", pendingApproval.approvedVehicleStateVersion)
      .catch((err) => {
        setToast(err instanceof Error ? err.message : "Không từ chối được lệnh.");
      });
  }, [pendingApproval, hetChoCham]);

  return (
    <DriverShellContext.Provider
      value={{
        vehicleState,
        uiPolicy,
        connectionState,
        canDrive,
        vehiclePool,
        activeView,
        setActiveView,
        lastTurn,
        turnHistory,
        assistantState,
        pendingApproval,
        // Đối chiếu id chứ không đọc cờ trần: `canChamXacNhan` có thể còn giữ id của
        // một approval đã kết thúc trong khoảng giữa hai lần render.
        approvalNeedsTap: canChamXacNhan !== null && canChamXacNhan === pendingApproval?.approvalId,
        approve,
        reject,
        voiceOpen: effectiveVoiceOpen,
        openVoice,
        recording,
        stopVoice: stopVoiceAndSend,
        transcript,
        send,
        pending,
        toast,
        refreshVehicleState,
        closeVoice,
        speaking,
        stopSpeaking: stopSpeech,
        wakeWordAvailable,
        wakeWordEnabled,
        wakeState,
        setWakeWordEnabled,
        followUpWindowActive,
        subscribeMicLevel,
        routineExecution,
        routinePreview,
        routineSetupRequired,
      }}
    >
      {children}
    </DriverShellContext.Provider>
  );
}
