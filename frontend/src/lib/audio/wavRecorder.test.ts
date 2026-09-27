import { describe, expect, it, vi } from "vitest";
import { createSpeechEnergyTracker } from "./wavRecorder";

/**
 * Test cho VAD (PM/PO review PR0, điểm 1) — chỉ test phần logic năng lượng
 * thuần (`createSpeechEnergyTracker`), không giả lập AudioContext/
 * AudioWorkletNode thật (jsdom không có Web Audio API, và việc đó thuộc về
 * `startWavRecording()` — lớp tích hợp trình duyệt, không phải logic cần
 * test ở đây).
 */

const LOUD = new Float32Array(128).fill(0.5); // RMS 0.5, vượt xa ngưỡng 0.02
const SILENT = new Float32Array(128).fill(0); // RMS 0

describe("createSpeechEnergyTracker", () => {
  it("có giọng nói rồi im lặng đủ 900ms → gọi onSilenceDetected đúng 1 lần", () => {
    const onSilenceDetected = vi.fn();
    const tracker = createSpeechEnergyTracker(onSilenceDetected);

    tracker.feed(LOUD, 100); // có giọng nói
    expect(onSilenceDetected).not.toHaveBeenCalled();
    expect(tracker.hadSpeech()).toBe(true);

    // Im lặng dồn dần — chưa đủ 900ms thì chưa gọi.
    tracker.feed(SILENT, 500);
    expect(onSilenceDetected).not.toHaveBeenCalled();
    tracker.feed(SILENT, 300);
    expect(onSilenceDetected).not.toHaveBeenCalled();

    // Đủ 900ms (500+300+200=1000 ≥ 900) — gọi đúng 1 lần.
    tracker.feed(SILENT, 200);
    expect(onSilenceDetected).toHaveBeenCalledTimes(1);

    // Im lặng thêm nữa — không gọi lại lần 2 (silenceFired chặn).
    tracker.feed(SILENT, 1000);
    expect(onSilenceDetected).toHaveBeenCalledTimes(1);
  });

  it("chỉ toàn im lặng/ồn nền (không vượt ngưỡng) → không bao giờ gọi onSilenceDetected, hadSpeech() false", () => {
    const onSilenceDetected = vi.fn();
    const tracker = createSpeechEnergyTracker(onSilenceDetected);

    for (let i = 0; i < 20; i++) {
      tracker.feed(SILENT, 100); // tổng 2000ms im lặng, nhưng chưa từng có giọng nói
    }

    expect(onSilenceDetected).not.toHaveBeenCalled();
    expect(tracker.hadSpeech()).toBe(false);
  });

  it("im lặng ngắn xen giữa lúc đang nói không tính dồn — chỉ đếm lại từ khối im lặng liên tục cuối cùng", () => {
    const onSilenceDetected = vi.fn();
    const tracker = createSpeechEnergyTracker(onSilenceDetected);

    tracker.feed(LOUD, 100);
    tracker.feed(SILENT, 600); // im lặng 600ms, chưa đủ 900ms
    tracker.feed(LOUD, 100); // lại nói — reset đồng hồ im lặng về 0
    tracker.feed(SILENT, 800); // mới 800ms kể từ lần nói cuối, chưa đủ 900ms
    expect(onSilenceDetected).not.toHaveBeenCalled();

    tracker.feed(SILENT, 200); // 800+200=1000 ≥ 900 — giờ mới gọi
    expect(onSilenceDetected).toHaveBeenCalledTimes(1);
  });

  it("hadSpeech() vẫn đúng khi KHÔNG truyền onSilenceDetected (VAD tắt) — không phải luôn false", () => {
    // Bug tiềm ẩn đã sửa: bản trước gộp chung điều kiện `!onSilenceDetected`
    // khiến hasSpeech không bao giờ được set nếu không truyền callback, dù
    // đã nói rõ ràng — DriverShellProvider hiện luôn truyền callback nên
    // chưa từng lộ ra, nhưng interface public vẫn cho phép bỏ trống.
    const tracker = createSpeechEnergyTracker();

    expect(tracker.hadSpeech()).toBe(false);
    tracker.feed(LOUD, 100);
    expect(tracker.hadSpeech()).toBe(true);

    // Im lặng bao lâu cũng không throw/không gọi gì (không có callback) —
    // hadSpeech() vẫn giữ nguyên true.
    tracker.feed(SILENT, 5000);
    expect(tracker.hadSpeech()).toBe(true);
  });

  // Issue #342: vạch sóng ở đường thu tay cũng phải đọc RMS thật.
  describe("onLevel — mức 0..1 cho vạch sóng, chuẩn hoá theo đỉnh của chính lượt ghi", () => {
    const MEDIUM = new Float32Array(128).fill(0.25); // RMS 0.25 — nửa của LOUD

    it("khối to nhất từ đầu tới giờ ⇒ level = 1; khối nhỏ hơn ⇒ so với đỉnh đó, không phải ngưỡng tuyệt đối", () => {
      const onLevel = vi.fn();
      const tracker = createSpeechEnergyTracker(undefined, onLevel);

      tracker.feed(LOUD, 100);
      expect(onLevel).toHaveBeenLastCalledWith(1);

      tracker.feed(MEDIUM, 100);
      expect(onLevel).toHaveBeenLastCalledWith(0.5);
    });

    it("chỉ im lặng ⇒ chưa từng có đỉnh ⇒ level luôn 0", () => {
      const onLevel = vi.fn();
      const tracker = createSpeechEnergyTracker(undefined, onLevel);

      tracker.feed(SILENT, 100);
      tracker.feed(SILENT, 100);

      expect(onLevel).toHaveBeenCalledTimes(2);
      for (const call of onLevel.mock.calls) expect(call[0]).toBe(0);
    });
  });
});
