"use client";

import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { POI_ITEMS } from "@/lib/fixtures/poi";
import { placesService } from "@/lib/services/places";
import type { PlaceLabel, Places } from "@/lib/services/places";
import { routinesService } from "@/lib/services/routines";
import type {
  FrontSeatKey,
  Routine,
  RoutineDraft,
  RoutineExecution,
  RoutineExecutionStepStatus,
  RoutineIcon,
  RoutineStep,
  WindowKey,
} from "@/lib/services/routines";
import { sessionService } from "@/lib/services/session";
import { ServiceError } from "@/lib/services/shared/errors";
import { BriefcaseIcon, HomeIcon, MoonIcon, MusicNoteIcon, SteeringWheelIcon, SunIcon } from "./AppIcons";
import { useDriverShell } from "./DriverShellProvider";
import type { RoutineExecutionState } from "./DriverShellProvider";

const ICONS: Record<RoutineIcon, ReactNode> = {
  briefcase: <BriefcaseIcon size={20} />,
  home: <HomeIcon size={20} />,
  moon: <MoonIcon size={20} />,
  car: <SteeringWheelIcon size={20} />,
  music: <MusicNoteIcon size={20} />,
  sun: <SunIcon size={20} />,
};
const ICON_OPTIONS = Object.keys(ICONS) as RoutineIcon[];
const MAX_STEPS = 4;

/**
 * Đúng allowlist MVP mà PM/PO chốt ở epic #270 (HVAC power/nhiệt độ/quạt,
 * media, cửa sổ, sưởi/chỉnh ghế trước, dẫn đường Nhà/Cơ quan, đèn cabin) — tập
 * đóng, không cho người dùng gõ hành động tự do.
 *
 * `build()` trả về MẢNG bước, không phải 1 bước: backend chỉ nhận 1 ghế/lệnh
 * (`SetSeatHeatingArgs.seat`, `src/services/tool_registry.py`) nên "sưởi cả 2
 * ghế" không thể gói vào MỘT bước — phải là 2 bước riêng (2 lệnh, đúng khớp
 * cách backend thực thi). Mục "Sưởi ghế (cả hai)" dưới đây thêm 2 bước cùng
 * lúc để người dùng không phải tự bấm 2 lần.
 */
const STEP_KINDS: { action: RoutineStep["action"]; label: string; slots: number; build: () => RoutineStep[] }[] = [
  {
    action: "hvac_power",
    label: "Bật/tắt điều hoà",
    slots: 1,
    build: () => [{ action: "hvac_power", enabled: true }],
  },
  {
    action: "hvac_temperature",
    label: "Chỉnh nhiệt độ",
    slots: 1,
    build: () => [{ action: "hvac_temperature", temperatureC: 24 }],
  },
  {
    action: "hvac_fan_level",
    label: "Chỉnh quạt gió",
    slots: 1,
    build: () => [{ action: "hvac_fan_level", level: 2 }],
  },
  {
    action: "media_control",
    label: "Điều khiển nhạc",
    slots: 1,
    build: () => [{ action: "media_control", controlAction: "play" }],
  },
  {
    action: "window_position",
    label: "Chỉnh cửa sổ",
    slots: 1,
    build: () => [{ action: "window_position", window: "frontLeft", percent: 0 }],
  },
  {
    action: "seat_heating",
    label: "Sưởi ghế (1 bên)",
    slots: 1,
    build: () => [{ action: "seat_heating", seat: "frontLeft", level: 1 }],
  },
  {
    action: "seat_heating",
    label: "Sưởi ghế (cả hai)",
    slots: 2,
    build: () => [
      { action: "seat_heating", seat: "frontLeft", level: 1 },
      { action: "seat_heating", seat: "frontRight", level: 1 },
    ],
  },
  {
    action: "seat_position",
    label: "Chỉnh ghế trước",
    slots: 1,
    build: () => [{ action: "seat_position", seat: "frontLeft", axis: "recline", value: 50 }],
  },
  {
    action: "navigation",
    label: "Dẫn đường",
    slots: 1,
    build: () => [{ action: "navigation", destination: "home" }],
  },
  {
    action: "interior_light",
    label: "Đèn nội thất",
    slots: 1,
    build: () => [{ action: "interior_light", enabled: true }],
  },
];

function stepSummary(step: RoutineStep): string {
  switch (step.action) {
    case "hvac_power":
      return `Điều hoà: ${step.enabled ? "bật" : "tắt"}`;
    case "hvac_temperature":
      return `Nhiệt độ: ${step.temperatureC}°C`;
    case "hvac_fan_level":
      return `Quạt gió mức ${step.level}`;
    case "media_control":
      return step.controlAction === "set_volume" ? `Âm lượng: ${step.volume ?? 0}` : `Nhạc: ${step.controlAction}`;
    case "window_position":
      return `Cửa sổ ${step.window}: ${step.percent}%`;
    case "seat_heating":
      return `Sưởi ghế ${step.seat} mức ${step.level}`;
    case "seat_position":
      return `Ghế ${step.seat} — ${step.axis}: ${step.value}`;
    case "navigation":
      return `Dẫn đường: ${step.destination === "home" ? "Nhà" : "Cơ quan"}`;
    case "interior_light":
      return `Đèn nội thất: ${step.enabled ? "bật" : "tắt"}`;
  }
}

/** Khớp `_SPECS` ở `src/services/tool_registry.py` — S2 chỉ cửa sổ và chỉnh ghế
 * trước (yêu cầu xe đứng yên), còn lại là S1. Không tool nào Routine dùng ở S0/S3. */
const STEP_SAFETY: Record<RoutineStep["action"], "S1" | "S2"> = {
  hvac_power: "S1",
  hvac_temperature: "S1",
  hvac_fan_level: "S1",
  media_control: "S1",
  window_position: "S2",
  seat_heating: "S1",
  seat_position: "S2",
  navigation: "S1",
  interior_light: "S1",
};

/** Phòng dữ liệu cũ/hỏng trong `localStorage` (vd sau khi đổi dải giá trị) —
 * builder trong app này luôn tự kẹp giá trị nên nhánh false gần như không xảy
 * ra qua UI, nhưng vẫn là điều kiện thật cho trạng thái "Lỗi cấu hình". */
