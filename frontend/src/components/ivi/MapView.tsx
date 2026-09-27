"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { type Poi, findPoi, timKiemPoi } from "@/lib/fixtures/poi";
import { noiSuyTrenTuyen } from "@/lib/geo/routeAnimation";
import { useDriverShell } from "./DriverShellProvider";

// Thời lượng animation trình diễn nút "Bắt đầu" — nén còn 30s thay vì `eta_min`
// thật (6-14 phút) vì demo không thể chờ thật từng ấy. ĐÂY LÀ ANIMATION THUẦN FE,
// không đụng MQTT/vehicle_sim, không phải GPS thật — xem docs/demo_runbook.md.
const DEMO_DURATION_MS = 30_000;

// ssr:false bắt buộc — Leaflet đọc `window`/`document` ngay khi import, làm
// vỡ prerender server-side nếu load tĩnh (cùng lý do với Car3DViewer/model-viewer).
const LeafletMap = dynamic(
  () => import("./LeafletMap").then((m) => m.LeafletMap),
  { ssr: false, loading: () => <div className="absolute inset-0 bg-bg2" /> },
);

/** Bản đồ Leaflet thật, tile CARTO dark (miễn phí, không cần API key — Google
 * Maps Static API cần key trả phí, không hợp đồ án).
 *
 * Lộ trình và ETA đọc từ `src/fixtures/poi.json`, cùng file mà router tra alias
 * để ra `destination_id` (#171). Backend **chỉ gửi id** — không toạ độ, không
 * quãng đường — nên bảng tra nằm ở đây là đúng chỗ, không phải thiếu sót.
 *
 * Polyline lấy từ OSRM (`router.project-osrm.org`) NƯỚNG SẴN vào fixture lúc dev
 * (2026-08-21) — đường đi khớp đường thật, nhưng vẫn KHÔNG có GPS thật từ vehicle
 * simulator, và xe luôn xuất phát từ một toạ độ demo cố định, không phải vị trí
 * xe thật. Đừng nâng lời hứa lên "chỉ đường thật từ vị trí hiện tại" khi chưa có
 * cái đó — xem `ban-do-nut-bat-dau-va-lo-trinh-2026-08-21.md` §3 Phương án A. */
