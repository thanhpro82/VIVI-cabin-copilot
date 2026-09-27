import type {
  ActionPlan,
  Citation,
  DriverEvent,
  HeadlightMode,
  SafetyLevel,
  SimGear,
  SimMotionResult,
  TurnService,
  UiPolicy,
  VehicleState,
} from "./types";
import { TRACK_NAMES as FIXTURE_TRACK_NAMES } from "@/lib/fixtures/media";
import { HEADLIGHT_LABEL, LOCKED_UI_POLICY, OPEN_UI_POLICY } from "./types";

// Vẫn mô phỏng độ trễ thật (CODING_STANDARDS.md) nhưng ngắn — nút bấm UI đơn
// giản không nên chờ hàng giây như một lượt hội thoại giọng nói đầy đủ.
const MOCK_LATENCY_MS = 0;
const APPROVAL_TIMEOUT_MS = 15000;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function genId(prefix: string) {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

let vehicleState: VehicleState = {
  vehicleId: "vehicle-demo-01",
  stateVersion: 1,
  observedAt: new Date().toISOString(),
  motion: { speedKph: 0, gear: "P", ignition: "ON" },
  hvac: { power: false, temperatureC: 24, fanLevel: 2 },
  windows: { frontLeft: 0, frontRight: 0, rearLeft: 0, rearRight: 0 },
  doors: { frontLeft: "closed", frontRight: "closed", rearLeft: "closed", rearRight: "closed" },
  media: { status: "paused", volume: 35, track: null },
  navigation: { status: "idle", destinationId: null },
  lights: { headlight: "auto", interior: false },
  trunk: { position: "closed" },
  seat: {
    frontLeft: { heating: 0, foreAft: 50, recline: 50, height: 50 },
    frontRight: { heating: 0, foreAft: 50, recline: 50, height: 50 },
  },
};

function bumpState(mutate: (s: VehicleState) => void) {
  const next = { ...vehicleState };
  mutate(next);
  next.stateVersion = vehicleState.stateVersion + 1;
  next.observedAt = new Date().toISOString();
  vehicleState = next;
}

/**
 * Debug-only, KHÔNG thuộc TurnService chính thức (real.ts không có hàm này —
 * tốc độ xe thật đọc từ vehicle simulator, FE không tự set được). Dùng cho
 * demo/test để mô phỏng xe đang chạy, xem docs/ARCHITECTURE.md mục 5 và
 * scripts/smoke-turn.ts. Tương đương slider "tốc độ mô phỏng" ở prototype gốc.
 *
 * Speed-sensing auto-lock: trước đây chỉ CHẶN lệnh mở khoá MỚI khi xe đang
 * chạy (S3, xem doorSafetyLevel()) — không đụng tới cửa/cốp ĐÃ mở khoá từ lúc
 * còn đứng yên. Nghĩa là đỗ xe → mở khoá → tăng tốc lên >0 km/h thì cửa vẫn
 * hiện "đã mở khoá", một lỗ hổng an toàn thật (phát hiện qua review
 * 2026-08-09). Xe thật có tính năng tương đương ("speed-sensing door lock")
 * — vượt ngưỡng 0 thì tự khoá lại, không chờ người dùng tự khoá tay. Chỉ tác
 * động cửa/cốp — cửa sổ vẫn dùng được lúc xe chạy vì đó là 1 nhóm an toàn
 * khác (S2 mọi tốc độ, không phải S3), xem ADR-006.
 */
/**
 * Mô phỏng quy tắc `is_stationary()` backend dùng để tính `ui.policy`
 * (PR #77, src/services/ui_policy.py) — CHỈ dùng cho mock, real.ts nhận
 * policy y nguyên từ backend qua WS, không tự tính. speedKph > 0 → biến
 * thể siết chặt nhất (giống LOCKED_UI_POLICY); == 0 → biến thể mở.
 */
function computeMockUiPolicy(speedKph: number): UiPolicy {
  // controlsLocked là fail-closed cho MẤT KẾT NỐI, không phải cho xe đang chạy
  // (issue #241) — mock không bao giờ "mất kết nối" nên luôn false ở cả hai
  // nhánh, kể cả khi tái dùng giá trị siết chặt của LOCKED_UI_POLICY cho slider.
  if (speedKph > 0) return { ...LOCKED_UI_POLICY, controlsLocked: false };
  return OPEN_UI_POLICY;
}

/**
 * Quy ước "chọn hộ tôi" của `SimulatorRuntime.set_motion(gear=None)`: tốc độ > 0
 * thì `D`, bằng 0 thì `P`. Lặp lại ở mock để `speed 45` gõ console, thanh trượt
 * ở real mode và thanh trượt ở mock cho **cùng một trạng thái xe** — nếu mock
 * giữ nguyên `P` ở 45 km/h thì nó mô phỏng một chiếc xe không tồn tại, và ca S3
 * cửa (backend đòi `speed_kph == 0 && gear == "P"`) thử ở mock sẽ không nói gì
 * về hành vi thật.
 */
function autoGear(speedKph: number): SimGear {
  return speedKph > 0 ? "D" : "P";
}

function applyMockMotion(speedKph: number, gear: SimGear) {
  const wasStationary = vehicleState.motion.speedKph === 0;
  const nowStationary = speedKph === 0;
  bumpState((s) => {
    s.motion.speedKph = speedKph;
    s.motion.gear = gear;
    if (wasStationary && speedKph > 0) {
      ALL_POSITIONS.forEach((p) => {
        s.doors[p] = "closed";
      });
      s.trunk.position = "closed";
    }
  });
  // Backend chỉ phát ui.policy khi POLICY đổi, không phải mỗi lần tốc độ
  // đổi số — chỉ emit khi băng qua ranh giới đứng yên/di chuyển.
  if (wasStationary !== nowStationary) {
    emit({ type: "ui.policy", uiPolicy: computeMockUiPolicy(speedKph) });
  }
}

export function __setMockSpeedKph(speedKph: number) {
  applyMockMotion(speedKph, autoGear(speedKph));
}

let pendingApprovalId: string | null = null;
const pendingByApproval = new Map<
  string,
  { turnId: string; plan: ActionPlan; parsed: ParsedCommand }
>();
const subscribers = new Set<(event: DriverEvent) => void>();

function emit(event: DriverEvent) {
  subscribers.forEach((cb) => cb(event));
}

interface ParsedCommand {
  tool: string;
  args: Record<string, unknown>;
  safetyLevel: SafetyLevel;
  apply: () => void;
  displayText: string;
}

/** control_door: S2 khi xe đứng yên, S3 (chặn) khi xe đang chạy — ADR-006. */
function doorSafetyLevel(): SafetyLevel {
  return vehicleState.motion.speedKph > 0 ? "S3" : "S2";
}

// windows/doors dùng chung 1 bộ vị trí (frontLeft/frontRight/rearLeft/rearRight).
type Position = keyof VehicleState["windows"] & keyof VehicleState["doors"];

const POSITION_LABEL: Record<Position, string> = {
  frontLeft: "bên lái",
  frontRight: "bên phụ",
  rearLeft: "sau bên trái",
  rearRight: "sau bên phải",
};

const POSITION_ARG: Record<Position, string> = {
  frontLeft: "front_left",
  frontRight: "front_right",
  rearLeft: "rear_left",
  rearRight: "rear_right",
};

/** Nhận diện vị trí từ câu nói — mặc định bên tài (frontLeft) nếu không nói rõ, giữ đúng hành vi cũ (mock.test.ts). */
function detectPosition(t: string): Position {
  if (/sau.*trái|hàng sau bên trái/.test(t)) return "rearLeft";
  if (/sau.*phải|hàng sau bên phải/.test(t)) return "rearRight";
  if (/bên phụ/.test(t)) return "frontRight";
  return "frontLeft";
}

const ALL_POSITIONS: Position[] = ["frontLeft", "frontRight", "rearLeft", "rearRight"];

/** Câu không nói rõ vị trí (vd nút "Mở khoá cửa" ở RightPanel) → áp dụng cho TẤT CẢ 4 cửa, không chỉ bên lái. */
function hasExplicitPosition(t: string): boolean {
  return /bên lái|bên phụ|sau bên trái|sau bên phải/.test(t);
}

// Ghế — chỉ điều khiển ghế lái (frontLeft) từ màn hình driver, giống phạm vi
// thực tế (tài xế chỉnh ghế của mình), tránh thêm bộ chọn vị trí như cửa/cửa sổ.
type SeatAxis = "foreAft" | "recline" | "height";

const SEAT_AXIS_LABEL: Record<SeatAxis, string> = {
  foreAft: "trượt ghế",
  recline: "ngả ghế",
  height: "độ cao ghế",
};

const SEAT_AXIS_ARG: Record<SeatAxis, string> = {
  foreAft: "fore_aft",
  recline: "recline",
  height: "height",
};

// Từ khoá router thật đọc để nhận trục (Assistant._match_seat_position) —
// khác SEAT_AXIS_LABEL (chỉ dùng cho câu hiển thị tự nhiên). "ngả ghế" khớp cả
// khi đứng trong "ngả ghế lái"; "nâng ghế" khớp trong "nâng ghế lái"; "tiến"
// đứng độc lập trong "ghế lái tiến" — xem VehicleControlView.tsx SEAT_AXES.
const SEAT_AXIS_TRIGGER: Record<SeatAxis, string> = {
  foreAft: "tiến",
  recline: "ngả ghế",
  height: "nâng ghế",
};

// Cùng nguồn với simulator thật — `default_playlist()`
// (src/vehicle_sim/state.py) đọc chính `src/fixtures/media.json` này. Mock
// và real lệch tên bài là bug đã khiến real mode phát mãi một file (#173),
// và mock chính là chỗ bảng chép tay cũ được sinh ra.
const TRACK_NAMES = FIXTURE_TRACK_NAMES;

function shiftTrack(current: string | null, delta: number): string {
  const index = current ? TRACK_NAMES.indexOf(current) : -1;
  const nextIndex = (index + delta + TRACK_NAMES.length) % TRACK_NAMES.length;
  return TRACK_NAMES[nextIndex];
}

function parseCommand(text: string): ParsedCommand | null {
  const t = text.toLowerCase();

  const acMatch = t.match(/điều hòa.*?(\d+)\s*độ/);
  if (acMatch) {
    const temp = Number(acMatch[1]);
    return {
      tool: "control_ac",
      args: { temperature_c: temp },
      safetyLevel: "S1",
      apply: () =>
        bumpState((s) => {
          s.hvac.power = true;
          s.hvac.temperatureC = temp;
        }),
      displayText: `Đã chỉnh điều hòa ${temp} độ.`,
    };
  }

  if (/tắt điều hòa/.test(t)) {
    return {
      tool: "control_ac",
      args: { power: false },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.hvac.power = false; }),
      displayText: "Đã tắt điều hòa.",
    };
  }

  if (/quạt gió/.test(t)) {
    // Dải THẬT của backend là 0..3 (`router.py::_match_hvac` trả
    // `fan_level_out_of_range` ngoài dải đó). Bản cũ kẹp tới 5 — mock nhận mức 4/5
    // ngon lành còn real mode từ chối, đúng loại lệch khiến demo mock xanh mà real
    // đỏ (issue #115 mục 5).
    //
    // Router thật KHÔNG suy diễn tăng/giảm tương đối: nó không đọc vehicle state nên
    // "tăng quạt gió" trả `clarify/missing_fan_level`. FE giờ luôn gửi mức tuyệt
    // đối; nhánh tương đối giữ lại làm fallback y như `sưởi ghế` phía dưới, phòng
    // nơi khác còn gọi kiểu cũ.
    const explicitLevel = t.match(/(\d+)/);
    const nextLevel = explicitLevel
      ? Math.max(0, Math.min(3, Number(explicitLevel[1])))
      : Math.max(0, Math.min(3, vehicleState.hvac.fanLevel + (/giảm/.test(t) ? -1 : 1)));
    return {
      tool: "set_hvac_fan_level",
      args: { level: nextLevel },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.hvac.fanLevel = nextLevel; }),
      displayText: `Đã chỉnh quạt gió mức ${nextLevel}.`,
    };
  }

  if (/sưởi ghế/.test(t)) {
    // agent_spec.md: set_seat_heating level 0..3. Router thật luôn đòi số mức
    // tuyệt đối trong câu (Assistant._number), không có "tăng/giảm 1 nấc" —
    // VehicleControlView.tsx giờ luôn gửi kèm số; giữ nhánh tương đối cũ làm
    // fallback phòng khi có nơi khác gọi "tăng/giảm/tắt sưởi ghế" không kèm số.
    const explicitLevel = t.match(/(\d+)/);
    const nextLevel = explicitLevel
      ? Math.max(0, Math.min(3, Number(explicitLevel[1])))
      : /tắt/.test(t)
        ? 0
        : Math.max(0, Math.min(3, vehicleState.seat.frontLeft.heating + (/giảm/.test(t) ? -1 : 1)));
    return {
      tool: "control_seat_heating",
      args: { seat: "front_left", level: nextLevel },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.seat.frontLeft.heating = nextLevel; }),
      displayText: `Đã chỉnh sưởi ghế lái mức ${nextLevel}.`,
    };
  }

  const seatAxisMatch = t.match(/(tiến|ngả ghế|nâng ghế).*?(\d+)\s*%/);
  if (seatAxisMatch) {
    // set_seat_position: S2 khi xe đứng yên, S3 (chặn) khi đang chạy —
    // cùng mức an toàn với cửa/cốp vì cũng là bộ truyền động cơ khí (agent_spec.md).
    const axis = (Object.entries(SEAT_AXIS_TRIGGER).find(([, trigger]) => trigger === seatAxisMatch[1])?.[0] ??
      "foreAft") as SeatAxis;
    const percent = Math.max(0, Math.min(100, Number(seatAxisMatch[2])));
    return {
      tool: "control_seat_position",
      args: { seat: "front_left", axis: SEAT_AXIS_ARG[axis], value: percent },
      safetyLevel: doorSafetyLevel(),
      apply: () => bumpState((s) => { s.seat.frontLeft[axis] = percent; }),
      displayText: `Đã chỉnh ${SEAT_AXIS_LABEL[axis]} lái còn ${percent}%.`,
    };
  }

  // Phải xét TRƯỚC /mở.*cửa sổ/ chung chung — "mở cửa sổ bên tài 40%" vẫn
  // khớp regex mở phía dưới nếu đứng sau, sẽ luôn nhảy về 100% sai ý người dùng.
  const windowPercentMatch = t.match(/cửa sổ.*?(\d+)\s*%/);
  if (windowPercentMatch) {
    const percentage = Math.max(0, Math.min(100, Number(windowPercentMatch[1])));
    const position = detectPosition(t);
    return {
      tool: "control_window",
      args: { position: POSITION_ARG[position], percentage },
      safetyLevel: "S2",
      apply: () => bumpState((s) => { s.windows[position] = percentage; }),
      displayText: `Đã chỉnh cửa sổ ${POSITION_LABEL[position]} còn ${percentage}%.`,
    };
  }

  if (/mở.*cửa sổ/.test(t)) {
    // control_window luôn S2, bất kể tốc độ (khác control_door) — ADR-006.
    const position = detectPosition(t);
    return {
      tool: "control_window",
      args: { position: POSITION_ARG[position], percentage: 100 },
      safetyLevel: "S2",
      apply: () => bumpState((s) => { s.windows[position] = 100; }),
      displayText: `Đã mở cửa sổ ${POSITION_LABEL[position]}.`,
    };
  }

  if (/đóng.*cửa sổ/.test(t)) {
    const position = detectPosition(t);
    return {
      tool: "control_window",
      args: { position: POSITION_ARG[position], percentage: 0 },
      safetyLevel: "S2",
      apply: () => bumpState((s) => { s.windows[position] = 0; }),
      displayText: `Đã đóng cửa sổ ${POSITION_LABEL[position]}.`,
    };
  }

  // "mở khóa cửa" = RightPanel (nút "toàn xe"), "mở cửa" = VehicleControlView
  // (đổi theo đúng ngữ pháp router thật — Assistant._match_door chỉ cần "mở"/
  // "đóng" + "cửa", không cần "khoá").
  if (/mở khóa cửa|mở cửa/.test(t)) {
    if (!hasExplicitPosition(t)) {
      // Nút "Mở khoá cửa" ở RightPanel — mở TẤT CẢ cửa. S3 (chặn cứng, không hỏi) nếu xe đang chạy — ADR-006 + yêu cầu review 2026-08-07.
      return {
        tool: "control_door",
        args: { position: "all", lock_status: "unlocked" },
        safetyLevel: doorSafetyLevel(),
        // Giá trị "open"/"closed" — đúng hợp đồng backend thật (mqtt_spec.md,
        // agent_spec.md set_door_state), không phải "unlocked"/"locked" như
        // trước — P0 không remote-control được việc đẩy cửa mở khỏi khoá,
        // nhưng field lưu là trạng thái cửa, không phải trạng thái khoá.
        apply: () => bumpState((s) => { ALL_POSITIONS.forEach((p) => { s.doors[p] = "open"; }); }),
        displayText: "Đã mở khoá tất cả cửa.",
      };
    }
    const position = detectPosition(t);
    return {
      tool: "control_door",
      args: { position: POSITION_ARG[position], lock_status: "unlocked" },
      safetyLevel: doorSafetyLevel(),
      apply: () => bumpState((s) => { s.doors[position] = "open"; }),
      displayText: `Đã mở khoá cửa ${POSITION_LABEL[position]}.`,
    };
  }

  if (/khoá cửa|khóa cửa|đóng cửa/.test(t)) {
    if (!hasExplicitPosition(t)) {
      return {
        tool: "control_door",
        args: { position: "all", lock_status: "locked" },
        safetyLevel: doorSafetyLevel(),
        apply: () => bumpState((s) => { ALL_POSITIONS.forEach((p) => { s.doors[p] = "closed"; }); }),
        displayText: "Đã khoá tất cả cửa.",
      };
    }
    const position = detectPosition(t);
    return {
      tool: "control_door",
      args: { position: POSITION_ARG[position], lock_status: "locked" },
      safetyLevel: doorSafetyLevel(),
      apply: () => bumpState((s) => { s.doors[position] = "closed"; }),
      displayText: `Đã khoá cửa ${POSITION_LABEL[position]}.`,
    };
  }

  if (/mở cốp/.test(t)) {
    // set_trunk_state dùng chung mức an toàn với set_door_state — vẫn là bộ
    // truyền động vật lý bên ngoài xe, cùng rủi ro khi xe đang chạy (ADR-006).
    return {
      tool: "set_trunk_state",
      args: { state: "open" },
      safetyLevel: doorSafetyLevel(),
      apply: () => bumpState((s) => { s.trunk.position = "open"; }),
      displayText: "Đã mở cốp xe.",
    };
  }

  if (/đóng cốp/.test(t)) {
    return {
      tool: "set_trunk_state",
      args: { state: "closed" },
      safetyLevel: doorSafetyLevel(),
      apply: () => bumpState((s) => { s.trunk.position = "closed"; }),
      displayText: "Đã đóng cốp xe.",
    };
  }

  // Đèn trần xét TRƯỚC đèn pha: "đèn trần" cũng chứa "đèn", và chỉ nhánh này
  // mới cho phép tắt (đèn pha không có `off`, xem dưới).
  if (/đèn trần|đèn nội thất|đèn trong xe/.test(t)) {
    const enabled = !/tắt/.test(t);
    return {
      tool: "set_interior_light",
      args: { enabled },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.lights.interior = enabled; }),
      displayText: enabled ? "Đã bật đèn trần." : "Đã tắt đèn trần.",
    };
  }

  if (/đèn/.test(t)) {
    // Enum 3 trạng thái, KHÔNG có `off`: router thật trả
    // `denied/headlight_off_not_permitted` cho "tắt đèn pha" (UNECE R48 cấm tắt
    // thủ công khi có DRL, ADR-020). Mock phải từ chối y hệt, nếu không mock lại
    // dạy người dùng một hành vi mà real mode không có.
    if (/tắt/.test(t)) return null;
    const mode: HeadlightMode = /chiếu xa|pha xa/.test(t)
      ? "high_beam"
      : /tự động/.test(t)
        ? "auto"
        : /đèn pha|chiếu gần|đèn cốt/.test(t)
          ? "low_beam"
          : "auto";
    return {
      tool: "set_headlight_mode",
      args: { mode },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.lights.headlight = mode; }),
      displayText: `Đã chuyển đèn sang ${HEADLIGHT_LABEL[mode]}.`,
    };
  }

  if (/bật nhạc/.test(t)) {
    return {
      tool: "control_music",
      args: { action: "play" },
      safetyLevel: "S1",
      apply: () =>
        bumpState((s) => {
          s.media.status = "playing";
          s.media.track = s.media.track ?? TRACK_NAMES[0];
        }),
      displayText: "Đã bật nhạc.",
    };
  }

  if (/tắt nhạc|dừng nhạc/.test(t)) {
    return {
      tool: "control_music",
      args: { action: "pause" },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.media.status = "paused"; }),
      displayText: "Đã tắt nhạc.",
    };
  }

  if (/bài (tiếp theo|kế tiếp|sau)|next.*track|chuyển bài/.test(t)) {
    const nextTrack = shiftTrack(vehicleState.media.track, 1);
    return {
      tool: "control_music",
      args: { action: "next" },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.media.status = "playing"; s.media.track = nextTrack; }),
      displayText: `Đang phát: ${nextTrack}.`,
    };
  }

  if (/bài (trước|trước đó)/.test(t)) {
    const prevTrack = shiftTrack(vehicleState.media.track, -1);
    return {
      tool: "control_music",
      args: { action: "prev" },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.media.status = "playing"; s.media.track = prevTrack; }),
      displayText: `Đang phát: ${prevTrack}.`,
    };
  }

  if (/âm lượng/.test(t)) {
    // Router thật luôn đòi số tuyệt đối (Assistant._number) — không có
    // "tăng/giảm 1 nấc" — MusicView.tsx giờ luôn gửi kèm số; giữ nhánh
    // tương đối cũ làm fallback phòng khi gọi không kèm số.
    const explicitVolume = t.match(/(\d+)/);
    const nextVolume = explicitVolume
      ? Math.max(0, Math.min(100, Number(explicitVolume[1])))
      : Math.max(0, Math.min(100, vehicleState.media.volume + (/giảm/.test(t) ? -10 : 10)));
    return {
      tool: "control_music",
      args: { action: "set_volume", volume: nextVolume },
      safetyLevel: "S1",
      apply: () => bumpState((s) => { s.media.volume = nextVolume; }),
      displayText: `Đã chỉnh âm lượng ${nextVolume}.`,
    };
  }

  return null;
}

