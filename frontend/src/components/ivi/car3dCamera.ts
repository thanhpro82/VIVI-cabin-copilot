import type { VehicleState } from "@/lib/services/turn/types";

/**
 * Phần tính góc camera của `Car3DViewer`, tách riêng vì `Car3DViewer.tsx`
 * import `@google/model-viewer` — thư viện đó đụng `HTMLElement` ngay lúc
 * import nên kéo cả file vào test là vỡ ở môi trường node. Cùng lý do và cùng
 * cách xử lý như `voiceOverlayClose.ts`.
 */

export type DoorKey = keyof VehicleState["doors"];

export const ORBIT_DEFAULT = "25deg 75deg auto";

/**
 * Góc phương vị (theta) để camera nhìn về phía từng cửa. Trong model-viewer,
 * vị trí camera = target + r·(sinθ·sinφ, cosφ, cosθ·sinφ) → **θ=0 là nhìn từ
 * phía trước xe** (+Z, xem chú thích trục ở DOOR_OPEN_SIGN trong
 * Car3DViewer.tsx) và **θ=90° là từ bên trái** (+X, phía "l" trong tên node).
 * Cửa trước lệch về đầu xe, cửa sau lệch về đuôi, để khung hình có cả cửa lẫn
 * phần thân liền kề chứ không dán phẳng vào cánh cửa.
 */
export const DOOR_VIEW_THETA_DEG: Record<DoorKey, number> = {
  frontLeft: 70,
  rearLeft: 110,
  frontRight: -70,
  rearRight: -110,
};

/**
 * Góc ngẩng giữ nguyên như khung mặc định, và KHOẢNG CÁCH cũng vậy (`auto`).
 *
 * Đã thử ghé sát vào để "nhìn vào buồng lái" rồi phải bỏ (2026-08-15): model
 * này không chịu được cận cảnh lúc cửa mở. Kính, tấm ốp nội thất và vỏ cửa là
 * ba mesh RỜI ngang hàng nhau; mở cửa thì vỏ cửa xoay còn kính đứng nguyên tại
 * chỗ, nên soi gần vào là thấy ngay các mảnh rời rạc, chồng chéo. Gộp chúng vào
 * cùng pivot cũng không cứu được (xem chú thích dài trong Car3DViewer.tsx) —
 * node kính của model nằm ở nửa dưới thân cửa chứ không phải trên đường bệ cửa.
 *
 * Nên camera chỉ XOAY về phía cửa đang mở, giữ nguyên khoảng cách khung mặc
 * định. Ở khoảng cách đó khuyết tật của model nhỏ trên màn hình và không ai để
 * ý — đúng như trạng thái vẫn chạy trên `develop` từ trước tới nay. Muốn cận
 * cảnh khoang lái thì phải thay model, không phải chỉnh camera.
 */
export const DOOR_VIEW_PHI_DEG = 75;

/**
 * Cửa nào đang mở thì camera ngó về đó. Nhiều cửa cùng mở thì ưu tiên theo thứ
 * tự dưới đây (ghế lái trước) — camera chỉ có một hướng, nên phải chọn, và
 * chọn cố định theo thứ tự dễ đoán hơn là nhảy theo cửa đổi gần nhất.
 */
const DOOR_VIEW_PRIORITY: DoorKey[] = ["frontLeft", "frontRight", "rearLeft", "rearRight"];

/** Đúng hợp đồng backend (mqtt_spec.md, api_spec.md): "open"/"closed". */
export function isDoorVisuallyOpen(status: string): boolean {
  return status === "open";
}

export function firstOpenDoor(doors: VehicleState["doors"]): DoorKey | null {
  return DOOR_VIEW_PRIORITY.find((key) => isDoorVisuallyOpen(doors[key])) ?? null;
}

/** Camera nên đứng ở đâu. Chỉ đổi góc, không bao giờ đổi khoảng cách. */
export function computeCameraView(
  openDoor: DoorKey | null,
  windowOpenPercent: number,
): { orbit: string } {
  if (openDoor) return { orbit: `${DOOR_VIEW_THETA_DEG[openDoor]}deg ${DOOR_VIEW_PHI_DEG}deg auto` };
  if (windowOpenPercent > 0) return { orbit: `${18 + windowOpenPercent * 0.2}deg 78deg auto` };
  return { orbit: ORBIT_DEFAULT };
}
