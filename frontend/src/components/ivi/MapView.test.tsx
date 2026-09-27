// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POI_ITEMS, findPoi } from "@/lib/fixtures/poi";
import { MapView } from "./MapView";

const shell = { status: "idle", destinationId: null as string | null };
const leafletProps: { route: unknown }[] = [];
const sendMock = vi.fn();

vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => ({
    vehicleState: {
      navigation: { status: shell.status, destinationId: shell.destinationId },
    },
    send: sendMock,
  }),
}));

// `next/dynamic` với ssr:false không render đoán được trong jsdom, và test này
// quan tâm **MapView truyền lộ trình nào xuống**, không quan tâm Leaflet vẽ ra
// sao. Ghi lại props là đúng ranh giới cần khoá.
vi.mock("next/dynamic", () => ({
  default: () =>
    function LeafletMapStub(props: { route: unknown }) {
      leafletProps.push(props);
      return <div data-testid="map" />;
    },
}));

describe("MapView đọc lộ trình và ETA từ POI fixture", () => {
  beforeEach(() => {
    shell.status = "idle";
    shell.destinationId = null;
    leafletProps.length = 0;
    sendMock.mockClear();
  });

  // vitest.config.mts không bật `globals` nên @testing-library/react không tự
  // đăng ký cleanup — thiếu dòng này thì DOM lượt trước còn nguyên.
  afterEach(cleanup);

  it("chưa dẫn đường thì không có lộ trình và hiện lời mời nói", () => {
    render(<MapView />);
    expect(leafletProps.at(-1)?.route).toBeNull();
    expect(screen.getByPlaceholderText(/Chưa có điểm đến/)).toBeTruthy();
  });

  it.each(POI_ITEMS.map((poi) => [poi.id]))(
    "%s hiện đúng tên, ETA và quãng đường của chính nó",
    (id) => {
      const poi = findPoi(id)!;
      shell.status = "active";
      shell.destinationId = id;

      render(<MapView />);

      expect(leafletProps.at(-1)?.route).toEqual(poi.polyline);
      expect(screen.getByText(`${poi.eta_min} phút`)).toBeTruthy();
      // Khớp cả dòng, không khớp con số rời: `distance_km: 4.0` đọc ra `"4"`,
      // và `"4"` còn nằm trong `"14 phút"` của một POI khác — regex lỏng sẽ
      // trúng nhiều phần tử rồi đỏ vì lý do chẳng liên quan gì tới quãng đường.
      expect(
        screen.getByText(
          (_, el) => el?.textContent === `${poi.distance_km} km · ${poi.name}`,
        ),
      ).toBeTruthy();
    },
  );

  it("sáu POI cho nhiều ETA khác nhau — hồi quy cho chuỗi cứng '12 phút'", () => {
    // Trước issue #175, MapView cứng `"12 phút"` và `"3.4 km · Nguyễn Trãi →
    // Cầu Giấy"`, nên tập này chỉ có đúng 1 phần tử bất kể dẫn đường tới đâu.
    const etas = new Set(POI_ITEMS.map((poi) => poi.eta_min));
    const routes = new Set<string>();
    for (const poi of POI_ITEMS) {
      shell.status = "active";
      shell.destinationId = poi.id;
      render(<MapView />);
      routes.add(JSON.stringify(leafletProps.at(-1)?.route));
      cleanup();
    }
    expect(etas.size).toBeGreaterThan(1);
    expect(routes.size).toBe(POI_ITEMS.length);
  });

  it("destination_id lạ thì không crash, không vẽ tuyến, và NÓI RA là không biết", () => {
    // Gộp ca này vào ca "chưa dẫn đường" là để màn hình nói dối rằng chẳng có gì
    // đang chạy, trong khi xe vẫn đang được dẫn đi đâu đó. Router có guard
    // `poi_not_in_fixture` nên ca này đáng lẽ không tới được đây — nhưng "đáng
    // lẽ" không phải lý do để bỏ nhánh hiển thị.
    shell.status = "active";
    shell.destinationId = "poi-khong-ton-tai";

    render(<MapView />);

    expect(leafletProps.at(-1)?.route).toBeNull();
    expect(screen.getByPlaceholderText(/không có trong dữ liệu demo/)).toBeTruthy();
    expect(screen.queryByText(/phút/)).toBeNull();
  });

  it("status idle thì không vẽ, kể cả khi snapshot còn destinationId", () => {
    // Ca này SIMULATOR HIỆN KHÔNG SINH RA: `_apply_navigation` xoá `status` và
    // `destination_id` trong cùng một lần huỷ (`src/vehicle_sim/state.py:345-347`),
    // nên hai trường luôn đi cùng nhau. Test giữ lại để khoá việc MapView đọc
    // `status` — cờ canonical — thay vì suy từ `destinationId != null`.
    shell.status = "idle";
    shell.destinationId = POI_ITEMS[0].id;

    render(<MapView />);

    expect(leafletProps.at(-1)?.route).toBeNull();
  });

  it("bấm 'Bắt đầu' đổi nút thành 'Huỷ', bấm lại thì về 'Bắt đầu' — animation trình diễn thuần FE", () => {
    shell.status = "active";
    shell.destinationId = POI_ITEMS[0].id;

    render(<MapView />);

    const nut = screen.getByRole("button", { name: "Bắt đầu" });
    fireEvent.click(nut);
    expect(screen.getByRole("button", { name: "Huỷ" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Huỷ" }));
    expect(screen.getByRole("button", { name: "Bắt đầu" })).toBeTruthy();
    // Huỷ phải về đúng ETA gốc — không phải kẹt lại ở số đã đếm ngược dở.
    expect(
      screen.getByText(`${POI_ITEMS[0].eta_min} phút`),
    ).toBeTruthy();
  });

  it("đổi điểm đến giữa lúc animation đang chạy thì tự reset về 'Bắt đầu'", () => {
    shell.status = "active";
    shell.destinationId = POI_ITEMS[0].id;

    const { rerender } = render(<MapView />);
    fireEvent.click(screen.getByRole("button", { name: "Bắt đầu" }));
    expect(screen.getByRole("button", { name: "Huỷ" })).toBeTruthy();

    shell.destinationId = POI_ITEMS[1].id;
    rerender(<MapView />);

    expect(screen.getByRole("button", { name: "Bắt đầu" })).toBeTruthy();
  });

  it("chưa dẫn đường thì không có nút huỷ dẫn đường thật", () => {
    render(<MapView />);
    expect(screen.queryByRole("button", { name: /Huỷ dẫn đường/ })).toBeNull();
  });

  it("bấm 'Huỷ dẫn đường' gửi đúng câu router khớp (set_navigation cancel) — KHÁC nút Huỷ animation", () => {
    shell.status = "active";
    shell.destinationId = POI_ITEMS[0].id;

    render(<MapView />);

    fireEvent.click(screen.getByRole("button", { name: /Huỷ dẫn đường/ }));

    expect(sendMock).toHaveBeenCalledWith("Hủy dẫn đường");
    expect(sendMock).toHaveBeenCalledTimes(1);
    // Nút này không đụng animation cục bộ — thẻ ETA vẫn đứng yên, không đổi
    // thành "Bắt đầu"/"Huỷ" nào cả trong lúc này (chỉ đổi khi vehicleState
    // thật đổi, mà mock ở đây chưa đổi `shell.status`).
    expect(screen.getByRole("button", { name: "Bắt đầu" })).toBeTruthy();
  });

  it("destination_id lạ (không có trong fixture) vẫn huỷ được — status xe vẫn 'active'", () => {
    shell.status = "active";
    shell.destinationId = "poi-khong-ton-tai";

    render(<MapView />);

    const nutHuy = screen.getByRole("button", { name: /Huỷ dẫn đường/ });
    fireEvent.click(nutHuy);

    expect(sendMock).toHaveBeenCalledWith("Hủy dẫn đường");
  });

  describe("ô tìm kiếm POI thật (issue #226 A6)", () => {
    it("gõ chưa ra gì thì không hiện danh sách gợi ý", () => {
      render(<MapView />);
      const o = screen.getByPlaceholderText(/Chưa có điểm đến/);
      expect(screen.queryByRole("list")).toBeNull();

      fireEvent.change(o, { target: { value: "" } });
      expect(screen.queryByRole("list")).toBeNull();
    });

    it("gõ khớp alias (không khớp tên) vẫn ra đúng POI — 'cà phê' không nằm trong tên Highlands", () => {
      render(<MapView />);
      const o = screen.getByPlaceholderText(/Chưa có điểm đến/);

      fireEvent.change(o, { target: { value: "cà phê" } });

      expect(
        screen.getByRole("button", { name: "Highlands Coffee Nguyễn Trãi" }),
      ).toBeTruthy();
    });

    it("gõ không khớp POI nào thì báo rõ, không im lặng", () => {
      render(<MapView />);
      const o = screen.getByPlaceholderText(/Chưa có điểm đến/);

      fireEvent.change(o, { target: { value: "phi thuyền vũ trụ" } });

      expect(screen.getByText("Không tìm thấy địa điểm nào")).toBeTruthy();
    });

    it("chọn một gợi ý gửi ĐÚNG câu router khớp (alias đầu tiên), không tự gán destination_id", () => {
      render(<MapView />);
      const o = screen.getByPlaceholderText(/Chưa có điểm đến/);

      fireEvent.change(o, { target: { value: "bình minh" } });
      fireEvent.click(screen.getByRole("button", { name: "Cà phê Bình Minh" }));

      expect(sendMock).toHaveBeenCalledWith("dẫn đường đến bình minh");
      // Ô tìm kiếm và danh sách gợi ý phải đóng lại sau khi chọn — không thì
      // gợi ý cũ còn treo trong lúc chờ vehicleState thật cập nhật.
      expect((o as HTMLInputElement).value).toBe("");
      expect(screen.queryByRole("list")).toBeNull();
    });
  });
});