function emptyResult(displayText: string) {
  return { displayText, speakText: displayText, citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false };
}

/**
 * Một câu trả lời sổ tay giả, cắt sẵn thành nhiều đoạn — đủ để thử luồng "nghe
 * tiếp" mà không cần backend, không cần corpus RAG (issue #116).
 *
 * Nội dung chỉ là chỗ giữ chỗ, KHÔNG chép từ sổ tay VF9 thật: corpus có bản
 * quyền và không nằm trong repo. Con số ở đây không được dùng để trả lời ai.
 */
const MANUAL_PARTS = [
  "Áp suất lốp tiêu chuẩn khi lốp nguội là 2,4 bar cho cả bốn bánh.",
  "Khi chở đủ tải hoặc chạy đường dài, tăng lên 2,6 bar ở bánh sau.",
  "Kiểm tra lại áp suất mỗi tháng một lần và trước mỗi chuyến đi xa.",
];

const MANUAL_CITATIONS = [
  {
    citationId: "cit_mock_lop",
    documentTitle: "Sổ tay VF9 (mock)",
    section: "Áp suất lốp",
    page: 2,
    excerpt: MANUAL_PARTS[0],
  },
];

/** Đoạn kế tiếp sẽ đọc. 0 = chưa hỏi câu sổ tay nào. */
let manualCursor = 0;

