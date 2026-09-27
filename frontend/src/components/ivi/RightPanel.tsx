"use client";

import dynamic from "next/dynamic";
import { useDriverShell } from "./DriverShellProvider";
import { HEADLIGHT_COMMAND, HEADLIGHT_LABEL } from "@/lib/services/turn/types";
import { HEADLIGHT_CYCLE } from "./headlightControl";

// ssr:false bắt buộc — @google/model-viewer đọc `self` (global trình duyệt)
// ngay khi import, làm vỡ prerender server-side nếu load tĩnh.
const Car3DViewer = dynamic(
  () => import("./Car3DViewer").then((m) => m.Car3DViewer),
  { ssr: false },
);

/** Đúng hợp đồng backend (mqtt_spec.md, api_spec.md): "open"/"closed", không phải "unlocked"/"locked". */
function anyDoorOpen(state: { doors: Record<string, string> } | null): boolean {
  if (!state) return false;
  return Object.values(state.doors).some((s) => s === "open");
}

/** Theo vivi_ivi_vf8style (1).html .rightpanel: 3D chiếm phần lớn (flex:4), khối nút gọn bên dưới (flex:1) — không có card liệt kê trạng thái riêng, tránh thừa khoảng trống. */
export function RightPanel() {
  const { vehicleState, send, connectionState, canDrive } = useDriverShell();
  // Cùng chốt fail-closed với VehicleControlView (issue #241, UAT-007): ba nút
  // này cũng là mặt điều khiển, chỉ khác chỗ đặt. Để chúng bấm được trong khi
  // màn "Điều khiển xe" đã khoá là vừa mâu thuẫn vừa vẫn bắn request đi.
  //
  // `!canDrive` (pool xe ảo hết, issue #261) đi cùng vế vì đúng lập luận đó —
  // hai LÝ DO khác nhau nhưng cùng một hệ quả với ba nút này. Lý do được nói rõ
  // ở StatusBar (hiện trên mọi màn) và ở panel "An toàn" của VehicleControlView,
  // nên ở đây chỉ cần khoá.
  const controlsLocked = connectionState !== "online" || !canDrive;
  const anyOpen = anyDoorOpen(vehicleState);
  const acOn = vehicleState?.hvac.power ?? false;
  // Trang chính chỉ đủ chỗ cho MỘT nút đèn nên nút này xoay vòng chế độ và hiện
  // thẳng chế độ đang bật — xem HEADLIGHT_CYCLE. Chưa đọc được state thì hiện
  // `auto`, mặc định xuất xưởng của xe theo UNECE R48
  // (xem `src/vehicle_sim/state.py`), không phải phỏng đoán tiện tay.
  const headlight = vehicleState?.lights.headlight ?? "auto";

  return (
    <aside className="flex w-100 shrink-0 flex-col gap-2.5 rounded-(--r-lg) border border-line bg-(--panel) p-3.5 xl:w-120 2xl:w-136">
      <Car3DViewer vehicleState={vehicleState} className="min-h-0 flex-6" />

      <div className="flex flex-1 flex-col justify-center gap-2">
        <button
          type="button"
          // "khoá cửa" KHÔNG khớp luật nào của router (`_match_door` đòi câu bắt
          // đầu bằng mở/đóng — xem `_starts_with_command`), nên nó rơi về mặc
          // định tra sổ tay theo ADR-011 và tài xế nhận "Tôi không tìm thấy
          // thông tin này trong sổ tay xe." cho một nút điều khiển. Chiều "mở
          // khóa cửa" thì khớp, nên bug chỉ lộ ở nửa đóng lại. Dùng "đóng cửa" —
          // đúng động từ router đọc, và fan-out đủ cả 4 cửa y như chiều mở.
          onClick={() => send(anyOpen ? "đóng cửa" : "mở khóa cửa")}
          disabled={controlsLocked}
          className={`rounded-(--r-md) border py-2.5 font-display text-[12.5px] font-semibold transition-colors disabled:opacity-40 ${
            anyOpen
              ? "border-accent bg-panel-solid text-accent"
              : "border-line bg-panel-solid text-ink-soft hover:text-ink"
          }`}
        >
          {anyOpen ? "Khoá cửa lại" : "Mở khoá cửa"}
        </button>
        <button
          type="button"
          onClick={() => send(acOn ? "tắt điều hòa" : "bật điều hòa 24 độ")}
          disabled={controlsLocked}
          className={`rounded-(--r-md) border py-2.5 font-display text-[12px] font-semibold transition-colors disabled:opacity-40 ${
            acOn ? "border-amber/50 bg-panel-solid text-amber" : "border-line bg-panel-solid text-ink-soft hover:text-ink"
          }`}
        >
          Điều hoà {acOn ? "đang bật" : "đang tắt"}
        </button>

        <button
          type="button"
          title={`Bấm để chuyển sang ${HEADLIGHT_LABEL[HEADLIGHT_CYCLE[headlight]]}`}
          onClick={() => send(HEADLIGHT_COMMAND[HEADLIGHT_CYCLE[headlight]])}
          disabled={controlsLocked}
          className={`rounded-(--r-md) border py-2.5 font-display text-[12px] font-semibold transition-colors disabled:opacity-40 ${
            headlight === "auto"
              ? "border-line bg-panel-solid text-ink-soft hover:text-ink"
              : "border-cyan bg-panel-solid text-cyan"
          }`}
        >
          Đèn: {HEADLIGHT_LABEL[headlight]}
        </button>
      </div>
    </aside>
  );
}
