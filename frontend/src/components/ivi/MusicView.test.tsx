// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MEDIA_TRACKS, TRACK_NAMES } from "@/lib/fixtures/media";
import { trackCoverGradient } from "@/lib/ivi/trackCover";
import { MusicView } from "./MusicView";

/**
 * `MusicView` chỉ còn phần HIỂN THỊ — thẻ `<audio>` đã chuyển lên `DriverShell`
 * để nhạc phát xuyên qua các lần đổi màn (`MediaPlayer.test.tsx` giữ nửa kia).
 * Nên ở đây không kiểm gì về phát nhạc, chỉ kiểm những gì tài xế nhìn thấy.
 */
const shell = { track: null as string | null, status: "playing" as string, volume: 40 };

/** Nền gradient của lớp bìa mờ phía sau, hoặc undefined khi không vẽ bìa nào. */
function nenBia(container: HTMLElement): string | undefined {
  const el = container.querySelector<HTMLElement>("div[aria-hidden].blur-2xl");
  return el?.style.background || undefined;
}

vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => ({
    vehicleState: { media: { status: shell.status, volume: shell.volume, track: shell.track } },
    send: vi.fn(),
  }),
}));

describe("MusicView hiển thị theo tên bài backend trả về", () => {
  beforeEach(() => {
    shell.track = null;
    shell.status = "playing";
    shell.volume = 40;
  });

  // vitest.config.mts không bật `globals` nên @testing-library/react không tự
  // đăng ký cleanup — thiếu dòng này thì DOM lượt trước còn nguyên.
  afterEach(cleanup);

  it("không còn giữ thẻ audio nào — trình phát đã lên tầng shell", () => {
    // Hồi quy cho lỗi "đổi tab thì nhạc tự tắt": thẻ audio nằm trong view bị
    // React tháo mỗi lần đổi màn, và trình duyệt tạm dừng media element bị gỡ
    // khỏi document (đúng spec HTML). Thẻ quay lại đây là lỗi quay lại.
    shell.track = TRACK_NAMES[0];
    const { container } = render(<MusicView />);
    expect(container.querySelector("audio")).toBeNull();
  });

  it.each(MEDIA_TRACKS.map((t) => [t.name, t.id, t.attribution]))(
    "bài %s hiện đúng tên, bìa riêng và dòng ghi công",
    (name, id, attribution) => {
      shell.track = name;
      const { container } = render(<MusicView />);

      expect(screen.getByText(name)).toBeTruthy();
      // Ghi công là ĐIỀU KIỆN của CC BY 4.0, không phải chi tiết trình bày.
      expect(screen.getByText(attribution)).toBeTruthy();
      expect(nenBia(container)).toBe(trackCoverGradient(id));
    },
  );

  it("bìa sinh bằng code, KHÔNG tải ảnh từ đâu cả", () => {
    // @thanhpro82 chốt ở #188: sinh bằng code thay vì đi tìm ảnh CC0. Một thẻ
    // <img> quay lại đây nghĩa là có file phải commit và license phải khai.
    shell.track = TRACK_NAMES[0];
    const { container } = render(<MusicView />);
    expect(container.querySelector("img")).toBeNull();
  });

  it("mỗi bài một bìa riêng, và ổn định qua các lần render", () => {
    const nen = new Set<string | undefined>();
    for (const name of TRACK_NAMES) {
      shell.track = name;
      nen.add(nenBia(render(<MusicView />).container));
      cleanup();
    }
    expect(nen.size).toBeGreaterThan(1);

    // Ổn định: cùng một bài phải ra cùng một bìa ở lần render sau. Bìa đổi màu
    // giữa hai lần mở app trông như lỗi, nên hàm sinh phải thuần và không dùng
    // Math.random/Date.
    shell.track = TRACK_NAMES[0];
    const lan1 = nenBia(render(<MusicView />).container);
    cleanup();
    const lan2 = nenBia(render(<MusicView />).container);
    expect(lan2).toBe(lan1);
  });

  it("tên không có trong fixture thì không vẽ bìa của bài khác", () => {
    shell.track = "Bolero chọn lọc";
    const { container } = render(<MusicView />);
    expect(nenBia(container)).toBeUndefined();
  });

  describe("nhãn trạng thái không còn tự mâu thuẫn (issue #226 B1)", () => {
    // Trước bản sửa: nhãn trên luôn cứng "Đang phát" bất kể `playing`, và dòng
    // tiêu đề lật thành "Tắt" khi dừng — trong khi dòng ghi công phía dưới vẫn
    // in tên bài và nút play hiện ▶. Ba tín hiệu, ba câu chuyện khác nhau.

    it("đang phát: nhãn 'Đang phát', tiêu đề là tên bài", () => {
      shell.status = "playing";
      shell.track = TRACK_NAMES[0];
      render(<MusicView />);

      expect(screen.getByText("Đang phát")).toBeTruthy();
      expect(screen.getByText(TRACK_NAMES[0])).toBeTruthy();
      expect(screen.queryByText("Tắt")).toBeNull();
    });

    it("tạm dừng nhưng còn bài: nhãn 'Đã dừng', tiêu đề VẪN là tên bài — không biến mất", () => {
      shell.status = "paused";
      shell.track = TRACK_NAMES[0];
      render(<MusicView />);

      expect(screen.getByText("Đã dừng")).toBeTruthy();
      // Đây là điểm chính của bug cũ: tên bài không được phép đổi thành "Tắt"
      // chỉ vì tạm dừng — bài hát không biến mất, chỉ đang không phát.
      expect(screen.getByText(TRACK_NAMES[0])).toBeTruthy();
      expect(screen.queryByText("Tắt")).toBeNull();
    });

    it("tắt tiếng: nhãn phải NÓI RA, vì status vẫn là playing", () => {
      // `set_volume: 0` không đụng tới `status` (`vehicle_sim.state._apply_media`),
      // nên đây là ca duy nhất mà "Đang phát" một mình là câu nói dối: loa im mà
      // màn hình bảo đang phát. Cùng lớp lỗi với #226 B1, chỉ khác nguồn.
      shell.status = "playing";
      shell.volume = 0;
      shell.track = TRACK_NAMES[0];
      render(<MusicView />);

      expect(screen.getByText("Đang phát · đã tắt tiếng")).toBeTruthy();
      // Tắt tiếng KHÔNG phải tạm dừng — nhãn không được đổi thành "Đã dừng".
      expect(screen.queryByText("Đã dừng")).toBeNull();
      expect(screen.getByText(TRACK_NAMES[0])).toBeTruthy();
    });

    it("tắt tiếng lúc đang dừng thì nhãn vẫn là 'Đã dừng'", () => {
      // Hai trạng thái độc lập; dừng là chuyện lớn hơn, nói trước.
      shell.status = "paused";
      shell.volume = 0;
      shell.track = TRACK_NAMES[0];
      render(<MusicView />);

      expect(screen.getByText("Đã dừng")).toBeTruthy();
    });

    it("chưa có bài nào: cả nhãn lẫn tiêu đề đều nói đúng một chuyện", () => {
      shell.status = "idle";
      shell.track = null;
      render(<MusicView />);

      expect(screen.getAllByText("Chưa có bài nào")).toHaveLength(2);
      expect(screen.queryByText("Tắt")).toBeNull();
    });
  });
});
