import { describe, expect, it } from "vitest";
import { shouldStartCloseTimerImmediately } from "./voiceOverlayClose";

describe("shouldStartCloseTimerImmediately", () => {
  it("không có audio nào (turn không có assistant.speech, TTS thất bại phía BE) → đóng ngay", () => {
    expect(shouldStartCloseTimerImmediately(null)).toBe(true);
  });

  it("audio đã phát xong (ended=true) → đóng ngay, không đợi thêm", () => {
    expect(shouldStartCloseTimerImmediately({ ended: true, error: null })).toBe(true);
  });

  it("audio lỗi (bị chặn autoplay/decode lỗi) → fail-open, đóng ngay thay vì treo vô thời hạn", () => {
    const fakeError = {} as MediaError;
    expect(shouldStartCloseTimerImmediately({ ended: false, error: fakeError })).toBe(true);
  });

  it("audio còn đang phát dở (chưa ended, chưa lỗi) → PHẢI đợi, không đóng ngay", () => {
    expect(shouldStartCloseTimerImmediately({ ended: false, error: null })).toBe(false);
  });
});
