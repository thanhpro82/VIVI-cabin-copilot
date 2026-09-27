// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * Ba app cần mạng phải NÓI RA là chúng cần mạng ở chế độ demo, thay vì để
 * iframe trắng trơn — người xem không phân biệt được trắng-vì-đang-tải,
 * trắng-vì-hỏng và trắng-vì-chưa-làm (issue #176).
 *
 * `OFFLINE_ASSETS` là hằng số đọc lúc build nên không đổi được giữa các test;
 * thay bằng getter trên module giả để chạy được cả hai chế độ trong một file.
 */
const che_do = { offline: false };

vi.mock("@/lib/assets", () => ({
  get OFFLINE_ASSETS() {
    return che_do.offline;
  },
  assetUrl: (local: string, remote: string) => (che_do.offline ? local : remote),
}));

const { YoutubeView } = await import("./YoutubeView");
const { SpotifyView } = await import("./SpotifyView");
const { TiktokView } = await import("./TiktokView");

const MAN_HINH = [
  ["YouTube", YoutubeView],
  ["Spotify", SpotifyView],
  ["TikTok", TiktokView],
] as const;

afterEach(cleanup);

describe("chế độ demo offline", () => {
  it.each(MAN_HINH)("%s hiện nhãn cần mạng thay vì iframe", (ten, View) => {
    che_do.offline = true;

    const { container } = render(<View />);

    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByText(`${ten} cần kết nối mạng`)).toBeTruthy();
    // Điều quan trọng không phải là có chữ, mà là KHÔNG còn gọi ra mạng nữa.
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("nhãn nói rõ đây là giới hạn của bản demo, không đổ cho mạng của người dùng", () => {
    che_do.offline = true;

    render(<SpotifyView />);

    // Họ không bật được thứ gì để sửa — bảo "kiểm tra kết nối" là gửi người
    // dùng đi làm một việc vô ích.
    expect(screen.getByText(/chế độ offline/)).toBeTruthy();
  });
});

describe("chế độ thường (mặc định)", () => {
  it.each(MAN_HINH)("%s vẫn dựng nội dung như cũ", (_ten, View) => {
    che_do.offline = false;

    const { container } = render(<View />);

    expect(screen.queryByRole("status")).toBeNull();
    expect(container.querySelector("iframe") ?? container.querySelector("img")).toBeTruthy();
  });
});
