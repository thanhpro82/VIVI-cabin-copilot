/**
 * Domain "Địa điểm cá nhân" (issue #283, epic #270) — Nhà và Cơ quan.
 *
 * Một địa điểm được NHIỀU Routine dùng chung (`navigation` step), nên nó là tài
 * nguyên riêng chứ không phải field lồng trong `Routine` — đổi chỗ làm một lần,
 * mọi Routine dẫn đường tới đó tự cập nhật (xem docstring `src/api/place_routes.py`).
 */

export type PlaceLabel = "home" | "office";

/**
 * Ba trạng thái của MỘT nhãn, và `Places` (dưới) giữ nguyên phân biệt cả ba —
 * không gộp "đã gán nhưng đích biến mất" vào "chưa gán":
 *
 * - `null` — chưa gán.
 * - `{ valid: true, name, destinationId }` — dùng được.
 * - `{ valid: false, name: null, destinationId }` — đã gán, nhưng đích không còn
 *   trong fixture offline. Vẫn giữ `destinationId` cũ để biết đã từng trỏ đâu.
 */
export interface Place {
  label: PlaceLabel;
  destinationId: string;
  name: string | null;
  valid: boolean;
  updatedAt: string;
}

export interface Places {
  home: Place | null;
  office: Place | null;
}

export interface PlacesService {
  /** Cả hai khoá luôn có mặt trong kết quả — `null` nghĩa là chưa gán. */
  getPlaces(): Promise<Places>;
  /** Gán một nhãn vào một điểm đến offline. Trả về CẢ HAI nhãn (khớp response backend). */
  setPlace(label: PlaceLabel, destinationId: string): Promise<Places>;
  /** Bỏ gán — idempotent, không lỗi nếu nhãn vốn chưa gán. */
  clearPlace(label: PlaceLabel): Promise<void>;
}
