import type { DoorKey } from "./car3dCamera";

/**
 * Tên node lấy trực tiếp từ `public/assets/models/sedan-realistic/scene.gltf`
 * (mục "nodes", KHÔNG phải "meshes").
 *
 * Để riêng khỏi `Car3DViewer.tsx` để test được: file kia import
 * `@google/model-viewer`, thư viện đụng `HTMLElement` ngay lúc import nên kéo
 * vào test là vỡ ở môi trường node. Cùng lý do như `car3dCamera.ts`.
 *
 * Gõ sai một tên ở đây KHÔNG làm vỡ gì cả — `getObjectByName` trả `undefined`,
 * code bỏ qua im lặng, và bộ phận đó đơn giản là không nhúc nhích khi mở cửa.
 * `car3dNodes.test.ts` đối chiếu từng tên với scene.gltf thật để lỗi kiểu đó
 * không phải chờ người nhìn màn hình mới phát hiện.
 */
export const DOOR_NODE_NAMES: Record<DoorKey, string> = {
  frontLeft: "door-front-l_16",
  frontRight: "door-front-r_17",
  rearLeft: "door-rear-l_22",
  rearRight: "door-rear-r_23",
};

/**
 * Một cánh cửa gồm BA node ngang hàng nhau — vỏ cửa, tấm ốp nội thất, kính —
 * chứ không phải một node. Chỉ xoay vỏ cửa thì hai cái kia đứng nguyên tại chỗ,
 * và trên màn hình trông như xe **thừa ra một cánh cửa** đứng im trong khi cánh
 * thật đã mở ra (báo cáo 2026-08-15), đồng thời tấm kính còn lại chắn mất tầm
 * nhìn vào khoang. Cả ba phải chung một pivot bản lề.
 *
 * `door-rear-trim-glass-*` là mảnh kính tam giác CỐ ĐỊNH trên khung xe, không đi
 * theo cửa, nên cố ý không có trong danh sách này.
 *
 * CẢNH BÁO cho ai sửa tiếp: mỗi node có `matrix` riêng đặt nó vào đúng chỗ trên
 * xe (vỏ cửa trước-trái ở y=0.687, kính ở y=1.168). Bản đầu của hàm gộp đã ghi
 * đè hết các vị trí đó thành một giá trị chung, khiến kính bị dồn về đúng vị trí
 * vỏ cửa — nhìn ra thành "kính chồng đè lên cánh cửa". Xem
 * `createHingePivotForGroup`: phải giữ **độ lệch riêng** của từng node.
 */
export const DOOR_GROUP_NODE_NAMES: Record<DoorKey, readonly string[]> = {
  frontLeft: ["door-front-l_16", "door-front-interior-panel-l_14", "door-front-window-glass-l_18"],
  frontRight: ["door-front-r_17", "door-front-interior-panel-r_15", "door-front-window-glass-r_19"],
  rearLeft: ["door-rear-l_22", "door-rear-interior-panel-l_20", "door-rear-window-glass-l_26"],
  rearRight: ["door-rear-r_23", "door-rear-interior-panel-r_21", "door-rear-window-glass-r_27"],
};

export const TRUNK_NODE_NAME = "trunk_99";
