"use client";

import { useEffect } from "react";
import { MapContainer, TileLayer, ImageOverlay, Marker, Polyline, useMap } from "react-leaflet";
import { divIcon, latLngBounds } from "leaflet";
import { OFFLINE_ASSETS } from "@/lib/assets";

// Tile OSM chuẩn, đảo màu sang nền tối bằng CSS (`.vivi-dark-tiles`, globals.css).
//
// Trước đây là CARTO `dark_all` — nền tối sẵn, không cần key. Tháng 8/2026 CARTO đổi
// chính sách: raster basemap bắt buộc API key, và request không key bị **in watermark
// "API KEY REQUIRED" thẳng vào ảnh PNG**. Đó là pixel trong file ảnh chứ không phải một
// lớp HTML, nên không CSS hay ad-block nào gỡ được — bản deploy công khai ngày 29/08 dính
// nguyên trang. Xem https://docs.carto.com/faqs/carto-basemaps.
//
// Chọn OSM + đảo màu thay vì xin key CARTO, vì ba lý do:
//   1. Key phải đi qua `NEXT_PUBLIC_*` nên bị nướng vào bundle client — ai xem source cũng
//      thấy, và đồ án này không có chỗ nào giữ được bí mật phía trình duyệt.
//   2. CARTO đang khai tử raster (khuyến nghị chuyển sang vector), nên xin key xong vẫn là
//      một giải pháp có hạn dùng.
//   3. Phép đảo màu ĐÃ có sẵn trong repo cho ảnh bản đồ offline (issue #176) — dùng lại
//      hết một dòng CSS, không thêm phụ thuộc nào.
//
// KHÔNG có `{s}` và `{r}`: OSM đã bỏ subdomain a/b/c, và không phục vụ tile @2x.
//
// Đây vẫn là tài nguyên mạng lúc chạy, KHÔNG phải bước tiến về offline: đổi nhà cung cấp
// chỉ gỡ được chữ xấu. Đường offline thật là `OFFLINE_ASSETS` bên dưới (issue #176).
//
// Bắt buộc giữ dòng attribution OSM theo điều khoản dùng.
const DARK_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/**
 * Chế độ demo: một ảnh raster tĩnh thay cho tile CDN (issue #176).
 *
 * Một ảnh, KHÔNG phải bộ tile tải hàng loạt — ToS của cả CARTO lẫn OSM đều cấm
 * việc đó. Ảnh xuất hợp lệ qua chức năng Share của openstreetmap.org, và dòng
 * `© OpenStreetMap contributors` nằm sẵn trong ảnh nên **đừng crop nó đi**; đó
 * là điều kiện dùng, và cũng là lý do `ImageOverlay` phủ nguyên ảnh.
 *
 * Bốn số dưới đây là bbox THẬT của khung nhìn lúc xuất ảnh, lấy từ đoạn nhúng
 * HTML mà osm.org sinh ra — không phải số ước lượng. Sai bốn số này thì ảnh
 * giãn lệch và polyline trôi khỏi mặt đường, nên đổi ảnh thì phải đổi kèm.
 */
export const OFFLINE_MAP_IMAGE = "/media/map-hanoi.webp";
export const OFFLINE_MAP_BOUNDS = latLngBounds(
  [20.9856431158777, 105.76855659484865],
  [21.035720685584845, 105.86769104003906],
);

// Vị trí xe khi CHƯA dẫn đường — toạ độ demo cố định (Hà Nội), không phải GPS
// thật từ vehicle simulator. Khi có lộ trình thì điểm đầu của `polyline` mới là
// vị trí xe: fixture vẽ cả tuyến từ một gốc chung, nên lấy hai nguồn khác nhau
// sẽ ra một chấm xanh rời khỏi đầu đường kẻ. Phải khớp CHÍNH XÁC điểm [0] của mọi
// polyline trong `src/fixtures/poi.json` (snap OSRM, không phải toạ độ gốc gõ tay) —
// lệch số này là chấm xe nhảy vị trí ngay lúc bắt đầu dẫn đường.
const IDLE_POSITION: [number, number] = [21.0045, 105.8413];