function stepWithinRange(step: RoutineStep): boolean {
  switch (step.action) {
    case "hvac_temperature":
      return step.temperatureC >= 16 && step.temperatureC <= 30;
    case "hvac_fan_level":
      return step.level >= 0 && step.level <= 3;
    case "seat_heating":
      return step.level >= 0 && step.level <= 3;
    case "window_position":
      return step.percent >= 0 && step.percent <= 100;
    case "seat_position":
      return step.value >= 0 && step.value <= 100;
    case "media_control":
      return step.controlAction !== "set_volume" || (step.volume !== undefined && step.volume >= 0 && step.volume <= 100);
    default:
      return true;
  }
}

type RoutineStatus = "ready" | "needs_setup" | "error";

/**
 * `needs_setup` đến thẳng từ backend (#272/#370) — KHÔNG tự suy từ việc có
 * bước `navigation` hay không: đó là cổng fail-closed do server quyết (thiếu
 * địa điểm Nhà/Cơ quan, #273/#284), và tự nó hết true khi tài xế gán địa điểm
 * xong mà không cần đổi gì ở đây. Tự đoán từ `steps` (bản trước) sẽ mãi mãi
 * hiện "Cần thiết lập" cho mọi Routine có bước dẫn đường, kể cả sau khi #284
 * đã gán địa điểm xong.
 */
function routineStatus(routine: Routine): RoutineStatus {
  if (routine.steps.some((s) => !stepWithinRange(s))) return "error";
  if (routine.needsSetup) return "needs_setup";
  return "ready";
}

const STATUS_LABELS: Record<RoutineStatus, { label: string; className: string }> = {
  ready: { label: "Sẵn sàng", className: "border-green/50 text-green" },
  needs_setup: { label: "Cần thiết lập", className: "border-amber/50 text-amber" },
  error: { label: "Lỗi cấu hình", className: "border-accent/50 text-accent" },
};

const PLACE_LABELS: Record<PlaceLabel, string> = { home: "Nhà", office: "Cơ quan" };

const WINDOW_LABELS: Record<WindowKey, string> = {
  frontLeft: "Trước trái",
  frontRight: "Trước phải",
  rearLeft: "Sau trái",
  rearRight: "Sau phải",
};
const SEAT_LABELS: Record<FrontSeatKey, string> = { frontLeft: "Trái", frontRight: "Phải" };
const AXIS_LABELS: Record<"fore_aft" | "recline" | "height", string> = {
  fore_aft: "Trước/sau",
  recline: "Ngả lưng",
  height: "Độ cao",
};
type MediaAction = "play" | "pause" | "next" | "previous" | "set_volume";
const MEDIA_ACTION_LABELS: Record<MediaAction, string> = {
  play: "Phát",
  pause: "Tạm dừng",
  next: "Bài tiếp",
  previous: "Bài trước",
  set_volume: "Chỉnh âm lượng",
};

const inputClass =
  "rounded-(--r-sm) border border-line bg-(--panel) px-2 py-1 text-xs text-ink outline-none focus:border-indigo";

/**
 * Dropdown tự vẽ, thay `<select>`/`<option>` gốc của trình duyệt.
 *
 * `<option>` gốc trên Windows/Chrome render bằng theme sáng của hệ điều hành bất
 * kể `color-scheme: dark` khai ở tokens.css — mục đang chọn thì tô xanh đọc được,
 * mọi mục còn lại là chữ nhạt trên nền trắng, gần như không đọc được (ảnh chụp màn
 * hình 26/08). Trình duyệt tự vẽ phần đó, CSS không can thiệp được vào bên trong
 * popup gốc — nên phải tự vẽ danh sách bằng div/button, dùng đúng token màu.
 */