/** Đúng các câu backend nhận là intent `manual_continue` (xem issue #116). */
function isContinueRequest(text: string): boolean {
  return /nói tiếp|đọc tiếp|nghe tiếp|còn gì nữa/.test(text.toLowerCase());
}

/**
 * Câu hỏi sổ tay mock nhận ra. Cố ý HẸP: mọi câu không khớp vẫn phải rơi về
 * "chưa nghe rõ" như trước, không thì mock biến mỗi câu vu vơ thành câu trả lời
 * sổ tay và không còn phản ánh backend thật nữa.
 */
function isManualQuestion(text: string): boolean {
  return /áp suất lốp/.test(text.toLowerCase());
}

function manualResult(partIndex: number) {
  const text = MANUAL_PARTS[partIndex];
  const hasMore = partIndex < MANUAL_PARTS.length - 1;
  // MỘT chuỗi cho cả hai kênh — backend hợp nhất chúng từ 21/08 (yêu cầu nhóm: màn
  // hình là phụ đề của lời nói). Mock trước đây dán riêng cho màn hình một dấu
  // `(còn tiếp — …)`; nay lời mời tự nó là tín hiệu ấy, còn nút "Nghe tiếp" của
  // `VoiceOverlay` vốn đã bám `hasMoreToRead` chứ không bám chuỗi.
  const noi = hasMore ? `${text} Bạn có muốn nghe tiếp không?` : text;
  return {
    displayText: noi,
    speakText: noi,
    // Trích dẫn GIỮ NGUYÊN qua mọi lượt đọc tiếp — cùng một nguồn, chỉ khác
    // đoạn đang đọc. Xem bảng hợp đồng trong issue #116.
    citations: MANUAL_CITATIONS,
    outcomes: [],
    hasMoreToRead: hasMore,
    moMicNgan: false,
  };
}

