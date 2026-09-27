// Nội suy vị trí trên một tuyến đường theo tỉ lệ hoàn thành — dùng cho animation
// trình diễn nút "Bắt đầu" (MapView). Nội suy theo TỈ LỆ QUÃNG ĐƯỜNG (haversine),
// không phải tỉ lệ số điểm, để chấm xe di chuyển đều tốc độ qua các đoạn dài/ngắn
// khác nhau của polyline (các đoạn OSRM `simplified` không đều nhau).
//
// Đây là animation trình diễn, KHÔNG phải toạ độ GPS thật từ vehicle simulator —
// xem docs/demo_runbook.md.

type LatLon = readonly [number, number];

function khoangCachMet(a: LatLon, b: LatLon): number {
  const R = 6371000;
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLon = toRad(b[1] - a[1]);
  const lat1 = toRad(a[0]);
  const lat2 = toRad(b[0]);
  const sinDLat = Math.sin(dLat / 2);
  const sinDLon = Math.sin(dLon / 2);
  const h = sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLon * sinDLon;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/**
 * `tiLe` 0..1 trên chiều dài tuyến. Trả điểm đầu khi `tiLe<=0`, điểm cuối khi
 * `tiLe>=1`. Gọi nơi đã kiểm `route.length >= 2` (route ngắn hơn không phải
 * một tuyến hợp lệ — xem `hasRoute` ở `LeafletMap.tsx`).
 */
export function noiSuyTrenTuyen(route: readonly LatLon[], tiLe: number): LatLon {
  if (tiLe <= 0) return route[0];
  if (tiLe >= 1) return route[route.length - 1];

  const doDaiDoan: number[] = [];
  let tongDoDai = 0;
  for (let i = 1; i < route.length; i++) {
    const d = khoangCachMet(route[i - 1], route[i]);
    doDaiDoan.push(d);
    tongDoDai += d;
  }

  const quangDaDi = tiLe * tongDoDai;
  let daDi = 0;
  for (let i = 0; i < doDaiDoan.length; i++) {
    const doanNay = doDaiDoan[i];
    if (daDi + doanNay >= quangDaDi || i === doDaiDoan.length - 1) {
      const tiLeTrongDoan = doanNay === 0 ? 0 : (quangDaDi - daDi) / doanNay;
      const [lat1, lon1] = route[i];
      const [lat2, lon2] = route[i + 1];
      return [lat1 + (lat2 - lat1) * tiLeTrongDoan, lon1 + (lon2 - lon1) * tiLeTrongDoan];
    }
    daDi += doanNay;
  }
  return route[route.length - 1];
}
