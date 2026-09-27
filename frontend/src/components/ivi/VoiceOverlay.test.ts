import { describe, expect, it } from "vitest";
import { micStateColor } from "./VoiceOverlay";

/**
 * Test cho màu nút mic/label theo `AssistantState` (PR2) — viết trước khi
 * implement UI, theo đúng quy trình test-first. `recording` luôn thắng mọi
 * trạng thái khác (giữ nguyên quy ước cũ: đang ghi = xanh lá thật, không đổi
 * theo assistantState vì lúc ghi chưa có assistantState nào từ backend cả).
 */
describe("micStateColor", () => {
  it("đang ghi (recording=true) → luôn xanh lá, bất kể assistantState", () => {
    expect(micStateColor(true, null)).toBe("green");
    expect(micStateColor(true, "executing")).toBe("green");
  });

  it("chưa có assistantState (vừa mở overlay, chưa nhận status nào) → cyan mặc định", () => {
    expect(micStateColor(false, null)).toBe("cyan");
  });

  it("map đúng từng AssistantState", () => {
    expect(micStateColor(false, "transcribing")).toBe("cyan");
    expect(micStateColor(false, "routing")).toBe("violet");
    expect(micStateColor(false, "planning")).toBe("violet");
    expect(micStateColor(false, "retrieving")).toBe("violet");
    expect(micStateColor(false, "waiting_approval")).toBe("amber");
    expect(micStateColor(false, "executing")).toBe("green");
    expect(micStateColor(false, "composing")).toBe("cyan");
  });
});