/** Domain của từng tool, để mock phát `plan.ready.steps` giống backend thật.
 *
 * Mock là backend giả, nên nó được phép biết bảng này — frontend thật thì không:
 * `real.ts` đọc `domain` do server gửi, không tự suy.
 *
 * LƯU Ý: khoá ở đây là tên tool **của mock**, và mock vẫn đang dùng bảng alias
 * Family-A (`control_ac`, `control_door`, ...) đã bị bỏ khỏi backend ngày 08/08.
 * Đó là lệch có sẵn từ trước, không phải do thay đổi này; đồng bộ lại tên là việc
 * riêng vì nó chạm mọi test của mock.
 */
const MOCK_TOOL_DOMAIN: Record<string, string | null> = {
  control_ac: "hvac",
  set_hvac_fan_level: "hvac",
  control_seat_heating: "seat",
  control_seat_position: "seat",
  control_window: "windows",
  control_door: "doors",
  control_music: "media",
  set_headlight_mode: "lights",
  set_interior_light: "lights",
  set_trunk_state: "trunk",
};

async function runTurn(turnId: string, text: string) {
  emit({ type: "assistant.status", turnId, state: "routing" });
  await delay(MOCK_LATENCY_MS);

  const parsed = parseCommand(text);

  if (!parsed) {
    // Nhánh tra sổ tay (mock) — xét TRƯỚC "chưa nghe rõ" nhưng SAU parseCommand,
    // giống backend thật: lệnh điều khiển thắng, câu không khớp luật mới rơi
    // xuống sổ tay (ADR-011).
    if (isManualQuestion(text)) {
      manualCursor = 0;
      emit({ type: "assistant.status", turnId, state: "retrieving" });
      emit({ type: "assistant.response", turnId, result: manualResult(manualCursor) });
      emit({ type: "turn.completed", turnId });
      return;
    }
    if (isContinueRequest(text) && manualCursor < MANUAL_PARTS.length - 1) {
      // Đọc tiếp KHÔNG tra lại sổ tay — chỉ nhích con trỏ, đúng như backend.
      manualCursor += 1;
      emit({ type: "assistant.response", turnId, result: manualResult(manualCursor) });
      emit({ type: "turn.completed", turnId });
      return;
    }
    emit({
      type: "assistant.response",
      turnId,
      result: emptyResult("Mình chưa nghe rõ, bạn nói lại giúp mình nhé."),
    });
    emit({ type: "turn.completed", turnId });
    return;
  }

  const plan: ActionPlan = {
    planId: genId("plan"),
    sessionId: "ses_mock",
    vehicleId: vehicleState.vehicleId,
    vehicleStateVersion: vehicleState.stateVersion,
    steps: [
      {
        stepId: genId("step"),
        ordinal: 1,
        tool: parsed.tool,
        args: parsed.args,
        safetyLevel: parsed.safetyLevel,
        dependsOn: [],
      },
    ],
    requiresApproval: parsed.safetyLevel === "S2",
  };

  emit({
    type: "plan.ready",
    turnId,
    routeKind: "action",
    planId: plan.planId,
    summary: parsed.displayText,
    requiresApproval: plan.requiresApproval,
    steps: plan.steps.map((step) => ({
      stepId: step.stepId,
      tool: step.tool,
      domain: MOCK_TOOL_DOMAIN[step.tool] ?? null,
      args: step.args as Record<string, unknown>,
    })),
  });

  if (parsed.safetyLevel === "S3") {
    await delay(0);
    emit({
      type: "action.blocked",
      turnId,
      reason: "Xe đang di chuyển — không thể thực hiện thao tác này.",
    });
    emit({
      type: "assistant.response",
      turnId,
      result: emptyResult("Xe đang di chuyển nên mình không thể làm việc này ngay bây giờ."),
    });
    emit({ type: "turn.completed", turnId });
    return;
  }

  if (parsed.safetyLevel === "S2") {
    if (pendingApprovalId) {
      emit({
        type: "error",
        code: "APPROVAL_ALREADY_PENDING",
        message: "Đang có 1 lệnh chờ xác nhận khác.",
        retryable: false,
      });
      emit({
        type: "assistant.response",
        turnId,
        result: emptyResult("Bạn có 1 lệnh khác đang chờ xác nhận rồi."),
      });
      emit({ type: "turn.completed", turnId });
      return;
    }

    const approvalId = genId("appr");
    pendingApprovalId = approvalId;
    pendingByApproval.set(approvalId, { turnId, plan, parsed });
    const expiresAt = new Date(Date.now() + APPROVAL_TIMEOUT_MS).toISOString();
    emit({
      type: "approval.required",
      turnId,
      approvalId,
      planId: plan.planId,
      approvedVehicleStateVersion: vehicleState.stateVersion,
      expiresAt,
    });
    emit({ type: "assistant.status", turnId, state: "waiting_approval" });

    setTimeout(() => {
      if (pendingApprovalId === approvalId) {
        pendingApprovalId = null;
        pendingByApproval.delete(approvalId);
        emit({
          type: "assistant.response",
          turnId,
          result: emptyResult("Đã hết thời gian xác nhận, lệnh bị huỷ."),
        });
        emit({ type: "turn.canceled", turnId, reason: "approval_expired" });
      }
    }, APPROVAL_TIMEOUT_MS);
    return;
  }

  // S1 — không cần duyệt, thực thi ngay
  emit({ type: "assistant.status", turnId, state: "executing" });
  await delay(0);
  parsed.apply();
  emit({ type: "tool.result", turnId, stepId: plan.steps[0].stepId, status: "completed", errorCode: null });
  emit({
    type: "assistant.response",
    turnId,
    result: {
      displayText: parsed.displayText,
      speakText: parsed.displayText,
      citations: [],
      outcomes: [{ stepId: plan.steps[0].stepId, status: "completed" }],
      hasMoreToRead: false,
      moMicNgan: false,
    },
  });
  emit({ type: "turn.completed", turnId });
}