export function MapView() {
  const { vehicleState, send } = useDriverShell();
  const navigating = (vehicleState?.navigation.status ?? "idle") !== "idle";
  // Đọc `status` chứ không suy từ `destinationId != null`: `status` là cờ
  // canonical cho "đang dẫn đường". Hai trường di chuyển cùng nhau — huỷ dẫn
  // đường xoá cả hai trong một lần (`vehicle_sim/state.py:_apply_navigation`) —
  // nên đây là chuyện đọc đúng nguồn, KHÔNG phải chống một ca lệch pha nào cả.
  const poi = navigating ? findPoi(vehicleState?.navigation.destinationId) : undefined;

  // Animation trình diễn nút "Bắt đầu": `dangChay` bật/tắt vòng lặp
  // requestAnimationFrame bên dưới, `tiLe` là % quãng đường đã "đi" (0..1),
  // dùng để nội suy vị trí chấm xe trên polyline VÀ đếm ngược ETA hiển thị.
  // Không có state nào trong đây rời khỏi component — không gọi backend,
  // không đổi `vehicleState.navigation` (xem docs/demo_runbook.md).
  const [dangChay, setDangChay] = useState(false);
  const [tiLe, setTiLe] = useState(0);
  const rafIdRef = useRef<number | null>(null);

  // Đổi điểm đến (kể cả huỷ dẫn đường bằng giọng nói giữa lúc animation đang
  // chạy) phải reset về đứng yên — nếu không chấm xe kẹt lại giữa tuyến cũ
  // trong lúc UI đã chuyển sang tuyến mới hoặc về trạng thái "chưa có điểm đến".
  //
  // setState NGAY TRONG THÂN RENDER (không phải trong effect): đây là pattern
  // React khuyến nghị cho "reset state khi prop đổi" — React nhận ra và render
  // lại ngay trong cùng lượt commit, không có lượt vẽ trung gian với state cũ,
  // và không dính lỗi lint react-hooks/set-state-in-effect (setState đồng bộ
  // trong effect có thể gây render-chồng-render).
  const [tuyenDaXuLy, setTuyenDaXuLy] = useState(poi?.id);
  if (poi?.id !== tuyenDaXuLy) {
    setTuyenDaXuLy(poi?.id);
    setDangChay(false);
    setTiLe(0);
  }

  useEffect(() => {
    if (!dangChay) return;
    const batDauLuc = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - batDauLuc) / DEMO_DURATION_MS);
      setTiLe(t);
      if (t < 1) {
        rafIdRef.current = requestAnimationFrame(tick);
      } else {
        setDangChay(false);
      }
    };
    rafIdRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafIdRef.current !== null) cancelAnimationFrame(rafIdRef.current);
    };
  }, [dangChay]);

  const handleBamNutBatDau = () => {
    if (dangChay) {
      // Huỷ: về đứng yên tại gốc tuyến, không phải dừng-tại-chỗ — khớp cách
      // huỷ dẫn đường bằng giọng nói cũng xoá sạch chứ không giữ vị trí dở.
      setDangChay(false);
      setTiLe(0);
    } else {
      setTiLe(0);
      setDangChay(true);
    }
  };

  const carPosition = poi ? noiSuyTrenTuyen(poi.polyline, tiLe) : null;
  const etaHienThi = poi ? Math.max(0, Math.ceil(poi.eta_min * (1 - tiLe))) : 0;

  // Ô tìm kiếm THẬT (issue #226 A6) — trước đây khung này chỉ in lại tên POI
  // đang dẫn đường, không gõ được, không tìm được gì.
  //
  // Chọn một gợi ý KHÔNG gán thẳng `destinationId` cục bộ — nó gọi `send()` với
  // đúng câu router thật khớp (`aliases[0]`, cùng cơ chế nút "Huỷ dẫn đường"
  // đã dùng), để router (`_tra_poi` trong `src/agents/router.py`) vẫn là nơi
  // DUY NHẤT quyết định POI nào được dẫn tới — tránh một đường tắt FE lệch
  // khỏi luật backend (vd. `poi_not_in_fixture`).
  const [oTimKiem, setOTimKiem] = useState("");
  const [moGoiY, setMoGoiY] = useState(false);
  const goiYPoi = timKiemPoi(oTimKiem);

  const chonGoiY = (poiChon: Poi) => {
    send(`dẫn đường đến ${poiChon.aliases[0]}`);
    setOTimKiem("");
    setMoGoiY(false);
  };

  // `isolate` (isolation: isolate) trên khung ngoài tạo một NGỮ CẢNH XẾP LỚP
  // riêng, và nó là thứ giữ cho màn này không đè lên VoiceOverlay/HitlModal/Toast.
  //
  // Lý do: IVI dùng thang z-index 30/40/50 (Toast / VoiceOverlay / HitlModal),
  // còn Leaflet gán 200..1000 cho các lớp của nó, và hai thanh phủ bên dưới cần
  // 1100 để nằm trên chúng. Không có `isolate` thì mọi con số ấy thi đấu chung
  // sân với các lớp phủ toàn cục và thắng hết — bản đồ phủ mất khung thoại, đo
  // trên trình duyệt thật 20/08.
  //
  // Có `isolate`, z-index bên trong chỉ so với nhau; cả khối MapView tham gia
  // trang ở mức `auto` nên các lớp phủ nằm sau nó trong DOM lại vẽ lên trên như
  // thiết kế. Giữ nguyên được thang 30/40/50, thay vì đẩy mọi lớp phủ vượt 1100
  // — một cuộc chạy đua không có điểm dừng.
  return (
    <div className="relative isolate h-full overflow-hidden rounded-(--r-md)">
      <LeafletMap route={poi?.polyline ?? null} carPosition={carPosition} />

      {/* `z-[1100]` là bắt buộc, không phải tinh chỉnh thẩm mỹ. Leaflet gán
          z-index cho MỌI lớp của nó — pane 200..700, control 800, khối
          `.leaflet-top/.leaflet-bottom` 1000 — còn hai thanh này mặc định là
          `z-index: auto`. Phần tử có z-index dương luôn vẽ trên phần tử auto
          bất kể thứ tự DOM, nên thiếu dòng này là mọi lớp của bản đồ phủ mất
          chúng mỗi lần vẽ lại (đo trên trình duyệt thật 20/08).

          `left-16` chừa chỗ cho nút +/- của Leaflet ở góc trái: nâng z-index
          mà vẫn để `inset-x-4` thì thanh này đè ngược lại hai nút đó. */}
      <div className="pointer-events-none absolute top-4 right-4 left-16 z-[1100] flex items-center gap-2.5 rounded-2xl border border-line bg-[rgba(15,19,26,.85)] px-4 py-3 text-sm text-ink-soft backdrop-blur-sm">
        <span>🔍</span>
        {/* Ba trạng thái vẫn giữ nguyên qua `placeholder` khi ô trống: chưa dẫn
            đường / đang dẫn tới một POI biết tên / đang dẫn tới một id KHÔNG có
            trong fixture — router có guard `poi_not_in_fixture` nên ca thứ ba
            đáng lẽ không xảy ra, nhưng gộp nó vào ca đầu là để màn hình nói dối
            rằng chẳng có gì đang chạy. */}
        <div className="pointer-events-auto relative flex-1">
          <input
            type="text"
            value={oTimKiem}
            onChange={(e) => {
              setOTimKiem(e.target.value);
              setMoGoiY(true);
            }}
            onFocus={() => setMoGoiY(true)}
            // Trễ thay vì đóng ngay: click vào một gợi ý bắn `blur` TRƯỚC
            // `click`, đóng ngay ở đây thì danh sách biến mất trước khi
            // `onClick` của gợi ý kịp chạy.
            onBlur={() => setTimeout(() => setMoGoiY(false), 150)}
            placeholder={
              !navigating
                ? 'Chưa có điểm đến — gõ hoặc nói "quán cà phê"'
                : (poi?.name ?? "Điểm đến không có trong dữ liệu demo")
            }
            className="w-full bg-transparent text-sm text-ink-soft outline-none placeholder:text-ink-soft"
          />
          {moGoiY && oTimKiem.trim() && (
            <ul className="absolute inset-x-0 top-full z-1200 mt-2 max-h-48 overflow-auto rounded-xl border border-line bg-panel-solid py-1 text-sm shadow-lg">
              {goiYPoi.length === 0 ? (
                <li className="px-3 py-2 text-ink-dim">Không tìm thấy địa điểm nào</li>
              ) : (
                goiYPoi.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => chonGoiY(item)}
                      className="w-full px-3 py-2 text-left text-ink transition-colors hover:bg-bg2"
                    >
                      {item.name}
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
        {/* Huỷ THẬT trên xe — gửi đúng câu router khớp (`_match_navigation`
            trong `src/agents/router.py`: bắt đầu bằng hủy/dừng/tắt + chứa
            "dẫn đường"), khác hoàn toàn nút "Huỷ" ở thẻ ETA bên dưới vốn chỉ
            dừng animation trình diễn cục bộ. Điều kiện là `navigating`, không
            phải `poi`, để vẫn huỷ được cả ca destination_id lạ (không có
            trong fixture) — status vẫn "active" trên xe dù FE không tra được
            tên POI để hiện. */}
        {navigating && (
          <button
            type="button"
            onClick={() => send("Hủy dẫn đường")}
            className="pointer-events-auto shrink-0 rounded-full border border-line bg-panel-solid px-3 py-1.5 text-xs font-semibold text-ink-soft transition-colors hover:text-ink"
          >
            ✕ Huỷ dẫn đường
          </button>
        )}
      </div>

      {poi && (
        <div className="pointer-events-none absolute inset-x-4 bottom-4 z-[1100] flex items-center gap-4 rounded-(--r-md) border border-line bg-[rgba(15,19,26,.9)] px-4.5 py-4 backdrop-blur-sm">
          <div>
            <p className="font-display text-2xl font-bold text-cyan">{etaHienThi} phút</p>
            <p className="mt-0.5 text-xs text-ink-soft">
              {poi.distance_km} km · {poi.name}
            </p>
          </div>
          <button
            type="button"
            onClick={handleBamNutBatDau}
            className="pointer-events-auto ml-auto rounded-xl bg-cyan px-5 py-2.5 font-display text-[13px] font-bold text-bg"
          >
            {dangChay ? "Huỷ" : "Bắt đầu"}
          </button>
        </div>
      )}
    </div>
  );
}
