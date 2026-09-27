import fixture from "./poi.json";

/**
 * POI mock — đọc bản sao đồng bộ của `src/fixtures/poi.json`.
 *
 * Bản sao là thứ SINH RA bởi `scripts/sync_fixtures.ps1`; `tests/test_services/
 * test_fixtures.py` so từng byte hai bản. Sửa nguồn rồi chạy lại script, đừng sửa
 * JSON ở đây.
 *
 * `id` là **khoá nối** với backend: router tra `aliases` ra `poi_id`, simulator
 * đặt nó vào `navigation.destination_id`, và IVI tra ngược lại chính file này để
 * biết vẽ lộ trình nào. Backend không bao giờ gửi toạ độ — nó chỉ gửi id.
 */
export interface Poi {
  id: string;
  name: string;
  category: string;
  aliases: string[];
  lat: number;
  lon: number;
  distance_km: number;
  eta_min: number;
  /** `[lat, lon][]` — lộ trình viết tay, KHÔNG phải định tuyến thật (issue #175). */
  polyline: [number, number][];
}

export const POI_ITEMS: readonly Poi[] = fixture.items as Poi[];

/**
 * Tra POI theo `destination_id` backend trả về.
 *
 * `undefined` khi không khớp — và chỗ gọi phải hiện trạng thái rỗng chứ không
 * được vẽ bừa một lộ trình khác. Router có guard `poi_not_in_fixture` nên ca này
 * đáng lẽ không xảy ra, nhưng "đáng lẽ" không phải lý do để màn hình nói dối.
 */
export function findPoi(id: string | null | undefined): Poi | undefined {
  return id ? POI_ITEMS.find((poi) => poi.id === id) : undefined;
}

/**
 * Lọc POI theo chữ gõ trong ô tìm kiếm (issue #226 A6).
 *
 * So khớp trên `name` VÀ `aliases` — chỉ so `name` thì gõ "cà phê" không ra
 * "Highlands Coffee Nguyễn Trãi" (tên không chứa "cà phê", chỉ alias có).
 * `""`/khoảng trắng trả về mảng rỗng thay vì cả sáu POI, vì gọi nơi dùng là để
 * MỞ danh sách gợi ý khi có chữ, không phải liệt kê sẵn khi ô còn trống.
 */
export function timKiemPoi(query: string): readonly Poi[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return POI_ITEMS.filter(
    (poi) =>
      poi.name.toLowerCase().includes(q) ||
      poi.aliases.some((alias) => alias.toLowerCase().includes(q)),
  );
}
