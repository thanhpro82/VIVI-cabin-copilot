// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MEDIA_TRACKS, TRACK_NAMES, findTrack } from "@/lib/fixtures/media";
import { MediaPlayer } from "./MediaPlayer";

const shell = { track: null as string | null, status: "playing", volume: 40 };

vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => ({
    vehicleState: { media: { status: shell.status, volume: shell.volume, track: shell.track } },
  }),
}));

function audio(container: HTMLElement): HTMLAudioElement | null {
  return container.querySelector("audio");
}

describe("MediaPlayer chọn nguồn theo tên bài backend trả về", () => {
  beforeEach(() => {
    shell.track = null;
    shell.status = "playing";
    shell.volume = 40;
    // jsdom không cài đặt HTMLMediaElement.play/pause — gọi thẳng sẽ ném
    // "Not implemented" trong effect.
    HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
    HTMLMediaElement.prototype.pause = vi.fn();
  });

  afterEach(cleanup);

  it.each(MEDIA_TRACKS.map((t) => [t.name, t.file]))("bài %s phát đúng file của nó", (name, file) => {
    shell.track = name;
    const { container } = render(<MediaPlayer />);
    expect(audio(container)?.getAttribute("src")).toBe(file);
  });

  it("mỗi bài một file riêng — hồi quy cho bug luôn phát một file", () => {
    // Trước issue #173, MỌI tên bài backend trả về đều trượt bảng tra của FE và
    // rơi về cùng một `DEFAULT_TRACK_SRC`, nên tập này chỉ có đúng 1 phần tử.
    const files = new Set<string | null | undefined>();
    for (const name of TRACK_NAMES) {
      shell.track = name;
      files.add(audio(render(<MediaPlayer />).container)?.getAttribute("src"));
      cleanup();
    }
    expect(files.size).toBe(TRACK_NAMES.length);
  });

  it("đổi bài KHÔNG tạo phần tử <audio> mới", () => {
    // Lỗi đo trên trình duyệt thật 19/08: thẻ có `key` nên mỗi lần chuyển bài
    // React tháo phần tử cũ và tạo phần tử mới. Phần tử bị gỡ khỏi DOM vẫn phát
    // tiếp, còn ref chỉ trỏ tới cái mới nhất — sáu lần next ra sáu tiếng chồng
    // lên nhau và nút dừng không tắt nổi. jsdom không phát tiếng nên thứ kiểm
    // được, và cũng là nguyên nhân gốc, là phần tử có bị thay hay không.
    shell.track = TRACK_NAMES[0];
    const { container, rerender } = render(<MediaPlayer />);
    const truoc = audio(container);

    shell.track = TRACK_NAMES[1];
    rerender(<MediaPlayer />);

    expect(audio(container)).toBe(truoc);
    expect(container.querySelectorAll("audio")).toHaveLength(1);
    expect(audio(container)?.getAttribute("src")).toBe(findTrack(TRACK_NAMES[1])?.file);
  });

  it("tên không có trong fixture thì KHÔNG phát bừa bài khác", () => {
    // Rơi về bài đầu tiên là đúng cách bug cũ ẩn mình: người xem nghe thấy
    // tiếng nên tưởng mọi thứ ổn.
    shell.track = "Bolero chọn lọc";
    const { container } = render(<MediaPlayer />);
    expect(audio(container)?.getAttribute("src")).toBeNull();
  });

  it("chưa phát bài nào thì không có nguồn audio", () => {
    const { container } = render(<MediaPlayer />);
    expect(audio(container)?.getAttribute("src")).toBeNull();
  });

  it("trạng thái paused thì gọi pause, playing thì gọi play", () => {
    shell.track = TRACK_NAMES[0];
    shell.status = "paused";
    render(<MediaPlayer />);
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();

    cleanup();
    shell.status = "playing";
    render(<MediaPlayer />);
    expect(HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });

  it("âm lượng 0..100 của xe ánh xạ xuống 0..1 của phần tử audio", () => {
    shell.track = TRACK_NAMES[0];
    shell.volume = 35;
    const { container } = render(<MediaPlayer />);
    expect(audio(container)?.volume).toBeCloseTo(0.35);
  });
});
