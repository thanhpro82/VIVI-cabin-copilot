import type { HeadlightMode } from "@/lib/services/turn/types";

/**
 * Hằng số dùng chung cho bộ chọn chế độ đèn pha, hiện có ở CẢ `RightPanel`
 * (trang chính) lẫn `VehicleControlView` (trang điều khiển xe) — để riêng thì
 * hai chỗ lệch thứ tự/nhãn lúc nào không hay.
 *
 * Đèn pha là enum 3 trạng thái đọc thẳng từ backend, KHÔNG phải toggle boolean:
 * enum không có `off` (UNECE R48 cấm tắt thủ công khi xe có đèn chạy ban ngày,
 * ADR-020) nên "tắt đèn pha" bị router trả `denied` — một toggle hai chiều sẽ
 * có đúng một nửa không bao giờ chạy (issue #115 mục 4).
 *
 * Quyết định PM/PO 2026-08-15: GIỮ bộ điều khiển này trên UI driver. Có lúc đã
 * gỡ đi để chỉ dùng giọng nói, nhưng nhận dạng giọng nói chưa đủ chuẩn nên tài
 * xế bị kẹt — bật đèn rồi không có cách nào đưa về `auto` khi STT nghe sai.
 * Đừng gỡ lại nếu không có quyết định sản phẩm mới.
 *
 * ĐÈN TRẦN cố ý KHÔNG có nút ở đâu cả (yêu cầu 2026-08-15): chỉ giữ 3 chế độ
 * đèn pha trên UI. `set_interior_light` vẫn chạy nguyên vẹn bằng giọng nói.
 */
export const HEADLIGHT_MODES: HeadlightMode[] = ["auto", "low_beam", "high_beam"];

/** Nhãn ngắn cho nút bấm; nhãn đầy đủ (`HEADLIGHT_LABEL`) dùng cho dòng trạng thái. */
export const HEADLIGHT_SHORT_LABEL: Record<HeadlightMode, string> = {
  auto: "Tự động",
  low_beam: "Chiếu gần",
  high_beam: "Chiếu xa",
};

/**
 * Thứ tự xoay vòng cho nút đèn gọn ở `RightPanel`: trang chính chỉ đủ chỗ cho
 * MỘT nút, nên nút đó hiện chế độ đang bật và bấm thì sang chế độ kế tiếp — như
 * công tắc xoay trên xe thật. Bộ 3 nút chọn thẳng nằm ở `VehicleControlView`.
 *
 * Vòng khép kín qua `auto` nên luôn quay lại được chế độ mặc định an toàn bằng
 * nhiều nhất 2 lần bấm, không bao giờ kẹt ở chiếu xa.
 */
export const HEADLIGHT_CYCLE: Record<HeadlightMode, HeadlightMode> = {
  auto: "low_beam",
  low_beam: "high_beam",
  high_beam: "auto",
};
