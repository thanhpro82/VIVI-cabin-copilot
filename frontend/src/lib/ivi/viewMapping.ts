import type { PlanReadyStep } from "@/lib/services/turn/types";
import type { ViewName } from "@/components/ivi/DriverShellProvider";

/**
 * Ánh xạ "vừa làm gì" -> "hiện màn nào". Bảng này sống **hoàn toàn ở frontend**.
 *
 * Backend không bao giờ biết tên màn hình: nó phát `domain` (`hvac`) và `tool`
 * (`open_app`), còn `"vehicle"` là tri thức của layout. Cùng ranh giới mà
 * `ui.policy` đang giữ — BE đưa dữ kiện, FE quyết cách hiển thị — nên đổi bố cục
 * IVI không kéo theo sửa backend và sửa test backend.
 *
 * Danh sách domain lấy từ `Domain` trong `src/models/vehicle.py`. `motion` cố ý
 * không có mặt: nó là tốc độ, không phải thứ có màn hình riêng.
 */
const VIEW_BY_DOMAIN: Record<string, ViewName> = {
  hvac: "vehicle",
  seat: "vehicle",
  windows: "vehicle",
  doors: "vehicle",
  lights: "vehicle",
  trunk: "vehicle",
  media: "music",
  navigation: "map",
};

/**
 * `open_app` có `domain = null` — nó là tool cục bộ của IVI, không có domain
 * MQTT (ADR-023) — nên chỉ `args.app` mới nói được là app nào. Enum đóng ba app
 * ở backend (`src/agents/tools/app.py`); bảng này khớp đúng ba.
 */
const VIEW_BY_APP: Record<string, ViewName> = {
  youtube: "youtube",
  tiktok: "tiktok",
  spotify: "spotify",
};

/**
 * Màn hình tương ứng với một bước kế hoạch, hoặc `null` nếu bước ấy không có
 * màn nào.
 *
 * `null` là câu trả lời hợp lệ, không phải lỗi: `query_manual` và
 * `get_vehicle_state` chạy xong mà không có gì để hiện, và nhảy màn cho chúng là
 * giật màn hình của tài xế vì một lý do họ không thấy được.
 */
export function viewForStep(step: PlanReadyStep): ViewName | null {
  if (step.tool === "open_app") {
    const app = step.args?.app;
    return typeof app === "string" ? (VIEW_BY_APP[app] ?? null) : null;
  }
  return step.domain ? (VIEW_BY_DOMAIN[step.domain] ?? null) : null;
}
