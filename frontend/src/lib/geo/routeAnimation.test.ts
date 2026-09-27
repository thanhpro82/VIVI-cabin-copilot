import { describe, expect, it } from "vitest";
import { noiSuyTrenTuyen } from "./routeAnimation";

describe("noiSuyTrenTuyen", () => {
  const tuyenThang: [number, number][] = [
    [21.0, 105.0],
    [21.01, 105.0],
  ];

  it("tiLe<=0 trả đúng điểm đầu", () => {
    expect(noiSuyTrenTuyen(tuyenThang, 0)).toEqual(tuyenThang[0]);
    expect(noiSuyTrenTuyen(tuyenThang, -0.5)).toEqual(tuyenThang[0]);
  });

  it("tiLe>=1 trả đúng điểm cuối", () => {
    expect(noiSuyTrenTuyen(tuyenThang, 1)).toEqual(tuyenThang[1]);
    expect(noiSuyTrenTuyen(tuyenThang, 2)).toEqual(tuyenThang[1]);
  });

  it("tiLe=0.5 trên đoạn thẳng một khúc thì ra đúng trung điểm", () => {
    const [lat, lon] = noiSuyTrenTuyen(tuyenThang, 0.5);
    expect(lat).toBeCloseTo(21.005, 3);
    expect(lon).toBeCloseTo(105.0, 5);
  });

  it("tuyến nhiều khúc — vị trí luôn nằm trong bbox của tuyến, di chuyển đơn điệu theo tiLe", () => {
    const tuyen: [number, number][] = [
      [21.0045, 105.8413],
      [20.9985, 105.8411],
      [20.9981, 105.8405],
      [20.9991, 105.8365],
      [20.9955, 105.801],
    ];
    const laiLat = tuyen.map((p) => p[0]);
    const laiLon = tuyen.map((p) => p[1]);
    const minLat = Math.min(...laiLat);
    const maxLat = Math.max(...laiLat);
    const minLon = Math.min(...laiLon);
    const maxLon = Math.max(...laiLon);

    let khoangCachTruoc = 0;
    for (let i = 0; i <= 10; i++) {
      const t = i / 10;
      const [lat, lon] = noiSuyTrenTuyen(tuyen, t);
      expect(lat).toBeGreaterThanOrEqual(minLat - 1e-6);
      expect(lat).toBeLessThanOrEqual(maxLat + 1e-6);
      expect(lon).toBeGreaterThanOrEqual(minLon - 1e-6);
      expect(lon).toBeLessThanOrEqual(maxLon + 1e-6);

      // Khoảng cách Euclid thô từ điểm đầu phải không giảm khi t tăng — xe
      // không bao giờ "đi lùi" trên tuyến.
      const dLat = lat - tuyen[0][0];
      const dLon = lon - tuyen[0][1];
      const khoangCach = Math.sqrt(dLat * dLat + dLon * dLon);
      expect(khoangCach).toBeGreaterThanOrEqual(khoangCachTruoc - 1e-9);
      khoangCachTruoc = khoangCach;
    }
  });
});