function dotIcon(colorVar: string, size: number) {
  return divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<span style="display:block;width:${size}px;height:${size}px;border-radius:9999px;background:var(${colorVar});box-shadow:0 0 0 4px color-mix(in srgb, var(${colorVar}) 30%, transparent)"></span>`,
  });
}

/**
 * Bắt Leaflet tính lại kích thước khi khung chứa đổi.
 *
 * Leaflet đo container **một lần lúc khởi tạo** rồi cache, và chỉ vẽ tile cho
 * đúng kích thước đã cache. Component này nạp qua `next/dynamic` với một
 * placeholder, nên lúc bản đồ thật gắn vào thì khung có thể chưa đạt kích thước
 * cuối — kết quả là tile phủ một mảng nhỏ giữa khung lớn, phần còn lại trống.
 * Đo được trên trình duyệt thật ngày 19/08.
 *
 * `ResizeObserver` chứ không phải sự kiện `resize` của window: khung này co giãn
 * theo layout flex (mở/đóng RightPanel, đổi view) mà cửa sổ không hề đổi kích
 * thước, nên nghe `window.resize` bỏ sót đúng những lần hay gặp nhất.
 */
function GiuDungKichThuoc() {
  const map = useMap();

  useEffect(() => {
    const el = map.getContainer();
    const observer = new ResizeObserver(() => map.invalidateSize());
    observer.observe(el);
    // Gọi một lần ngay sau khi gắn: ResizeObserver chỉ bắn khi kích thước ĐỔI,
    // nên nếu khung đã đúng cỡ từ trước thì không có lần bắn nào cả.
    map.invalidateSize();
    return () => observer.disconnect();
  }, [map]);

  return null;
}

export interface LeafletMapProps {
  /**
   * Lộ trình `[lat, lon][]` của POI đang được dẫn đường, hoặc `null` khi không
   * dẫn đường / `destination_id` không có trong fixture.
   *
   * Là mảng toạ độ chứ không phải `poiId`: giữ component này thuần trình bày,
   * không tự đi tra fixture. Cùng lý do `Car3DViewer` nhận `vehicleState` qua
   * props thay vì tự gọi API (`frontend/CLAUDE.md`).
   */
  route: readonly [number, number][] | null;

  /**
   * Vị trí xe khi đang chạy animation trình diễn (nút "Bắt đầu" ở `MapView`,
   * nội suy bằng `lib/geo/routeAnimation.ts`). `null`/`undefined` = đứng yên
   * tại điểm đầu tuyến (hành vi cũ). Đây là animation, KHÔNG phải GPS thật —
   * xem docs/demo_runbook.md.
   */
  carPosition?: readonly [number, number] | null;
}

export function LeafletMap({ route, carPosition }: LeafletMapProps) {
  // Một tuyến cần ít nhất hai điểm; một điểm không vẽ được đường và cũng không
  // nói lên vị trí đích, nên đối xử y như không có lộ trình.
  const hasRoute = route !== null && route.length >= 2;
  // `center` KHÔNG đổi theo animation — MapContainer chỉ dùng `center` lúc mount
  // (react-leaflet không tự pan lại khi prop đổi), nên giữ nguyên gốc tuyến làm
  // khung nhìn tĩnh; chỉ marker xe di chuyển bên trong khung đó.
  const center = hasRoute ? route[0] : IDLE_POSITION;
  const current = carPosition ?? center;

  return (
    <MapContainer
      center={center}
      zoom={14}
      minZoom={OFFLINE_ASSETS ? 13.5 : 10}
      maxZoom={OFFLINE_ASSETS ? 16 : 18}
      maxBounds={OFFLINE_ASSETS ? OFFLINE_MAP_BOUNDS : undefined}
      maxBoundsViscosity={OFFLINE_ASSETS ? 1.0 : 0.0}
      zoomControl={true}
      attributionControl={!OFFLINE_ASSETS}
      style={{ height: "100%", width: "100%" }}
    >
      <GiuDungKichThuoc />
      {OFFLINE_ASSETS ? (
        <ImageOverlay
          url={OFFLINE_MAP_IMAGE}
          bounds={OFFLINE_MAP_BOUNDS}
          // Đảo màu sang nền tối — luật ở globals.css `.vivi-offline-map`.
          className="vivi-offline-map"
        />
      ) : (
        <TileLayer url={DARK_TILE_URL} attribution={TILE_ATTRIBUTION} className="vivi-dark-tiles" />
      )}
      {/* Sao chép thành tuple KHẢ BIẾN: `LatLngTuple` của leaflet là mảng ghi
          được, còn `carPosition`/`route` khai báo `readonly` — TypeScript từ
          chối đúng luật. Không nới `readonly` ở props vì nó đang bảo vệ đúng
          thứ cần bảo vệ; chỉ nới đúng ở ranh giới sang thư viện. */}
      <Marker position={[...current]} icon={dotIcon("--cyan", 16)} />
      {hasRoute && (
        <>
          <Marker position={route[route.length - 1]} icon={dotIcon("--accent", 20)} />
          <Polyline
            positions={route as [number, number][]}
            pathOptions={{ color: "var(--cyan)", weight: 5, opacity: 0.9, lineCap: "round" }}
          />
        </>
      )}
    </MapContainer>
  );
}
