import { describe, expect, it } from "vitest";
import { MEDIA_TRACKS } from "@/lib/fixtures/media";
import { trackCoverGradient } from "./trackCover";

describe("trackCoverGradient", () => {
  it("thuần và ổn định — cùng id luôn ra cùng bìa", () => {
    // Bìa đổi màu giữa hai lần mở app trông như lỗi, nên hàm sinh không được
    // đụng tới Math.random hay Date.
    for (const track of MEDIA_TRACKS) {
      expect(trackCoverGradient(track.id)).toBe(trackCoverGradient(track.id));
    }
  });

  it("sáu bài cho nhiều bìa khác nhau", () => {
    const nen = new Set(MEDIA_TRACKS.map((t) => trackCoverGradient(t.id)));
    expect(nen.size).toBeGreaterThan(1);
  });

  it("CHỈ dùng token màu có sẵn, không đẻ hex mới", () => {
    // `frontend/CLAUDE.md` cấm thêm hex ngoài DESIGN_TOKENS.md. Test này là chỗ
    // duy nhất bắt được việc ai đó "cho đẹp hơn" bằng một mã màu viết thẳng.
    for (const track of MEDIA_TRACKS) {
      expect(trackCoverGradient(track.id)).not.toMatch(/#[0-9a-f]{3,8}\b/i);
      expect(trackCoverGradient(track.id)).not.toMatch(/\b(rgb|hsl)a?\(/i);
    }
  });

  it("chỉ ở trong họ màu nhạc — không mượn token của miền khác", () => {
    // `--accent` là cảnh báo/điều khiển nguy hiểm, `--pink` là TikTok, `--green`
    // là Spotify. Một bìa đỏ đọc thành "nguy hiểm"; đó là lý do bảng token gán
    // ý nghĩa cho màu chứ không chỉ gán sắc độ.
    const CAM = ["--accent", "--pink", "--green", "--amber"];
    for (const track of MEDIA_TRACKS) {
      const nen = trackCoverGradient(track.id);
      expect(nen).toContain("--violet");
      for (const token of CAM) expect(nen).not.toContain(token);
    }
  });

  it("không có id thì vẫn trả một chuỗi hợp lệ, không ném", () => {
    expect(trackCoverGradient(null)).toContain("linear-gradient");
    expect(trackCoverGradient(undefined)).toContain("linear-gradient");
  });
});
