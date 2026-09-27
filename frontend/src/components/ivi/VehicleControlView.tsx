"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useDriverShell } from "./DriverShellProvider";
import { HEADLIGHT_COMMAND, HEADLIGHT_LABEL } from "@/lib/services/turn/types";
import type { VehicleState } from "@/lib/services/turn/types";
import { HEADLIGHT_MODES, HEADLIGHT_SHORT_LABEL } from "./headlightControl";

// ssr:false bắt buộc — @google/model-viewer đọc `self` (global trình duyệt)
// ngay khi import, làm vỡ prerender server-side nếu load tĩnh (xem RightPanel.tsx).
const Car3DViewer = dynamic(
  () => import("./Car3DViewer").then((m) => m.Car3DViewer),
  { ssr: false },
);

const AC_MIN_C = 16;
const AC_MAX_C = 30;

// Dải quạt gió của backend là 0..3 (`router.py::_match_hvac` trả
// `fan_level_out_of_range` ngoài dải này). Thanh hiển thị trước đây vẽ 5 vạch
// theo dải mock cũ (0..5) nên mức 3 — mức cao nhất thật — trông như mới hơn nửa.
const FAN_MIN = 0;
const FAN_MAX = 3;
const FAN_STEPS = [0, 1, 2];

// Bộ chọn chế độ đèn pha: hằng số và lý do thiết kế ở `headlightControl.ts`
// (dùng chung với RightPanel).

type Position = keyof VehicleState["windows"] & keyof VehicleState["doors"];

// "bên lái"/"bên phụ"/"sau bên trái"/"sau bên phải" — đúng nguyên văn từ khoá
// router thật đọc (src/agents/router.py Assistant._side()), không phải "bên
// tài"/"hàng sau..." như bản cũ suy đoán theo mock. Sai từ này khiến MỌI lệnh
// cửa/cửa sổ/ghế rơi vào "clarify" khi cắm real mode (phát hiện 2026-08-11).
const POSITIONS: { key: Position; label: string; speech: string }[] = [
  { key: "frontLeft", label: "Bên lái", speech: "bên lái" },
  { key: "frontRight", label: "Bên phụ", speech: "bên phụ" },
  { key: "rearLeft", label: "Sau trái", speech: "sau bên trái" },
  { key: "rearRight", label: "Sau phải", speech: "sau bên phải" },
];

/** Đúng hợp đồng backend (mqtt_spec.md, api_spec.md): "open"/"closed", không phải "unlocked"/"locked". */
function anyDoorOpen(doors: VehicleState["doors"] | undefined): boolean {
  if (!doors) return false;
  return Object.values(doors).some((s) => s === "open");
}

type SeatAxis = "foreAft" | "recline" | "height";

// Router thật chỉ nhận đúng 3 cụm từ khoá trục ghế này (Assistant._match_seat_position):
// "ngả lưng"/"ngả ghế" → recline, "tiến"/"lùi"/"về trước"/"về sau" → fore_aft,
// "nâng ghế"/"hạ ghế" → height. Giá trị % vẫn là mục tiêu tuyệt đối bất kể chọn
// từ nào trong cặp (router không đọc chiều, chỉ dùng từ để phân loại trục).
// `speech` là CẢ CỤM đứng trước %, đã lồng sẵn "ghế lái" (để router nhận ra vị
// trí qua Assistant._side) mà không lặp chữ "ghế" — "ngả ghế lái"/"nâng ghế lái"
// dùng chung 1 chữ "ghế" cho cả 2 phần khớp, "ghế lái tiến" đặt vị trí trước vì
// "tiến" không chứa "ghế" để lồng được.
const SEAT_AXES: { key: SeatAxis; label: string; speech: string }[] = [
  { key: "foreAft", label: "Trượt tới/lui", speech: "ghế lái tiến" },
  { key: "recline", label: "Ngả lưng", speech: "ngả ghế lái" },
  { key: "height", label: "Độ cao", speech: "nâng ghế lái" },
];