function Select<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (next: T) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const current = options.find((o) => o.value === value);

  return (
    <div ref={rootRef} className={`relative ${className ?? ""}`}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex w-full items-center justify-between gap-2 ${inputClass} py-1.5`}
      >
        <span className="truncate">{current?.label ?? value}</span>
        <span className={`shrink-0 text-[10px] text-ink-dim transition-transform ${open ? "rotate-180" : ""}`}>▾</span>
      </button>
      {open && (
        <ul className="absolute top-[calc(100%+4px)] left-0 z-20 min-w-full overflow-hidden rounded-(--r-sm) border border-line bg-panel-solid/95 py-1 shadow-2xl backdrop-blur-sm">
          {options.map((o) => (
            <li key={o.value}>
              <button
                type="button"
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                className={`block w-full px-3 py-1.5 text-left text-xs whitespace-nowrap ${
                  o.value === value ? "bg-indigo/20 font-semibold text-indigo" : "text-ink hover:bg-(--panel)"
                }`}
              >
                {o.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const LEVEL_OPTIONS = [0, 1, 2, 3].map((l) => ({ value: String(l), label: `Mức ${l}` }));

/** Điều khiển tham số riêng cho từng loại bước — trước đây bước chỉ hiện text tĩnh
 * (vd "Nhiệt độ: 24°C") không sửa được, tài xế tạo mẫu "Đi làm" xong không đổi
 * được thành 26°C. Mỗi nhánh action render đúng field của nó, gọi `onChange` với
 * step đầy đủ cùng action — giữ discriminated union đúng kiểu. */
function StepFields({ step, onChange }: { step: RoutineStep; onChange: (next: RoutineStep) => void }) {
  switch (step.action) {
    case "hvac_power":
    case "interior_light":
      return (
        <Select
          value={step.enabled ? "on" : "off"}
          options={[
            { value: "on", label: "Bật" },
            { value: "off", label: "Tắt" },
          ]}
          onChange={(v) => onChange({ ...step, enabled: v === "on" })}
          className="w-28"
        />
      );
    case "hvac_temperature":
      return (
        <input
          type="number"
          min={16}
          max={30}
          value={step.temperatureC}
          onChange={(e) => onChange({ ...step, temperatureC: Number(e.target.value) })}
          className={`${inputClass} w-20`}
        />
      );
    case "hvac_fan_level":
      return (
        <Select
          value={String(step.level)}
          options={LEVEL_OPTIONS}
          onChange={(v) => onChange({ ...step, level: Number(v) })}
          className="w-24"
        />
      );
    case "media_control":
      return (
        <div className="flex items-center gap-2">
          <Select
            value={step.controlAction}
            options={Object.entries(MEDIA_ACTION_LABELS).map(([value, label]) => ({ value: value as MediaAction, label }))}
            onChange={(controlAction) =>
              onChange(
                controlAction === "set_volume"
                  ? { action: "media_control", controlAction, volume: step.volume ?? 50 }
                  : { action: "media_control", controlAction },
              )
            }
            className="w-36"
          />
          {step.controlAction === "set_volume" && (
            <input
              type="number"
              min={0}
              max={100}
              value={step.volume ?? 0}
              onChange={(e) => onChange({ ...step, volume: Number(e.target.value) })}
              className={`${inputClass} w-20`}
            />
          )}
        </div>
      );
    case "window_position":
      return (
        <div className="flex items-center gap-2">
          <Select
            value={step.window}
            options={Object.entries(WINDOW_LABELS).map(([value, label]) => ({ value: value as WindowKey, label }))}
            onChange={(v) => onChange({ ...step, window: v })}
            className="w-28"
          />
          <input
            type="number"
            min={0}
            max={100}
            value={step.percent}
            onChange={(e) => onChange({ ...step, percent: Number(e.target.value) })}
            className={`${inputClass} w-20`}
          />
          <span className="text-xs text-ink-dim">%</span>
        </div>
      );
    case "seat_heating":
      return (
        <div className="flex items-center gap-2">
          <Select
            value={step.seat}
            options={Object.entries(SEAT_LABELS).map(([value, label]) => ({ value: value as FrontSeatKey, label }))}
            onChange={(v) => onChange({ ...step, seat: v })}
            className="w-20"
          />
          <Select
            value={String(step.level)}
            options={LEVEL_OPTIONS}
            onChange={(v) => onChange({ ...step, level: Number(v) })}
            className="w-24"
          />
        </div>
      );
    case "seat_position":
      return (
        <div className="flex items-center gap-2">
          <Select
            value={step.seat}
            options={Object.entries(SEAT_LABELS).map(([value, label]) => ({ value: value as FrontSeatKey, label }))}
            onChange={(v) => onChange({ ...step, seat: v })}
            className="w-20"
          />
          <Select
            value={step.axis}
            options={Object.entries(AXIS_LABELS).map(([value, label]) => ({
              value: value as "fore_aft" | "recline" | "height",
              label,
            }))}
            onChange={(v) => onChange({ ...step, axis: v })}
            className="w-28"
          />
          <input
            type="number"
            min={0}
            max={100}
            value={step.value}
            onChange={(e) => onChange({ ...step, value: Number(e.target.value) })}
            className={`${inputClass} w-20`}
          />
        </div>
      );
    case "navigation":
      return (
        <Select
          value={step.destination}
          options={[
            { value: "home", label: "Nhà" },
            { value: "office", label: "Cơ quan" },
          ]}
          onChange={(v) => onChange({ ...step, destination: v })}
          className="w-28"
        />
      );
  }
}

const NO_DESTINATION = "__none__";

/**
 * Một hàng cho một nhãn (Nhà hoặc Cơ quan) — ba trạng thái (#283/#284) phải
 * nói khác nhau rõ ràng: chưa gán, hợp lệ (hiện tên), hoặc đã gán nhưng đích
 * biến mất khỏi fixture offline (`valid=false`, `name=null`). Gộp ca cuối vào
 * "chưa gán" là mất đúng thông tin người dùng cần để hiểu vì sao lựa chọn cũ
 * biến mất (đọc docstring `PlacesData` ở `src/models/api.py`).
 */
function PlaceRow({
  label,
  place,
  busy,
  highlighted,
  onChoose,
  onClear,
}: {
  label: PlaceLabel;
  place: Places["home"];
  busy: boolean;
  /** #385: đây là hàng backend vừa báo thiếu cho lượt voice-run vừa rồi. */
  highlighted: boolean;
  onChoose: (destinationId: string) => void;
  onClear: () => void;
}) {
  const options = [
    { value: NO_DESTINATION, label: place ? "— Đổi địa điểm —" : "— Chọn địa điểm —" },
    ...POI_ITEMS.map((poi) => ({ value: poi.id, label: poi.name })),
  ];

  return (
    <div
      data-highlighted={highlighted}
      className={`flex flex-col gap-1.5 rounded-(--r-md) border p-3.5 ${
        highlighted ? "border-accent bg-accent/10" : "border-line bg-panel-solid"
      }`}
    >
      <div className="flex items-center justify-between">
        <p className="font-display text-sm font-semibold text-ink">{PLACE_LABELS[label]}</p>
        {place && (
          <button
            type="button"
            disabled={busy}
            onClick={onClear}
            className="text-xs text-accent hover:underline disabled:opacity-40"
          >
            Bỏ gán
          </button>
        )}
      </div>

      {highlighted && (
        <p className="text-xs font-semibold text-accent">
          Cần địa điểm này để chạy chuỗi lệnh bạn vừa yêu cầu bằng giọng nói.
        </p>
      )}
      {!place && <p className="text-xs text-ink-soft">Chưa thiết lập.</p>}
      {place && place.valid && <p className="text-xs text-ink-soft">Hiện tại: {place.name}</p>}
      {place && !place.valid && (
        <p className="text-xs text-amber">Lựa chọn cũ không còn trong danh sách offline — chọn lại bên dưới.</p>
      )}

      <Select
        value={NO_DESTINATION}
        options={options}
        onChange={(v) => {
          if (v !== NO_DESTINATION) onChoose(v);
        }}
        className="mt-1"
      />
    </div>
  );
}

function PlacesPanel({
  places,
  error,
  busyLabel,
  thieuChoRoutine,
  onChoose,
  onClear,
  onClose,
}: {
  places: Places | null;
  error: string | null;
  busyLabel: PlaceLabel | null;
  /** #385: nhãn backend vừa báo thiếu cho lượt voice-run gần nhất — rỗng ở lối vào bình thường. */
  thieuChoRoutine: PlaceLabel[];
  onChoose: (label: PlaceLabel, destinationId: string) => void;
  onClear: (label: PlaceLabel) => void;
  onClose: () => void;
}) {
  // #404 review: `thieuChoRoutine` là ảnh chụp lúc backend từ chối, không tự cập
  // nhật khi tài xế gán xong. Cả banner lẫn từng hàng phải nhìn vào MỘT danh sách
  // "còn thiếu thật" (giao với `places` hiện tại) — nếu không, gán xong nhãn cuối
  // cùng nhưng banner vẫn báo "cần địa điểm dưới đây" vì nó chỉ đếm ảnh chụp cũ.
  const unresolvedLabels = places ? thieuChoRoutine.filter((label) => !places[label]) : thieuChoRoutine;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="font-display text-lg font-bold text-ink">Địa điểm Nhà &amp; Cơ quan</h2>
        <button type="button" onClick={onClose} className="text-sm text-ink-soft hover:text-ink">
          Đóng
        </button>
      </div>

      {unresolvedLabels.length > 0 ? (
        // #385: mở panel bằng tay ("Địa điểm Nhà & Cơ quan" ở màn danh sách) không
        // đi qua nhánh này — chỉ voice-run bị chặn vì thiếu địa điểm mới thấy câu
        // này, và nó tự hết khi tài xế gán xong (không phải một cờ phải tự tay xoá).
        // Chữ "chuỗi lệnh" chứ không "Routine" — cùng lý do #400: STT tiếng Việt
        // không nghe được từ tiếng Anh, và câu này có thể được đọc lên.
        <p className="text-sm text-accent">
          Bạn vừa yêu cầu chạy một chuỗi lệnh cần {unresolvedLabels.length === 2 ? "cả hai địa điểm" : "địa điểm"} dưới đây.
        </p>
      ) : (
        <p className="text-xs text-ink-dim">
          Các chuỗi lệnh dẫn đường (nhãn &quot;Cần thiết lập&quot;) dùng chung hai địa điểm này.
        </p>
      )}

      {error && <p className="text-sm text-accent">{error}</p>}
      {places === null && !error && <p className="text-sm text-ink-soft">Đang tải…</p>}

      {places !== null && (
        <div className="flex flex-col gap-3">
          {(["home", "office"] as const).map((label) => (
            <PlaceRow
              key={label}
              label={label}
              place={places[label]}
              busy={busyLabel === label}
              highlighted={unresolvedLabels.includes(label)}
              onChoose={(destinationId) => onChoose(label, destinationId)}
              onClear={() => onClear(label)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

type DisplayStepStatus = RoutineExecutionStepStatus | "pending";

const STEP_RESULT_LABELS: Record<DisplayStepStatus, { label: string; className: string }> = {
  pending: { label: "Chờ", className: "border-line text-ink-dim" },
  waiting_approval: { label: "Chờ phê duyệt", className: "border-cyan/50 text-cyan" },
  completed: { label: "Hoàn tất", className: "border-green/50 text-green" },
  failed: { label: "Lỗi", className: "border-accent/50 text-accent" },
  blocked: { label: "Bị chặn", className: "border-accent/50 text-accent" },
  // Cả hai đều CHƯA CHẠY (đúng ngữ nghĩa backend: canceled ở đây luôn kèm
  // `canceled_before_run` — bước đã chạy xong thì không thể "huỷ" được nữa).
  skipped: { label: "Bỏ qua", className: "border-line text-ink-dim" },
  canceled: { label: "Đã huỷ (chưa chạy)", className: "border-line text-ink-dim" },
};

const TERMINAL_STATUS_LABELS: Record<"completed" | "failed" | "blocked" | "user_canceled", { label: string; className: string }> = {
  completed: { label: "Chuỗi lệnh đã hoàn tất", className: "text-green" },
  failed: { label: "Chuỗi lệnh thất bại", className: "text-accent" },
  blocked: { label: "Chuỗi lệnh bị chặn", className: "text-accent" },
  user_canceled: { label: "Chuỗi lệnh đã dừng", className: "text-ink-soft" },
};

/**
 * Panel tiến độ (#292) — hai nguồn KHÔNG có một nguồn "luôn thắng": WS `live`
 * (đúng `executionId` đang xem) và snapshot REST `initial` (poll fallback ở
 * `RoutinesView`, P1 review PR #379 lần 2) mỗi bên có thể là bên có tin mới
 * nhất, tuỳ đường nào tới trước. Trường hợp cụ thể khiến bản trước bị kẹt:
 * WS đã gửi `routine.started`/`routine.step` (nên `matches` đúng) nhưng rớt
 * kết nối trước `routine.finished` — `live.terminal` mãi mãi null trong khi
 * REST poll đã có kết quả cuối. Vì vậy: ai có TERMINAL trước thì người đó
 * thắng, không phải "WS luôn thắng khi khớp execution".
 *
 * KHÔNG đợi WS mới vẽ danh sách bước: dùng `routine.steps` (đã có sẵn phía
 * client, không cần chờ backend) qua `stepSummary()` — mô tả tiếng Việt tốt
 * hơn hẳn `routine.started.steps[]` (backend chỉ trả lại đúng tên action cho
 * những bước CHƯA chạy).
 */
interface CancelState {
  executionId: string;
  status: "requesting" | "requested" | "error";
  message?: string;
}

function RunningRoutinePanel({
  routine,
  initial,
  live,
  cancelState,
  onCancel,
  onClose,
}: {
  routine: Routine;
  initial: RoutineExecution;
  live: RoutineExecutionState | null;
  /** `null` = chưa từng bấm Dừng cho execution này. */
  cancelState: CancelState | null;
  onCancel: () => void;
  onClose: () => void;
}) {
  const matches = live !== null && live.executionId === initial.id;
  const restTerminal: { status: "completed" | "failed" | "blocked" | "user_canceled" } | null =
    initial.status === "running" || initial.status === "waiting_approval" ? null : { status: initial.status };
  const liveTerminal = matches ? live.terminal : null;
  const terminal = liveTerminal ?? restTerminal;

  const resultByIndex = new Map<number, { status: DisplayStepStatus; description: string }>();
  for (const r of initial.results) resultByIndex.set(r.index, { status: r.status, description: r.description });
  // Chỉ để WS đè lên khi REST CHƯA có kết quả cuối: một khi REST đã terminal,
  // backend khoá đúng một `routine.finished` mỗi lần chạy nên sẽ không còn
  // `routine.step` nào tới nữa — REST lúc đó là bản đầy đủ nhất, không phải
  // WS (có thể đang dừng giữa chừng đúng ở lần rớt kết nối đã nói ở trên).
  if (matches && restTerminal === null) {
    for (const [indexKey, r] of Object.entries(live.stepResults)) {
      resultByIndex.set(Number(indexKey), { status: r.status, description: r.description });
    }
  }

  const steps = routine.steps.map((step, index) => {
    const result = resultByIndex.get(index);
    return { index, description: result?.description || stepSummary(step), status: result?.status ?? "pending" };
  });
  const doneCount = steps.filter((s) => s.status !== "pending").length;

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">{routine.name}</h2>
          <p className="text-xs text-ink-soft">
            {doneCount}/{steps.length} bước
          </p>
        </div>
        <button type="button" onClick={onClose} className="text-sm text-ink-soft hover:text-ink">
          Đóng
        </button>
      </div>

      {terminal ? (
        <p className={`text-sm font-semibold ${TERMINAL_STATUS_LABELS[terminal.status].className}`}>
          {TERMINAL_STATUS_LABELS[terminal.status].label}
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-3">
            <p className="text-sm text-ink-soft">Đang chạy…</p>
            <button
              type="button"
              disabled={cancelState !== null && cancelState.status !== "error"}
              onClick={onCancel}
              className="rounded-(--r-sm) border border-accent/60 bg-accent/10 px-3 py-1 text-xs font-semibold text-accent disabled:opacity-50"
            >
              {cancelState && cancelState.status !== "error" ? "Đang dừng…" : "Dừng chuỗi lệnh"}
            </button>
          </div>
          {/* Đúng ngữ nghĩa backend (#298): 200 chỉ nghĩa yêu cầu đã ghi nhận,
              không phải đã dừng — và bước đã chạy KHÔNG được hoàn tác. */}
          <p className="text-[11px] text-ink-dim">
            Dừng chỉ chặn các bước chưa chạy — bước đang/đã thực hiện không bị hoàn tác.
          </p>
          {cancelState?.status === "error" && <p className="text-xs text-accent">{cancelState.message}</p>}
        </div>
      )}

      <ul className="flex flex-col gap-2">
        {steps.map((step) => (
          <li
            key={step.index}
            className="flex items-center justify-between gap-2 rounded-(--r-sm) border border-line bg-panel-solid px-3 py-2"
          >
            <span className="text-sm text-ink">{step.description}</span>
            <span className={`rounded-full border px-1.5 py-0.5 text-[10px] ${STEP_RESULT_LABELS[step.status].className}`}>
              {STEP_RESULT_LABELS[step.status].label}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const emptyDraft: RoutineDraft = { name: "", icon: "sun", steps: [] };

/** Chu kỳ REST fallback khi panel đang chạy chưa thấy terminal qua WS (P1 review PR #379). */
const ROUTINE_POLL_INTERVAL_MS = 3000;

export function RoutinesView() {
  const { routineExecution, routinePreview, routineSetupRequired } = useDriverShell();
  const [routines, setRoutines] = useState<Routine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"list" | "form" | "places" | "running">("list");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<RoutineDraft>(emptyDraft);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [places, setPlaces] = useState<Places | null>(null);
  const [placesError, setPlacesError] = useState<string | null>(null);
  const [placesBusyLabel, setPlacesBusyLabel] = useState<PlaceLabel | null>(null);

  const [runningRoutine, setRunningRoutine] = useState<Routine | null>(null);
  const [runningExecution, setRunningExecution] = useState<RoutineExecution | null>(null);
  const [runStartingId, setRunStartingId] = useState<string | null>(null);
  const [cancelState, setCancelState] = useState<CancelState | null>(null);
  const [highlightedRoutineId, setHighlightedRoutineId] = useState<string | null>(
    routinePreview?.preview.routineId ?? null,
  );
  const routineCardRefs = useRef(new Map<string, HTMLLIElement>());

  useEffect(() => {
    if (!routinePreview) return;
    const timer = setTimeout(() => {
      setHighlightedRoutineId((current) =>
        current === routinePreview.preview.routineId ? null : current,
      );
    }, 30_000);
    return () => clearTimeout(timer);
  }, [routinePreview]);

  useEffect(() => {
    if (!routinePreview || routines === null || mode !== "list") return;
    routineCardRefs.current
      .get(routinePreview.preview.routineId)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [routinePreview, routines, mode]);

  function refresh() {
    routinesService.listRoutines().then(setRoutines, () => setError("Không tải được danh sách chuỗi lệnh."));
  }

  useEffect(refresh, []);

  function openPlaces() {
    setPlacesError(null);
    setPlaces(null);
    setMode("places");
    placesService.getPlaces().then(setPlaces, () => setPlacesError("Không tải được địa điểm."));
  }

  // Issue #385: voice-run vừa bị chặn vì thiếu Nhà/Cơ quan — mở thẳng panel thay vì
  // để tài xế tự tìm nút "Địa điểm Nhà & Cơ quan" từ màn danh sách. `openedForRef`
  // dedupe theo turnId (cùng khuôn `applyRoutineSetupRequired` ở Provider): Provider
  // đã tự dedupe lượt trễ/replay, nhưng effect này còn phải tránh MỞ LẠI panel khi
  // component re-render vì lý do khác (đổi `mode` do tài xế tự đóng panel) trong khi
  // `routineSetupRequired` không đổi.
  //
  // #404 review: `DriverShell.tsx` remount `RoutinesView` bằng `key={routinePreview
  // ?.turnId}` — một preview KHÔNG liên quan tới cũng làm ref này reset về null, nên
  // chỉ dựa vào ref là không đủ: nó sẽ mở lại đúng panel setup CŨ dù tài xế đã gán
  // xong địa điểm từ trước. Xác minh lại với `places` MỚI NHẤT trước khi mở — nếu
  // không còn nhãn nào thiếu thật thì bỏ qua, bất kể ref nói gì.
  const setupOpenedForRef = useRef<string | null>(null);
  useEffect(() => {
    if (!routineSetupRequired || setupOpenedForRef.current === routineSetupRequired.turnId) return;
    setupOpenedForRef.current = routineSetupRequired.turnId;
    let huy = false;
    placesService.getPlaces().then((hienTai) => {
      if (huy) return;
      const conThieu = routineSetupRequired.setup.thieu.some(
        (nhan) => (nhan === "home" || nhan === "office") && !hienTai[nhan],
      );
      if (conThieu) openPlaces();
    }, () => {});
    return () => {
      huy = true;
    };
  }, [routineSetupRequired]);

  function closePlaces() {
    setMode("list");
    // Gán/bỏ gán địa điểm có thể vừa đổi `needs_setup` của các Routine dẫn
    // đường (backend tự tính lại — #370) — nạp lại danh sách để nhãn khớp ngay.
    refresh();
  }

  async function choosePlace(label: PlaceLabel, destinationId: string) {
    setPlacesBusyLabel(label);
    setPlacesError(null);
    try {
      setPlaces(await placesService.setPlace(label, destinationId));
    } catch (err) {
      setPlacesError(err instanceof ServiceError ? err.message : "Không lưu được địa điểm.");
    } finally {
      setPlacesBusyLabel(null);
    }
  }

  async function clearPlace(label: PlaceLabel) {
    setPlacesBusyLabel(label);
    setPlacesError(null);
    try {
      await placesService.clearPlace(label);
      setPlaces(await placesService.getPlaces());
    } catch (err) {
      setPlacesError(err instanceof ServiceError ? err.message : "Không bỏ gán được địa điểm.");
    } finally {
      setPlacesBusyLabel(null);
    }
  }

  async function startRun(routine: Routine) {
    const sessionId = sessionService.getCurrentDriverSession()?.sessionId;
    if (!sessionId) {
      setError("Chưa có phiên lái — không thể chạy chuỗi lệnh.");
      return;
    }
    setRunStartingId(routine.id);
    setError(null);
    try {
      const execution = await routinesService.runRoutine(routine.id, sessionId);
      setRunningRoutine(routine);
      setRunningExecution(execution);
      setCancelState(null);
      setMode("running");
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : "Không chạy được chuỗi lệnh.");
    } finally {
      setRunStartingId(null);
    }
  }

  function closeRunning() {
    setMode("list");
    setRunningRoutine(null);
    setRunningExecution(null);
    setCancelState(null);
  }

  /**
   * Chặn double-submit bằng CHÍNH state, không chỉ `disabled` trên nút — nút
   * có thể nhận double-click/double-tap nhanh hơn một lượt render (#298:
   * "bị khoá chống double submit" là done-when, không phải gợi ý UI).
   * Idempotent phía backend nên gọi lại vẫn an toàn, nhưng tránh vẫn tốt hơn.
   */
  async function cancelRun(executionId: string) {
    if (cancelState?.executionId === executionId && cancelState.status !== "error") return;
    setCancelState({ executionId, status: "requesting" });
    try {
      await routinesService.cancelExecution(executionId);
      // KHÔNG suy ra "đã dừng" từ đây — 200 chỉ nghĩa yêu cầu đã ghi nhận
      // (docstring backend). Trạng thái cuối thật tới qua `routine.finished`
      // (context `routineExecution.terminal`), panel tự ẩn nút khi nó tới.
      setCancelState({ executionId, status: "requested" });
    } catch (err) {
      setCancelState({
        executionId,
        status: "error",
        message: err instanceof ServiceError ? err.message : "Không dừng được chuỗi lệnh.",
      });
    }
  }

  /**
   * P1 review PR #379: `getExecution()` đã có nhưng panel chỉ đọc WS + snapshot
   * `runRoutine()` — mất `routine.finished` (reconnect/WS chập chờn) thì panel
   * kẹt vĩnh viễn ở "Đang chạy…" dù backend đã có kết quả terminal từ lâu.
   *
   * Poll REST làm nguồn sự thật dự phòng trong lúc chưa biết terminal từ đâu
   * cả (WS lẫn REST snapshot đang có). Đọc state mới nhất qua ref bên trong
   * callback thay vì đặt `runningExecution`/`routineExecution` vào dependency
   * — mỗi lần poll trả về hay mỗi `routine.step` tới đều đổi reference của
   * chúng, đặt thẳng vào deps sẽ dựng lại interval liên tục (review
   * "Potential Memory Leak" của bot ở lần review đầu). Effect chỉ còn phụ
   * thuộc `mode`/`executionId` — một interval sống suốt vòng đời của MỘT lần
   * chạy, tự `clearInterval` chính nó ngay khi biết terminal, không đợi
   * React re-render.
   */
  const runningExecutionRef = useRef(runningExecution);
  const routineExecutionRef = useRef(routineExecution);
  // Không gán ref ngay trong thân component (React 19 cấm ghi ref lúc render,
  // "Cannot access refs during render") — đồng bộ qua effect chạy sau MỌI
  // render (không có mảng dependency), luôn xong trước khi tick interval kế
  // tiếp của effect polling bên dưới có dịp đọc lại ref.
  useEffect(() => {
    runningExecutionRef.current = runningExecution;
    routineExecutionRef.current = routineExecution;
  });

  useEffect(() => {
    if (mode !== "running" || !runningExecution) return;
    const executionId = runningExecution.id;

    function terminalKnown(): boolean {
      const current = runningExecutionRef.current;
      if (!current || current.id !== executionId) return true;
      const live = routineExecutionRef.current;
      const restDone = current.status !== "running" && current.status !== "waiting_approval";
      const liveDone = live !== null && live.executionId === executionId && live.terminal !== null;
      return restDone || liveDone;
    }

    if (terminalKnown()) return;
    const timer = setInterval(() => {
      if (terminalKnown()) {
        clearInterval(timer);
        return;
      }
      routinesService.getExecution(executionId).then(setRunningExecution, () => {});
    }, ROUTINE_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
    // Cố ý chỉ phụ thuộc mode/executionId — runningExecution/routineExecution
    // đọc qua ref (xem effect đồng bộ ref phía trên) để một lần chạy chỉ có
    // đúng MỘT interval sống suốt vòng đời của nó, không dựng lại mỗi lần
    // poll/routine.step đổi reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, runningExecution?.id]);

  function openCreate() {
    setDraft(emptyDraft);
    setEditingId(null);
    setError(null);
    setMode("form");
  }

  function openEdit(routine: Routine) {
    setDraft({ name: routine.name, icon: routine.icon, steps: routine.steps });
    setEditingId(routine.id);
    setError(null);
    setMode("form");
  }

  function addStep(build: () => RoutineStep[]) {
    const toAdd = build();
    if (draft.steps.length + toAdd.length > MAX_STEPS) return;
    setDraft((d) => ({ ...d, steps: [...d.steps, ...toAdd] }));
  }

  function removeStep(index: number) {
    setDraft((d) => ({ ...d, steps: d.steps.filter((_, i) => i !== index) }));
  }

  function updateStep(index: number, next: RoutineStep) {
    setDraft((d) => ({ ...d, steps: d.steps.map((s, i) => (i === index ? next : s)) }));
  }

  function moveStep(index: number, dir: -1 | 1) {
    setDraft((d) => {
      const target = index + dir;
      if (target < 0 || target >= d.steps.length) return d;
      const steps = [...d.steps];
      [steps[index], steps[target]] = [steps[target], steps[index]];
      return { ...d, steps };
    });
  }

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      if (editingId) {
        await routinesService.updateRoutine(editingId, draft);
      } else {
        await routinesService.createRoutine(draft);
      }
      setMode("list");
      refresh();
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : "Không lưu được chuỗi lệnh.");
    } finally {
      setSaving(false);
    }
  }

  async function toggleEnabled(routine: Routine) {
    await routinesService.setEnabled(routine.id, !routine.enabled);
    refresh();
  }

  /**
   * Xoá Routine đang chạy trả 409 `ROUTINE_RUNNING` kèm `details.execution_id`
   * (#298, liên quan #281) — thay vì chỉ báo lỗi, đưa thẳng tài xế sang panel
   * đang chạy của chính lần chạy đó để bấm Dừng, đúng gợi ý trong hợp đồng
   * backend ("execution_id... là thứ để nối sang nút Dừng").
   */
  async function confirmDelete() {
    if (!confirmDeleteId) return;
    const routine = routines?.find((r) => r.id === confirmDeleteId) ?? null;
    try {
      await routinesService.deleteRoutine(confirmDeleteId);
      setConfirmDeleteId(null);
      refresh();
    } catch (err) {
      setConfirmDeleteId(null);
      const executionId = err instanceof ServiceError ? (err.details?.execution_id as string | undefined) : undefined;
      if (err instanceof ServiceError && err.code === "ROUTINE_RUNNING" && routine && executionId) {
        try {
          const execution = await routinesService.getExecution(executionId);
          setRunningRoutine(routine);
          setRunningExecution(execution);
          setCancelState(null);
          setMode("running");
          return;
        } catch {
          // getExecution thất bại thì rơi xuống nhánh lỗi chung bên dưới.
        }
      }
      setError(err instanceof ServiceError ? err.message : "Không xoá được chuỗi lệnh.");
    }
  }

  async function restoreDefault(routine: Routine) {
    await routinesService.restoreDefault(routine.id);
    refresh();
  }

  if (mode === "running" && runningRoutine && runningExecution) {
    return (
      <RunningRoutinePanel
        routine={runningRoutine}
        initial={runningExecution}
        live={routineExecution}
        cancelState={cancelState?.executionId === runningExecution.id ? cancelState : null}
        onCancel={() => cancelRun(runningExecution.id)}
        onClose={closeRunning}
      />
    );
  }

  if (mode === "places") {
    return (
      <PlacesPanel
        places={places}
        error={placesError}
        busyLabel={placesBusyLabel}
        onChoose={choosePlace}
        onClear={clearPlace}
        onClose={closePlaces}
        thieuChoRoutine={
          routineSetupRequired?.setup.thieu.filter(
            (nhan): nhan is PlaceLabel => nhan === "home" || nhan === "office",
          ) ?? []
        }
      />
    );
  }

  if (mode === "form") {
    return (
      <div className="flex h-full flex-col gap-4 overflow-y-auto">
        <div className="flex items-center justify-between">
          <h2 className="font-display text-lg font-bold text-ink">{editingId ? "Sửa chuỗi lệnh" : "Tạo chuỗi lệnh mới"}</h2>
          <button type="button" onClick={() => setMode("list")} className="text-sm text-ink-soft hover:text-ink">
            Huỷ
          </button>
        </div>

        <label className="flex flex-col gap-1.5 text-sm">
          <span className="text-ink-soft">Tên chuỗi lệnh</span>
          <input
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
            placeholder="Ví dụ: Đi làm"
            className="rounded-(--r-sm) border border-line bg-(--panel) px-3 py-2 text-ink outline-none focus:border-indigo"
          />
        </label>

        <div className="flex flex-col gap-1.5 text-sm">
          <span className="text-ink-soft">Biểu tượng</span>
          <div className="flex gap-2">
            {ICON_OPTIONS.map((icon) => (
              <button
                key={icon}
                type="button"
                onClick={() => setDraft((d) => ({ ...d, icon }))}
                className={`flex h-10 w-10 items-center justify-center rounded-(--r-sm) border ${
                  draft.icon === icon ? "border-indigo text-indigo" : "border-line text-ink-soft"
                }`}
              >
                {ICONS[icon]}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5 text-sm">
          <div className="flex items-center justify-between">
            <span className="text-ink-soft">Các bước ({draft.steps.length}/{MAX_STEPS})</span>
          </div>
          {draft.steps.length === 0 && (
            <p className="text-xs text-ink-dim">Chưa có bước nào — thêm ít nhất một hành động bên dưới.</p>
          )}
          <ul className="flex flex-col gap-2">
            {draft.steps.map((step, index) => (
              <li key={index} className="flex flex-col gap-2 rounded-(--r-sm) border border-line px-3 py-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs text-ink-soft">
                    {stepSummary(step)}
                    <span
                      className={`rounded-full px-1 text-[9px] font-semibold ${
                        STEP_SAFETY[step.action] === "S2" ? "bg-amber/15 text-amber" : "bg-cyan/15 text-cyan"
                      }`}
                    >
                      {STEP_SAFETY[step.action]}
                    </span>
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      disabled={index === 0}
                      onClick={() => moveStep(index, -1)}
                      className="flex h-7 w-7 items-center justify-center rounded-(--r-sm) border border-line text-ink-soft disabled:opacity-30"
                    >
                      ↑
                    </button>
                    <button
                      type="button"
                      disabled={index === draft.steps.length - 1}
                      onClick={() => moveStep(index, 1)}
                      className="flex h-7 w-7 items-center justify-center rounded-(--r-sm) border border-line text-ink-soft disabled:opacity-30"
                    >
                      ↓
                    </button>
                    <button
                      type="button"
                      onClick={() => removeStep(index)}
                      className="flex h-7 w-7 items-center justify-center rounded-(--r-sm) border border-line text-accent"
                    >
                      ×
                    </button>
                  </div>
                </div>
                <StepFields step={step} onChange={(next) => updateStep(index, next)} />
              </li>
            ))}
          </ul>

          <div className="mt-1 flex flex-wrap gap-2">
            {STEP_KINDS.map((kind) => (
              <button
                key={kind.label}
                type="button"
                disabled={draft.steps.length + kind.slots > MAX_STEPS}
                onClick={() => addStep(kind.build)}
                className="rounded-(--r-sm) border border-line px-2.5 py-1.5 text-xs text-ink-soft hover:border-indigo hover:text-indigo disabled:opacity-30"
              >
                + {kind.label}
              </button>
            ))}
          </div>
        </div>

        {error && <p className="text-sm text-accent">{error}</p>}

        <button
          type="button"
          onClick={submit}
          disabled={saving}
          className="mt-auto rounded-(--r-sm) border border-indigo/60 bg-indigo/15 py-2.5 text-sm font-semibold text-indigo disabled:opacity-50"
        >
          {editingId ? "Lưu thay đổi" : "Tạo chuỗi lệnh"}
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h2 className="font-display text-lg font-bold text-ink">Chuỗi lệnh</h2>
          <p className="mt-0.5 text-xs text-ink-soft">Thử nói &quot;Chạy chuỗi lệnh Thư giãn&quot;</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={openPlaces}
            className="rounded-(--r-sm) border border-line px-3 py-1.5 text-sm text-ink-soft hover:border-indigo hover:text-indigo"
          >
            Địa điểm Nhà &amp; Cơ quan
          </button>
          <button
            type="button"
            onClick={openCreate}
            className="rounded-(--r-sm) border border-indigo/60 bg-indigo/15 px-3 py-1.5 text-sm font-semibold text-indigo"
          >
            + Tạo chuỗi lệnh mới
          </button>
        </div>
      </div>

      {error && <p className="text-sm text-accent">{error}</p>}

      {routines === null && <p className="text-sm text-ink-soft">Đang tải…</p>}

      {routines !== null && routines.length === 0 && (
        <p className="text-sm text-ink-soft">Chưa có chuỗi lệnh nào — tạo chuỗi lệnh đầu tiên của bạn.</p>
      )}

      <ul className="flex flex-col gap-2.5">
        {routines !== null &&
          routinePreview &&
          !routines.some((routine) => routine.id === routinePreview.preview.routineId) && (
            <li
              ref={(node) => {
                if (node) routineCardRefs.current.set(routinePreview.preview.routineId, node);
                else routineCardRefs.current.delete(routinePreview.preview.routineId);
              }}
              data-testid="routine-preview-fallback"
              data-routine-id={routinePreview.preview.routineId}
              data-highlighted={highlightedRoutineId === routinePreview.preview.routineId}
              className={`rounded-(--r-md) border bg-indigo/10 p-3.5 transition-shadow ${
                highlightedRoutineId === routinePreview.preview.routineId
                  ? "border-indigo ring-2 ring-indigo/40"
                  : "border-line"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <p className="font-display text-sm font-semibold text-ink">{routinePreview.preview.routineName}</p>
                <span className="rounded-full border border-indigo/50 px-1.5 py-0.5 text-[10px] text-indigo">
                  Xem trước
                </span>
              </div>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {routinePreview.preview.steps.map((step) => (
                  <span
                    key={step.index}
                    className="rounded-full border border-line-soft px-2 py-0.5 text-[10.5px] text-ink-soft"
                  >
                    {step.description}
                  </span>
                ))}
              </div>
            </li>
          )}
        {routines?.map((routine) => (
          <li
            key={routine.id}
            ref={(node) => {
              if (node) routineCardRefs.current.set(routine.id, node);
              else routineCardRefs.current.delete(routine.id);
            }}
            data-routine-id={routine.id}
            data-highlighted={highlightedRoutineId === routine.id}
            className={`rounded-(--r-md) border bg-panel-solid p-3.5 transition-shadow ${
              highlightedRoutineId === routine.id
                ? "border-indigo ring-2 ring-indigo/40"
                : "border-line"
            }`}
          >
            <div className="flex items-center gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-(--r-sm) bg-indigo/15 text-indigo">
                {ICONS[routine.icon]}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <p className="truncate font-display text-sm font-semibold text-ink">{routine.name}</p>
                  {routine.isDefaultTemplate && (
                    <span className="rounded-full border border-line px-1.5 py-0.5 text-[10px] text-ink-dim">Mẫu</span>
                  )}
                  {(() => {
                    const status = STATUS_LABELS[routineStatus(routine)];
                    return (
                      <span className={`rounded-full border px-1.5 py-0.5 text-[10px] ${status.className}`}>
                        {status.label}
                      </span>
                    );
                  })()}
                  {routine.needsPreview && (
                    <span className="rounded-full border border-amber/50 px-1.5 py-0.5 text-[10px] text-amber">
                      Cần xem trước
                    </span>
                  )}
                </div>
                <p className="text-xs text-ink-soft">{routine.steps.length} bước</p>
              </div>
              <button
                type="button"
                onClick={() => toggleEnabled(routine)}
                aria-pressed={routine.enabled}
                className={`h-6 w-11 shrink-0 rounded-full border transition-colors ${
                  routine.enabled ? "border-indigo bg-indigo/40" : "border-line bg-(--panel)"
                }`}
              >
                <span
                  className={`block h-4.5 w-4.5 rounded-full bg-ink transition-transform ${
                    routine.enabled ? "translate-x-5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>

            <div className="mt-2.5 flex flex-wrap gap-1.5">
              {routine.steps.map((step, i) => (
                <span
                  key={i}
                  className="flex items-center gap-1 rounded-full border border-line-soft px-2 py-0.5 text-[10.5px] text-ink-soft"
                >
                  {stepSummary(step)}
                  <span
                    className={`rounded-full px-1 text-[9px] font-semibold ${
                      STEP_SAFETY[step.action] === "S2" ? "bg-amber/15 text-amber" : "bg-cyan/15 text-cyan"
                    }`}
                  >
                    {STEP_SAFETY[step.action]}
                  </span>
                </span>
              ))}
            </div>

            <div className="mt-2.5 flex items-center gap-3 text-xs">
              {routine.runnable && (
                <button
                  type="button"
                  disabled={runStartingId === routine.id}
                  onClick={() => startRun(routine)}
                  className="font-semibold text-indigo hover:underline disabled:opacity-40"
                >
                  {runStartingId === routine.id ? "Đang chạy…" : "Chạy chuỗi lệnh"}
                </button>
              )}
              <button type="button" onClick={() => openEdit(routine)} className="text-cyan hover:underline">
                Sửa
              </button>
              {routine.isDefaultTemplate ? (
                <button type="button" onClick={() => restoreDefault(routine)} className="text-ink-soft hover:underline">
                  Khôi phục mặc định
                </button>
              ) : confirmDeleteId === routine.id ? (
                <>
                  <span className="text-ink-soft">Xoá chuỗi lệnh này?</span>
                  <button type="button" onClick={confirmDelete} className="font-semibold text-accent hover:underline">
                    Xác nhận xoá
                  </button>
                  <button type="button" onClick={() => setConfirmDeleteId(null)} className="text-ink-soft hover:underline">
                    Thôi
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmDeleteId(routine.id)}
                  className="text-accent hover:underline"
                >
                  Xoá
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