export const mockTurnService: TurnService = {
  async getVehicleState() {
    await delay(0);
    return vehicleState;
  },

  async sendText(text) {
    const turnId = genId("turn");
    emit({ type: "turn.accepted", turnId, inputMode: "text" });
    void runTurn(turnId, text);
    return { turnId };
  },

  async sendVoice(audio) {
    void audio; // mock không thật sự STT — xem ghi chú dưới
    const turnId = genId("turn");
    emit({ type: "turn.accepted", turnId, inputMode: "voice" });
    // Mock STT: giả lập luôn ra 1 câu cố định — real.ts sẽ nhận transcript.final
    // thật từ WS sau khi BE xử lý audio.
    await delay(150);
    const text = "bật điều hòa 22 độ";
    emit({ type: "transcript.final", turnId, text, confidence: 0.95 });
    void runTurn(turnId, text);
    return { turnId };
  },

  async decideApproval(approvalId, decision, approvedVehicleStateVersion) {
    const pending = pendingByApproval.get(approvalId);
    if (!pending || pendingApprovalId !== approvalId) {
      throw new Error("Không tìm thấy approval đang chờ (có thể đã hết hạn).");
    }
    pendingApprovalId = null;
    pendingByApproval.delete(approvalId);
    const { turnId, plan, parsed } = pending;

    if (decision === "reject") {
      emit({
        type: "assistant.response",
        turnId,
        result: emptyResult("Đã huỷ thao tác."),
      });
      emit({ type: "turn.canceled", turnId, reason: "approval_rejected" });
      return;
    }

    if (approvedVehicleStateVersion !== vehicleState.stateVersion) {
      emit({
        type: "assistant.response",
        turnId,
        result: emptyResult("Trạng thái xe đã thay đổi, vui lòng thử lại."),
      });
      emit({ type: "turn.canceled", turnId, reason: "approval_invalidated_state" });
      return;
    }

    emit({ type: "assistant.status", turnId, state: "executing" });
    await delay(0);
    parsed.apply();
    emit({ type: "tool.result", turnId, stepId: plan.steps[0].stepId, status: "completed", errorCode: null });
    emit({
      type: "assistant.response",
      turnId,
      result: {
        displayText: parsed.displayText,
        speakText: parsed.displayText,
        citations: [],
        outcomes: [{ stepId: plan.steps[0].stepId, status: "completed" }],
        hasMoreToRead: false,
        moMicNgan: false,
      },
    });
    emit({ type: "turn.completed", turnId });
  },

  async getCitation(citationId) {
    await delay(0);
    const citation: Citation = {
      citationId,
      documentTitle: "Sổ tay xe VIVI",
      section: "Áp suất lốp",
      page: 42,
      excerpt: "Áp suất lốp chuẩn là 2.2 bar.",
    };
    return citation;
  },

  async setSimSpeed(speedKph, gear) {
    // Mock đóng vai **cả backend lẫn xe ảo**: nó áp luôn quy ước gear mà thật
    // ra `SimulatorRuntime` mới là nơi áp. Chấp nhận được vì ở đây không có
    // MQTT để đi qua — nhưng vì thế mock KHÔNG chứng minh gì về kênh harness,
    // nó chỉ giữ cho màn hình mock hành xử giống màn hình real.
    //
    // Không mô phỏng nhánh 404: mock nghĩa là "có tính năng". Ca cờ tắt chỉ
    // dựng được ở real mode và đã có test riêng trong `real.simSpeed.test.ts`.
    const applied = gear ?? autoGear(speedKph);
    applyMockMotion(speedKph, applied);
    await delay(MOCK_LATENCY_MS);
    // `gear` echo lại đúng thứ người gọi gửi (null khi bỏ trống), giống backend
    // — chứ KHÔNG phải số xe vừa nhận. Xem SimMotionResult.
    const result: SimMotionResult = { accepted: true, speedKph, gear: gear ?? null };
    return result;
  },

  subscribe(onEvent) {
    subscribers.add(onEvent);
    // Mô phỏng "phát ngay sau khi connection.init xong" (docs/api_spec.md:572).
    onEvent({ type: "ui.policy", uiPolicy: computeMockUiPolicy(vehicleState.motion.speedKph) });
    return () => subscribers.delete(onEvent);
  },
};