/**
 * Bố cục 3 phần theo yêu cầu review: bên trái gồm 2 khối nút (Khoá cửa+Cốp /
 * Điều hoà+Đèn/Cửa sổ), bên phải là xe 3D chiếm đúng 1/3 chiều rộng và cao
 * toàn bộ khung nội dung — thay cho RightPanel dùng chung mọi view (xem
 * DriverShell.MainArea: view "vehicle" không dùng RightPanel nữa, tránh lặp
 * xe 3D + nút khoá/điều hoà/đèn ở 2 nơi cùng lúc). Trạng thái an toàn nằm
 * dưới khung xe 3D (~1/5 chiều cao cột phải), không còn nhét trong card Khoá
 * cửa — theo yêu cầu review 2026-08-09.
 */
export function VehicleControlView() {
  const { vehicleState, send, uiPolicy, connectionState, canDrive } = useDriverShell();
  const driving = (vehicleState?.motion.speedKph ?? 0) > 0;
  const anyOpen = anyDoorOpen(vehicleState?.doors);
  const acOn = vehicleState?.hvac.power ?? false;
  const headlight = vehicleState?.lights.headlight;
  // Fail-closed khi kênh sự kiện chưa/không còn tin được (issue #241, UAT-007)
  // — KHÁC `driving`: đó là khoá cửa/cốp thật theo tốc độ xe (S3), còn đây là
  // khoá TOÀN BỘ mặt control (kể cả AC/đèn, vốn không bị khoá lúc xe chạy) vì
  // không còn kênh tin cậy để biết xe đang ở trạng thái nào.
  //
  // Điều kiện là `!== "online"`, tức khoá cả lúc `connecting` (PM/PO review PR
  // #246): mở app khi backend đã chết sẵn thì chưa có `ui.policy` nào để biết
  // là hỏng, mà nút vẫn bấm được là vẫn bắn request ra network — đúng ca
  // UAT-008. Sliders đã tự khoá qua `lockSmallControls` khi đã có policy, nhưng
  // lúc `connecting` thì `uiPolicy` còn là LOCKED_UI_POLICY nên chúng cũng khoá.
  const controlsLocked = connectionState !== "online";
  // Chế độ chỉ-xem (pool xe ảo hết, issue #261/ADR-028) — LÝ DO KHÁC
  // `controlsLocked`: kết nối vẫn tốt, chỉ là không còn xe nào để cấp cho
  // phiên này. Giữ hai biến tách biệt để thông điệp panel An toàn không lẫn
  // lộn, gộp lại thành `controlsDisabled` chỉ cho mục đích disable nút.
  const readOnly = !canDrive;
  const controlsDisabled = controlsLocked || readOnly;

  // Bấm +/- liên tiếp nhanh: vehicleState chưa kịp cập nhật (send() bất đồng
  // bộ) nên 2 lần bấm dựa trên state cũ sẽ tính ra cùng 1 mục tiêu thay vì
  // tăng/giảm 2 nấc. Giữ 1 giá trị "đang chờ" cục bộ làm nguồn sự thật cho
  // lần bấm tiếp theo. Đồng bộ lại khi server xác nhận — chỉnh state ngay
  // trong lúc render (pattern React chính thức khuyến nghị để "phản ứng khi
  // prop đổi"), không dùng useEffect để tránh cascading render.
  const [pendingTempC, setPendingTempC] = useState<number | null>(null);
  const [lastSeenTempC, setLastSeenTempC] = useState(vehicleState?.hvac.temperatureC);

  if (vehicleState?.hvac.temperatureC !== lastSeenTempC) {
    setLastSeenTempC(vehicleState?.hvac.temperatureC);
    if (pendingTempC != null && vehicleState?.hvac.temperatureC === pendingTempC) {
      setPendingTempC(null);
    }
  }

  const displayTempC = pendingTempC ?? vehicleState?.hvac.temperatureC ?? 24;

  function stepTemp(delta: number) {
    const next = Math.max(AC_MIN_C, Math.min(AC_MAX_C, displayTempC + delta));
    setPendingTempC(next);
    send(`bật điều hòa ${next} độ`);
  }

  // Cùng vấn đề bấm nhanh như nhiệt độ ở trên, cùng cách xử lý.
  const [pendingFanLevel, setPendingFanLevel] = useState<number | null>(null);
  const [lastSeenFanLevel, setLastSeenFanLevel] = useState(vehicleState?.hvac.fanLevel);

  if (vehicleState?.hvac.fanLevel !== lastSeenFanLevel) {
    setLastSeenFanLevel(vehicleState?.hvac.fanLevel);
    if (pendingFanLevel != null && vehicleState?.hvac.fanLevel === pendingFanLevel) {
      setPendingFanLevel(null);
    }
  }

  const displayFanLevel = pendingFanLevel ?? vehicleState?.hvac.fanLevel ?? 0;

  // Router KHÔNG suy diễn tăng/giảm tương đối: nó không đọc vehicle state nên
  // "tăng quạt gió"/"giảm quạt gió" (bản cũ gửi đúng 2 câu này) chỉ trả
  // `clarify/missing_fan_level` — nút bấm như không có tác dụng (issue #115 mục 3).
  // FE tự tính mức rồi gửi số tuyệt đối, y như đã làm cho nhiệt độ và sưởi ghế.
  function stepFan(delta: number) {
    const next = Math.max(FAN_MIN, Math.min(FAN_MAX, displayFanLevel + delta));
    setPendingFanLevel(next);
    send(`đặt quạt gió mức ${next}`);
  }

  // Cửa sổ dùng thanh trượt kéo-thả, chỉ gửi lệnh MỘT LẦN lúc thả tay — vì
  // control_window luôn S2 (cần xác nhận), bấm/kéo nhiều lần nhỏ trước đây
  // tạo ra nhiều lượt duyệt liên tiếp rất khó chịu (feedback 2026-08-09).
  //
  // LƯU Ý: React `onChange` trên input controlled KHÔNG giống `change` event
  // gốc của trình duyệt (chỉ bắn lúc rời chuột) — nó bắn liên tục mỗi khi kéo,
  // y hệt `input`. Dùng `onChange` để gọi send() (như bản trước) khiến mỗi
  // nhích chuột đều gửi lệnh rồi xoá state đang kéo, giá trị bật ngược lại —
  // trông như "không kéo được". Phải tách: đổi giá trị hiển thị bằng
  // onChange, còn commit thật sự bằng onPointerUp (chuột/chạm) + onKeyUp
  // (bàn phím) — 2 event này mới đúng nghĩa "thả tay/kết thúc thao tác".
  const [draggingWindowPercent, setDraggingWindowPercent] = useState<Partial<Record<Position, number>>>({});

  function commitWindow(position: Position) {
    const percent = draggingWindowPercent[position];
    if (percent === undefined) return;
    setDraggingWindowPercent((prev) => {
      const next = { ...prev };
      delete next[position];
      return next;
    });
    const speech = POSITIONS.find((p) => p.key === position)?.speech;
    // Router thật (Assistant._match_window) đòi câu BẮT ĐẦU bằng một trong
    // "mở/đóng/hạ/kéo/nâng" — luôn dùng "mở" + số % tường minh, router đọc số
    // làm mục tiêu tuyệt đối bất kể động từ, không cần khớp nghĩa "mở"/"hạ".
    send(`mở cửa sổ ${speech} ${percent}%`);
  }

  // Ghế lái — cùng cơ chế kéo-thả-chỉ-gửi-lúc-thả với cửa sổ, vì control_seat_position
  // cũng luôn cần xác nhận (S2 đứng yên / S3 chặn khi đang chạy).
  const [draggingSeatPercent, setDraggingSeatPercent] = useState<Partial<Record<SeatAxis, number>>>({});

  function commitSeat(axis: SeatAxis) {
    const percent = draggingSeatPercent[axis];
    if (percent === undefined) return;
    setDraggingSeatPercent((prev) => {
      const next = { ...prev };
      delete next[axis];
      return next;
    });
    const speech = SEAT_AXES.find((a) => a.key === axis)?.speech;
    send(`${speech} ${percent}%`);
  }

  const seatHeating = vehicleState?.seat.frontLeft.heating ?? 0;

  return (
    <div className="flex h-full min-h-0 w-full min-w-0 flex-1 gap-4">
      {/* Bên trái — toàn bộ nút tác vụ */}
      <div className="h-full min-h-0 min-w-0 flex-1 overflow-y-auto pr-1">
        <div className="grid grid-cols-2 gap-3 pb-2">
          {/* Khoá cửa & Cốp — 6 ô đều nhau. S2 khi đứng yên, S3 (chặn) khi đang chạy */}
          <div className="flex flex-col gap-2.5 rounded-(--r-md) border border-line bg-panel-solid p-3.5">
            <div className="flex items-center justify-between font-display text-lg font-semibold text-ink">
              <span>Khoá cửa</span>
              <span className={driving ? "text-accent" : "text-green"}>●</span>
            </div>
          <div className="grid flex-1 grid-cols-2 grid-rows-3 gap-2">
            <button
              type="button"
              // Đo lại trên router thật 2026-08-15: "mở cửa"/"đóng cửa" không
              // kèm vị trí ra `control` với ĐỦ 4 step set_door_state (mỗi step
              // 1 cửa) — không phải `clarify` như comment cũ ở đây khẳng định.
              // Router có fan-out "mọi cửa" thật; chỉ là mỗi step vẫn 1 cửa.
              // Không tô sáng theo `anyOpen` — nút này là hành động (gửi lệnh
              // "toàn xe"), không phải trạng thái của riêng nó. Tô theo anyOpen
              // khiến mở đúng 1 cửa cũng làm nút này sáng lên như thể đã bấm nó.
              onClick={() => send(anyOpen ? "đóng cửa" : "mở cửa")}
              disabled={controlsDisabled}
              className="flex flex-col items-center justify-center gap-1 rounded-(--r-sm) border border-line bg-panel p-2 text-center text-ink-soft hover:text-ink disabled:opacity-40"
            >
              <span className="font-display text-base font-semibold">
                {anyOpen ? "Khoá tất cả" : "Mở khoá tất cả"}
              </span>
              <span className="font-technical text-xs text-ink-dim">Toàn xe</span>
            </button>
            {POSITIONS.map((pos) => {
              const closed = vehicleState?.doors[pos.key] !== "open";
              return (
                <button
                  key={pos.key}
                  type="button"
                  onClick={() => send(`${closed ? "mở cửa" : "đóng cửa"} ${pos.speech}`)}
                  disabled={controlsDisabled}
                  className={`flex flex-col items-center justify-center gap-1 rounded-(--r-sm) border p-2 text-center disabled:opacity-40 ${
                    closed ? "border-line text-ink-soft" : "border-accent/50 text-accent"
                  }`}
                >
                  <span className="font-display text-base font-semibold">
                    {closed ? "Đang khoá" : "Đã mở khoá"}
                  </span>
                  <span className="font-technical text-xs text-ink-dim">{pos.label}</span>
                </button>
              );
            })}
            {(() => {
              const trunkOpen = vehicleState?.trunk.position === "open";
              return (
                <button
                  type="button"
                  onClick={() => send(trunkOpen ? "đóng cốp" : "mở cốp")}
                  disabled={controlsDisabled}
                  className={`flex flex-col items-center justify-center gap-1 rounded-(--r-sm) border p-2 text-center disabled:opacity-40 ${
                    trunkOpen ? "border-accent/50 text-accent" : "border-line text-ink-soft"
                  }`}
                >
                  <span className="font-display text-base font-semibold">{trunkOpen ? "Đang mở" : "Đang đóng"}</span>
                  <span className="font-technical text-xs text-ink-dim">Cốp xe</span>
                </button>
              );
            })()}
          </div>
        </div>

        {/* Điều hoà & Đèn — S1, không cần xác nhận */}
        <div className="flex flex-col gap-2.5 rounded-(--r-md) border border-line bg-panel-solid p-3.5">
          <div className="flex items-center justify-between font-display text-lg font-semibold text-ink">
            <span>Điều hoà</span>
            <span className={acOn ? "text-green" : "text-ink-dim"}>●</span>
          </div>
          <button
            type="button"
            onClick={() => send(acOn ? "tắt điều hòa" : `bật điều hòa ${displayTempC} độ`)}
            disabled={controlsDisabled}
            className={`rounded-(--r-sm) border py-2 font-display text-base font-semibold transition-colors disabled:opacity-40 ${
              acOn ? "border-green/60 bg-panel text-green" : "border-line bg-panel text-ink-soft hover:text-ink"
            }`}
          >
            {acOn ? "Tắt điều hoà" : "Bật điều hoà"}
          </button>
          <div className="flex flex-1 items-center justify-center gap-4">
            <button
              type="button"
              onClick={() => stepTemp(-1)}
              disabled={controlsDisabled || displayTempC <= AC_MIN_C}
              className="flex h-12 w-12 items-center justify-center rounded-(--r-sm) border border-line text-2xl text-ink hover:border-amber disabled:opacity-40"
            >
              −
            </button>
            <div className="text-center">
              <p className="font-technical text-5xl font-semibold text-ink">
                {acOn || pendingTempC != null ? `${displayTempC}°` : "--°"}
              </p>
              <p className="font-technical text-xs text-ink-dim">
                {AC_MIN_C}–{AC_MAX_C}°C
              </p>
            </div>
            <button
              type="button"
              onClick={() => stepTemp(1)}
              disabled={controlsDisabled || displayTempC >= AC_MAX_C}
              className="flex h-12 w-12 items-center justify-center rounded-(--r-sm) border border-line text-2xl text-ink hover:border-amber disabled:opacity-40"
            >
              +
            </button>
          </div>
          <div>
            <p className="mb-1.5 text-sm text-ink-soft">Quạt gió — mức {displayFanLevel}</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => stepFan(-1)}
                disabled={controlsDisabled || displayFanLevel <= FAN_MIN}
                className="rounded-(--r-sm) border border-line px-2.5 py-1.5 text-base text-ink-soft hover:border-amber disabled:opacity-40"
              >
                −
              </button>
              <div className="flex flex-1 gap-1">
                {FAN_STEPS.map((i) => (
                  <div
                    key={i}
                    className={`h-3 flex-1 rounded-sm ${displayFanLevel > i ? "bg-amber" : "bg-line"}`}
                  />
                ))}
              </div>
              <button
                type="button"
                onClick={() => stepFan(1)}
                disabled={controlsDisabled || displayFanLevel >= FAN_MAX}
                className="rounded-(--r-sm) border border-line px-2.5 py-1.5 text-base text-ink-soft hover:border-amber disabled:opacity-40"
              >
                +
              </button>
            </div>
          </div>

          <div>
            <p className="mb-1.5 text-sm text-ink-soft">
              Đèn pha — đang ở{" "}
              <span className="font-semibold text-ink">
                {headlight ? HEADLIGHT_LABEL[headlight] : "—"}
              </span>
            </p>
            <div className="flex gap-1.5">
              {HEADLIGHT_MODES.map((mode) => {
                const active = headlight === mode;
                return (
                  <button
                    key={mode}
                    type="button"
                    aria-pressed={active}
                    onClick={() => send(HEADLIGHT_COMMAND[mode])}
                    disabled={controlsDisabled}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-(--r-sm) border py-2 font-display text-sm font-semibold transition-colors disabled:opacity-40 ${
                      active
                        ? "border-cyan bg-panel text-cyan"
                        : "border-line bg-panel text-ink-soft hover:text-ink"
                    }`}
                  >
                    <span
                      aria-hidden
                      className={`h-1.5 w-1.5 rounded-full ${active ? "bg-cyan" : "bg-transparent"}`}
                    />
                    {HEADLIGHT_SHORT_LABEL[mode]}
                  </button>
                );
              })}
            </div>
          </div>

        </div>

        {/* Cửa sổ — S2, luôn cần duyệt; kéo-thả, chỉ gửi lệnh lúc thả tay */}
        <div className="col-span-2 flex flex-col gap-2.5 rounded-(--r-md) border border-line bg-panel-solid p-3.5">
          <div className="flex items-center justify-between font-display text-lg font-semibold text-ink">
            <span>Cửa sổ</span>
            <span className="text-sm font-normal text-ink-dim">kéo rồi thả — cần xác nhận 1 lần</span>
          </div>
          <div className="grid flex-1 grid-cols-2 gap-x-6 gap-y-4">
            {POSITIONS.map((pos) => {
              const actual = vehicleState?.windows[pos.key] ?? 0;
              const percent = draggingWindowPercent[pos.key] ?? actual;
              return (
                <div key={pos.key} className="flex items-center gap-3 text-base text-ink-soft">
                  <span className="w-20 shrink-0">{pos.label}</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={percent}
                    disabled={uiPolicy.lockSmallControls}
                    style={{ accentColor: "var(--amber)" }}
                    className={`h-2 flex-1 cursor-pointer ${uiPolicy.lockSmallControls ? "opacity-40" : ""}`}
                    onChange={(e) =>
                      setDraggingWindowPercent((prev) => ({
                        ...prev,
                        [pos.key]: Number(e.target.value),
                      }))
                    }
                    onPointerUp={() => commitWindow(pos.key)}
                    onKeyUp={() => commitWindow(pos.key)}
                  />
                  <span className="w-11 shrink-0 text-right font-technical">{percent}%</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Ghế lái — sưởi (S1, tức thì) + vị trí (S2/S3, kéo-thả như cửa sổ) */}
        <div className="col-span-2 flex flex-col gap-2.5 rounded-(--r-md) border border-line bg-panel-solid p-3.5">
          <div className="flex items-center justify-between font-display text-lg font-semibold text-ink">
            <span>Ghế lái</span>
            <span className="text-sm font-normal text-ink-dim">chỉnh vị trí cần xác nhận 1 lần</span>
          </div>
          <div>
            <p className="mb-1.5 text-sm text-ink-soft">Sưởi ghế — mức {seatHeating}</p>
            <div className="flex items-center gap-2">
              <button
                type="button"
                // Router thật (Assistant._match_seat_heating) đọc mức bằng
                // Assistant._number(text) — không có khái niệm "giảm 1 nấc" như
                // mock, luôn cần số tuyệt đối trong câu, nên tính sẵn mục tiêu
                // rồi gửi nguyên câu có số, giống pattern stepTemp() của điều hoà.
                onClick={() => send(`chỉnh sưởi ghế lái mức ${Math.max(0, seatHeating - 1)}`)}
                disabled={controlsDisabled}
                className="rounded-(--r-sm) border border-line px-2.5 py-1.5 text-base text-ink-soft hover:border-amber disabled:opacity-40"
              >
                −
              </button>
              <div className="flex flex-1 gap-1">
                {[0, 1, 2].map((i) => (
                  <div key={i} className={`h-3 flex-1 rounded-sm ${seatHeating > i ? "bg-amber" : "bg-line"}`} />
                ))}
              </div>
              <button
                type="button"
                onClick={() => send(`chỉnh sưởi ghế lái mức ${Math.min(3, seatHeating + 1)}`)}
                disabled={controlsDisabled}
                className="rounded-(--r-sm) border border-line px-2.5 py-1.5 text-base text-ink-soft hover:border-amber disabled:opacity-40"
              >
                +
              </button>
            </div>
          </div>
          <div className="grid flex-1 grid-cols-3 gap-x-6 gap-y-4">
            {SEAT_AXES.map((axis) => {
              const actual = vehicleState?.seat.frontLeft[axis.key] ?? 50;
              const percent = draggingSeatPercent[axis.key] ?? actual;
              return (
                <div key={axis.key} className="flex items-center gap-3 text-base text-ink-soft">
                  <span className="w-24 shrink-0">{axis.label}</span>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={5}
                    value={percent}
                    disabled={uiPolicy.lockSmallControls}
                    style={{ accentColor: "var(--amber)" }}
                    className={`h-2 flex-1 cursor-pointer ${uiPolicy.lockSmallControls ? "opacity-40" : ""}`}
                    onChange={(e) =>
                      setDraggingSeatPercent((prev) => ({
                        ...prev,
                        [axis.key]: Number(e.target.value),
                      }))
                    }
                    onPointerUp={() => commitSeat(axis.key)}
                    onKeyUp={() => commitSeat(axis.key)}
                  />
                  <span className="w-11 shrink-0 text-right font-technical">{percent}%</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>

      {/* Bên phải — xe 3D (4/5 chiều cao) + trạng thái an toàn (1/5 chiều cao) */}
      <div className="flex w-1/3 shrink-0 flex-col gap-3">
        <div className="min-h-0 flex-4 rounded-(--r-lg) border border-line bg-(--panel) p-3.5">
          <Car3DViewer vehicleState={vehicleState} className="h-full" />
        </div>
        <div className="flex flex-1 flex-col justify-center gap-1 rounded-(--r-lg) border border-line bg-panel-solid p-4">
          <div className="flex items-center justify-between">
            <p className="font-display text-base font-semibold text-ink">An toàn</p>
            {/* Trần pool ("Lúc vào phiên: N/3 xe", issue #261 / PR #262 blocker 2) cố
                tình ẩn khỏi UI cho demo — dễ bị hỏi tại sao là ảnh chụp chứ không phải
                số sống (xem lý do đầy đủ ở lịch sử git). Dữ liệu `vehiclePool` và toàn bộ
                logic khoá control theo `canDrive` vẫn giữ nguyên, chỉ ẩn phần hiển thị. */}
          </div>
          {connectionState === "connecting" ? (
            // Chưa xác nhận được backend còn sống (issue #241, PM/PO review PR
            // #246). Phân biệt hẳn với "mất kết nối" bên dưới: ở đây hệ thống
            // chưa biết gì, nói "mất kết nối" là kết luận sớm, mà nói "bình
            // thường" thì lại mời tài xế bấm vào một mặt điều khiển đang chết.
            <p className="flex items-start gap-1.5 text-sm leading-relaxed font-semibold text-amber">
              <span aria-hidden>⋯</span>
              Đang kết nối với hệ thống — các lệnh điều khiển tạm khoá cho tới khi xác nhận được kết nối.
            </p>
          ) : controlsLocked ? (
            // Mất kết nối WS/backend (issue #241, UAT-007) — phải nói RÕ là
            // "không thể" chứ không phải im lặng như hư, để tài xế không tưởng
            // xe vẫn nhận lệnh trong lúc chờ kết nối lại.
            <p className="flex items-start gap-1.5 text-sm leading-relaxed font-semibold text-accent">
              <span aria-hidden>⚠</span>
              Mất kết nối với hệ thống — mọi lệnh điều khiển (cửa/cốp, điều hoà, đèn, cửa sổ, ghế) đang
              bị khoá để đảm bảo an toàn. Vui lòng chờ kết nối lại.
            </p>
          ) : readOnly ? (
            // Hết pool xe ảo (issue #261/ADR-028) — LÝ DO KHÁC `controlsLocked`
            // ở trên: kết nối vẫn tốt, vẫn tra sổ tay/đọc trạng thái xe được,
            // chỉ là không còn xe nào để cấp. Nói rõ để tài xế không tưởng hệ
            // thống hỏng, và không bấm-rồi-mới-biết (mục 3b của issue).
            <p className="flex items-start gap-1.5 text-sm leading-relaxed font-semibold text-amber">
              <span aria-hidden>👁</span>
              Hết xe mô phỏng khả dụng — bạn đang ở chế độ chỉ xem, mọi lệnh điều khiển tạm khoá. Vẫn
              tra được sổ tay và xem trạng thái xe bình thường.
            </p>
          ) : driving && anyOpen ? (
            // Cửa đã mở TỪ TRƯỚC lúc xe đứng yên rồi mới tăng tốc — không có
            // lệnh điều khiển nào chạy để S3 chặn (S3 chỉ chặn LỆNH mới, xem
            // ADR-010), nên xe mô phỏng không tự đóng cửa lại (xe thật cũng
            // không tự actuator đóng sập cửa khi đang chạy — nguy hiểm nếu có
            // tay/chân còn kẹt ở cửa). Chỉ cảnh báo rõ, không tự hành động.
            <p className="flex items-start gap-1.5 text-sm leading-relaxed font-semibold text-accent">
              <span aria-hidden>⚠</span>
              Cửa đang mở trong khi xe chạy {vehicleState?.motion.speedKph} km/h — không thể đóng bằng
              giọng nói lúc này (lệnh cửa bị khoá cứng S3 khi đang chạy). Hãy dừng xe hẳn rồi đóng lại.
            </p>
          ) : driving ? (
            <p className="text-sm leading-relaxed text-amber">
              Xe đang chạy {vehicleState?.motion.speedKph} km/h — cửa/cốp bị khoá cứng (S3), không thể mở.
              Cửa sổ vẫn dùng được nhưng cần xác nhận.
            </p>
          ) : (
            <p className="text-sm leading-relaxed text-ink-soft">
              Xe đang đứng yên — có thể mở khoá cửa/cốp, thao tác cần xác nhận qua hộp thoại (S2).
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
