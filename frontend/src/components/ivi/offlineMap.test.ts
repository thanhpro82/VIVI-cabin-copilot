// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import { POI_ITEMS } from "@/lib/fixtures/poi";
import { OFFLINE_MAP_BOUNDS } from "./LeafletMap";

/**
 * Ảnh nền chế độ demo được neo bằng bốn số bbox chép tay từ osm.org. Không có
 * gì trong TypeScript ràng buộc bốn số ấy với dữ liệu POI — nên test này là thứ
 * duy nhất bắt được hai lỗi rất dễ xảy ra và rất khó nhìn thấy:
 *
 *   1. thêm một POI nằm ngoài vùng ảnh -> lộ trình chạy ra nền trống
 *   2. đổi ảnh mà quên đổi bbox        -> cả bản đồ giãn lệch, đường trôi khỏi phố
 *
 * Cả hai đều không làm test nào khác đỏ, và trên màn hình thì trông "gần đúng".
 */
describe("bbox ảnh bản đồ offline", () => {
  it.each(POI_ITEMS.map((poi) => [poi.id]))("POI %s nằm trong vùng ảnh", (id) => {
    const poi = POI_ITEMS.find((item) => item.id === id)!;
    expect(OFFLINE_MAP_BOUNDS.contains([poi.lat, poi.lon])).toBe(true);
  });

  it("mọi điểm của mọi polyline đều nằm trong vùng ảnh", () => {
    for (const poi of POI_ITEMS) {
      for (const [lat, lon] of poi.polyline) {
        expect(OFFLINE_MAP_BOUNDS.contains([lat, lon])).toBe(true);
      }
    }
  });

  it("vùng ảnh có lề, không sát rìa POI", () => {
    // Sát rìa nghĩa là POI ngoài cùng chạm mép ảnh — kỹ thuật thì "nằm trong",
    // nhưng trên màn hình chấm đích dính vào cạnh và không còn ngữ cảnh nào.
    const lats = POI_ITEMS.map((p) => p.lat);
    const lons = POI_ITEMS.map((p) => p.lon);
    const sw = OFFLINE_MAP_BOUNDS.getSouthWest();
    const ne = OFFLINE_MAP_BOUNDS.getNorthEast();

    expect(Math.min(...lats) - sw.lat).toBeGreaterThan(0.003);
    expect(ne.lat - Math.max(...lats)).toBeGreaterThan(0.003);
    expect(Math.min(...lons) - sw.lng).toBeGreaterThan(0.003);
    expect(ne.lng - Math.max(...lons)).toBeGreaterThan(0.003);
  });
});
