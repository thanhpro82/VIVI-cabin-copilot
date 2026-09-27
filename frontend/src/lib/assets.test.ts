import { describe, expect, it } from "vitest";
import { OFFLINE_ASSETS, assetUrl } from "./assets";

describe("assetUrl", () => {
  it("mặc định trả bản web — cờ tắt phải giữ nguyên hành vi hôm nay", () => {
    // Cờ đọc lúc build nên không đổi được giữa chừng trong test; khẳng định giá
    // trị mặc định là thứ thật sự cần khoá — một bản build vô tình bật chế độ
    // demo sẽ trỏ vào file chưa tồn tại và im lặng không phát gì.
    expect(OFFLINE_ASSETS).toBe(false);
    expect(assetUrl("/media/x.mp3", "https://example.com/x.mp3")).toBe(
      "https://example.com/x.mp3",
    );
  });
});
