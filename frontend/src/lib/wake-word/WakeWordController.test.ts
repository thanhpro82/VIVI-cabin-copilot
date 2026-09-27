import { describe, expect, it, vi, afterEach } from "vitest";
import { MicrophonePipeline } from "@/lib/audio/microphonePipeline";
import type { WakeDetection, WakeWordDetector, WakeWordManifest } from "./types";
import { FOLLOW_UP_SESSION_MAX_MS, FOLLOW_UP_WINDOW_MS, MAX_CHAINED_FOLLOW_UPS, WakeWordController } from "./WakeWordController";

const manifest: WakeWordManifest = {
  schemaVersion: "1.0", modelVersion: "test", modelPath: "/model.onnx", sha256: "a",
  melspectrogramPath: "/melspectrogram.onnx", melspectrogramSha256: "b",
  embeddingPath: "/embedding_model.onnx", embeddingSha256: "c",
  license: "LicenseRef-VIVI-Academic-Only",
  trainingRunId: "test", evaluationReportPath: "/report", sampleRate: 16000, windowSamples: 32000, hopSamples: 1600,
  labels: ["wake", "non_wake"], threshold: 0.8, refractoryMs: 1000,
};

function fakePipeline() {
  let emit: ((samples: Float32Array) => void) | undefined;
  const stop = vi.fn(async () => undefined);
  const source = vi.fn(async (onSamples: (samples: Float32Array) => void) => { emit = onSamples; return { stop }; });
  return { pipeline: new MicrophonePipeline(source), source, stop, emit: (...values: number[]) => emit?.(Float32Array.from(values)) };
}

function fakeDetector() {
  let detected: ((detection: WakeDetection) => void) | undefined;
  let failed: ((message: string) => void) | undefined;
  const detector: WakeWordDetector = {
    load: vi.fn(async () => manifest),
    resume: vi.fn((_generation, onDetection, onError) => { detected = onDetection; failed = onError; }),
    accept: vi.fn(), pause: vi.fn(), dispose: vi.fn(),
  };
  return { detector, detect: (throughSequence = 1) => detected?.({ label: "wake", score: 1, modelVersion: "test", throughSequence, generation: 1 }), fail: (message: string) => failed?.(message) };
}

function setup(armLatencyMs?: number) {
  const audio = fakePipeline();
  const wake = fakeDetector();
  const callbacks = {
    onStateChange: vi.fn(),
    onArming: vi.fn(),
    onCaptureStarted: vi.fn(),
    onCommandReady: vi.fn(),
    onSilentClose: vi.fn(),
    onWakeUnavailable: vi.fn(),
    onFollowUpWindowStarted: vi.fn(),
    onFollowUpWindowExpired: vi.fn(),
    onLevel: vi.fn(),
  };
  const controller = new WakeWordController({ pipeline: audio.pipeline, detector: wake.detector, callbacks, setTimer: setTimeout, clearTimer: clearTimeout, armLatencyMs });
  return { ...audio, ...wake, callbacks, controller };
}

afterEach(() => vi.useRealTimers());

describe("WakeWordController", () => {
  it("loads the detector before requesting the microphone", async () => {
    const ctx = setup();
    await ctx.controller.enable();
    expect(ctx.detector.load).toHaveBeenCalledBefore(ctx.source);
  });

  it("arms before capturing: detection fires onArming, pauses the detector, then fires onCaptureStarted only after the arm-latency timer", async () => {
    vi.useFakeTimers();
    const ctx = setup(80);
    await ctx.controller.enable();
    ctx.emit(0.2, 0.2);
    ctx.detect(1);

    expect(ctx.callbacks.onArming).toHaveBeenCalledTimes(1);
    expect(ctx.detector.pause).toHaveBeenCalledTimes(1);
    expect(ctx.controller.state).toBe("ARMING");
    expect(ctx.callbacks.onCaptureStarted).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(80);
    expect(ctx.controller.state).toBe("CAPTURING_COMMAND");
    expect(ctx.callbacks.onCaptureStarted).toHaveBeenCalledWith("wake_word");
  });

  it("ignores a second detection while arming or already capturing", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable();
    ctx.detect(1); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);
    ctx.emit(...Array(1600).fill(0.2)); await ctx.controller.stopCapture(); ctx.detect(1);
    expect(ctx.controller.state).toBe("PROCESSING");
    expect(ctx.callbacks.onCaptureStarted).toHaveBeenCalledTimes(1);
  });

  it.each([0, 50, 80, 150, 400, 1000])(
    "submitted command audio never contains the wake-phrase samples, under a %ims arm-latency",
    async (latencyMs) => {
      vi.useFakeTimers();
      const ctx = setup(latencyMs);
      await ctx.controller.enable();
      // Wake-phrase audio: distinct, easily-identified sample values pushed to the
      // pipeline BEFORE the trigger. These must never appear in the submitted WAV.
      const wakePhraseSample = 0.77;
      ctx.emit(...Array(4).fill(wakePhraseSample));
      ctx.detect(1);
      // Frames arriving during ARMING (the gap the guard buffer exists to cover) —
      // the first of these represents the earliest a driver could plausibly start
      // speaking the command, right as the beep begins.
      const firstCommandPhoneme = 0.55;
      ctx.emit(firstCommandPhoneme);
      await vi.advanceTimersByTimeAsync(latencyMs);
      expect(ctx.controller.state).toBe("CAPTURING_COMMAND");

      // Enough post-beep speech, then silence, to trigger submission.
      ctx.emit(...Array(1600).fill(0.3));
      ctx.emit(...Array(14400).fill(0));
      await Promise.resolve();

      expect(ctx.callbacks.onCommandReady).toHaveBeenCalledTimes(1);
      const submitted = ctx.callbacks.onCommandReady.mock.calls[0][0] as Blob;
      const bytes = new Uint8Array(await submitted.arrayBuffer());
      const view = new DataView(bytes.buffer);
      const sampleCount = (bytes.length - 44) / 2;
      const samples: number[] = [];
      for (let i = 0; i < sampleCount; i++) samples.push(view.getInt16(44 + i * 2, true) / 0x7fff);

      // The wake-phrase value must be absent everywhere in the submitted audio.
      expect(samples.some((value) => Math.abs(value - wakePhraseSample) < 0.001)).toBe(false);
      // The first command phoneme, spoken right as the beep started, must survive
      // via the guard-buffer snapshot rather than being clipped.
      expect(samples.some((value) => Math.abs(value - firstCommandPhoneme) < 0.001)).toBe(true);
    },
  );

  it.each([400, 1000])(
    "guard buffer evicts stale arming-phase audio beyond its 300ms capacity, under a %ims arm-latency",
    async (latencyMs) => {
      vi.useFakeTimers();
      const ctx = setup(latencyMs);
      await ctx.controller.enable();
      ctx.detect(1);

      // The earliest arming-phase frame — pushed first, so it is the one the 4,800-sample
      // (300ms) ring must evict once enough later audio arrives during this same arm window.
      const earliestArmingSample = 0.11;
      ctx.emit(...Array(500).fill(earliestArmingSample));

      // Filler frames spread across the arming window (interleaved with partial timer
      // advances, not one big jump) whose cumulative size pushes the guard buffer well past
      // its 4,800-sample capacity, forcing the earliest frame above out of the ring.
      const fillerSample = 0.33;
      const steps = 5;
      const stepMs = Math.floor(latencyMs / steps);
      let elapsed = 0;
      for (let i = 0; i < steps - 1; i++) {
        await vi.advanceTimersByTimeAsync(stepMs);
        elapsed += stepMs;
        ctx.emit(...Array(1800).fill(fillerSample));
      }

      // The freshest frame, landing right before beep-fire — within the final ~300ms guard
      // margin — must survive the eviction that just cleared the earliest frame above.
      const freshTailSample = 0.66;
      ctx.emit(...Array(600).fill(freshTailSample));
      await vi.advanceTimersByTimeAsync(latencyMs - elapsed);
      expect(ctx.controller.state).toBe("CAPTURING_COMMAND");

      // Enough post-beep speech, then silence, to trigger submission.
      ctx.emit(...Array(1600).fill(0.3));
      ctx.emit(...Array(14400).fill(0));
      await Promise.resolve();

      expect(ctx.callbacks.onCommandReady).toHaveBeenCalledTimes(1);
      const submitted = ctx.callbacks.onCommandReady.mock.calls[0][0] as Blob;
      const bytes = new Uint8Array(await submitted.arrayBuffer());
      const view = new DataView(bytes.buffer);
      const sampleCount = (bytes.length - 44) / 2;
      const samples: number[] = [];
      for (let i = 0; i < sampleCount; i++) samples.push(view.getInt16(44 + i * 2, true) / 0x7fff);

      // The earliest arming-phase frame overflowed the 300ms ring and must have been evicted
      // — it must never reach the submitted WAV.
      expect(samples.some((value) => Math.abs(value - earliestArmingSample) < 0.001)).toBe(false);
      // The freshest ~300ms of arming-phase audio, landing right before beep-fire, survives
      // via the guard snapshot.
      expect(samples.some((value) => Math.abs(value - freshTailSample) < 0.001)).toBe(true);
    },
  );

  it("silently closes an explicit wake stop before the false-wake timeout, timer anchored at beep-fire", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);
    await ctx.controller.stopCapture();
    expect(ctx.callbacks.onSilentClose).toHaveBeenCalledTimes(1);
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
    expect(ctx.detector.resume).toHaveBeenCalledTimes(2);
  });

  it("silently closes a wake capture with no post-wake speech, 4s measured from beep-fire not from the trigger", async () => {
    vi.useFakeTimers(); const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);
    await vi.advanceTimersByTimeAsync(3999);
    expect(ctx.callbacks.onSilentClose).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(ctx.callbacks.onSilentClose).toHaveBeenCalledTimes(1);
    expect(ctx.callbacks.onCommandReady).not.toHaveBeenCalled();
    expect(ctx.detector.resume).toHaveBeenCalledTimes(2);
  });

  it("does NOT silently close a capture that heard speech, even when it outlasts the false-wake timeout", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);

    // Speak continuously past the false-wake deadline. The timeout exists to catch a
    // wake that nobody followed up on; firing it here discarded a live utterance and
    // sent no turn at all.
    for (let elapsed = 0; elapsed < 6_000; elapsed += 100) {
      ctx.emit(...Array(1600).fill(0.2));
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(ctx.callbacks.onSilentClose).not.toHaveBeenCalled();
    expect(ctx.controller.state).toBe("CAPTURING_COMMAND");
  });

  it("still auto-submits after the command ends when ambient noise rises above the level present at capture start", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);

    // Near-digital-silence at capture start, so a floor that never re-adapts settles low.
    for (let i = 0; i < 5; i++) { ctx.emit(...Array(1600).fill(0.00001)); await vi.advanceTimersByTimeAsync(100); }
    ctx.emit(...Array(1600).fill(0.2));
    await vi.advanceTimersByTimeAsync(100);

    // Ambient noise then settles well above that initial floor but far below speech.
    // A frozen floor reads every one of these frames as speech, so the silence counter
    // never advances and the capture hangs open until MAX_CAPTURE_MS.
    for (let elapsed = 0; elapsed < 2_000; elapsed += 100) {
      ctx.emit(...Array(1600).fill(0.0007));
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(ctx.callbacks.onCommandReady).toHaveBeenCalledTimes(1);
  });

  it("auto-submits after speech ends in a room whose noise floor stays above the absolute speech gate", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);

    // Room noise here (0.004) sits well above the absolute gate, which alone would read
    // every frame as speech and keep the capture open until MAX_CAPTURE_MS. Ending the
    // turn has to come from the level relative to the speech that was actually heard.
    const noise = 0.004;
    for (let i = 0; i < 4; i++) { ctx.emit(...Array(1600).fill(noise)); await vi.advanceTimersByTimeAsync(100); }
    for (let i = 0; i < 8; i++) { ctx.emit(...Array(1600).fill(0.2)); await vi.advanceTimersByTimeAsync(100); }
    expect(ctx.callbacks.onCommandReady).not.toHaveBeenCalled();

    for (let elapsed = 0; elapsed < 1_500; elapsed += 100) {
      ctx.emit(...Array(1600).fill(noise));
      await vi.advanceTimersByTimeAsync(100);
    }
    expect(ctx.callbacks.onCommandReady).toHaveBeenCalledTimes(1);
  });

  it("cancels an armed-but-not-yet-capturing trigger without ever starting a command recording", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    expect(ctx.controller.state).toBe("ARMING");
    ctx.controller.cancelCapture();
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
    await vi.advanceTimersByTimeAsync(80);
    expect(ctx.callbacks.onCaptureStarted).not.toHaveBeenCalled();
  });

  it("cancels a wake capture without submitting its audio", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);
    ctx.emit(...Array(1600).fill(0.2));

    ctx.controller.cancelCapture();
    await ctx.controller.stopCapture();

    expect(ctx.callbacks.onCommandReady).not.toHaveBeenCalled();
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
  });

  it("starts manual capture without arming, without a guard snapshot, and reports manual provenance", async () => {
    const ctx = setup(); await ctx.controller.enable(); ctx.emit(0.9); await ctx.controller.activateManual();
    expect(ctx.callbacks.onArming).not.toHaveBeenCalled();
    ctx.emit(0.3); await ctx.controller.stopCapture();
    expect(ctx.callbacks.onCaptureStarted).toHaveBeenCalledWith("manual");
    expect(ctx.callbacks.onCommandReady.mock.calls[0][1]).toBe("manual");
    expect((ctx.callbacks.onCommandReady.mock.calls[0][0] as Blob).size).toBe(46);
  });

  it("stops and invalidates listening when hidden", async () => {
    const ctx = setup(); await ctx.controller.enable(); await ctx.controller.visibilityChanged(false); ctx.detect(1);
    expect(ctx.stop).toHaveBeenCalledTimes(1); expect(ctx.callbacks.onCaptureStarted).not.toHaveBeenCalled();
  });

  it("re-loads and resumes in foreground only with enabled intent and no active turn", async () => {
    const ctx = setup(); await ctx.controller.enable(); await ctx.controller.visibilityChanged(false); await ctx.controller.visibilityChanged(true);
    expect(ctx.detector.load).toHaveBeenCalledTimes(2); expect(ctx.detector.resume).toHaveBeenCalledTimes(2);
  });

  it("restarts the stopped pipeline and consumes frames after a backgrounded submitted turn completes", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    await vi.advanceTimersByTimeAsync(80);
    ctx.emit(...Array(1600).fill(0.2)); await ctx.controller.stopCapture();
    await ctx.controller.visibilityChanged(false);
    ctx.controller.responseBoundary(true, false); ctx.controller.ttsEnded();
    await vi.advanceTimersByTimeAsync(500);
    await ctx.controller.visibilityChanged(true);
    ctx.emit(0.4);
    expect(ctx.source).toHaveBeenCalledTimes(2);
    expect(ctx.detector.accept).toHaveBeenLastCalledWith(expect.objectContaining({ samples: Float32Array.of(0.4) }));
  });

  it("reports worker failure without removing manual activation", async () => {
    const ctx = setup(); (ctx.detector.load as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error("worker failed"));
    await ctx.controller.enable(); await ctx.controller.activateManual();
    expect(ctx.callbacks.onWakeUnavailable).toHaveBeenCalledWith("worker failed");
    expect(ctx.callbacks.onCaptureStarted).toHaveBeenCalledWith("manual");
  });

  it("waits for TTS then 500ms cooldown before listening", async () => {
    vi.useFakeTimers(); const ctx = setup(); await ctx.controller.enable(); await ctx.controller.activateManual(); await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(true, false); ctx.controller.ttsEnded(); await vi.advanceTimersByTimeAsync(499);
    expect(ctx.detector.resume).toHaveBeenCalledTimes(1); await vi.advanceTimersByTimeAsync(1);
    expect(ctx.detector.resume).toHaveBeenCalledTimes(2);
  });

  it("disposes every resource and is idempotent, including a controller that is mid-arming", async () => {
    vi.useFakeTimers();
    const ctx = setup(80); await ctx.controller.enable(); ctx.detect(1);
    expect(ctx.controller.state).toBe("ARMING");
    await ctx.controller.dispose(); await ctx.controller.dispose();
    expect(ctx.detector.dispose).toHaveBeenCalledTimes(1); expect(ctx.stop).toHaveBeenCalledTimes(1);
  });

  // Issue #343: cửa sổ nghe tiếp sau lượt "hasMoreToRead" — nghe được tiếng nói thì
  // vào thẳng CAPTURING_COMMAND, không cần "Hey Vi Vi"; hết giờ thì quay lại nghe tên gọi.
  describe("FOLLOW_UP_WINDOW", () => {
    /** Đưa controller tới PROCESSING rồi hết cooldown với `hasMoreToRead` cho trước. */
    async function toiCooldown(ctx: ReturnType<typeof setup>, hasMoreToRead: boolean) {
      await ctx.controller.enable();
      await ctx.controller.activateManual();
      await ctx.controller.stopCapture();
      ctx.controller.responseBoundary(false, hasMoreToRead);
      await vi.advanceTimersByTimeAsync(500);
    }

    it("hasMoreToRead=true ⇒ sau cooldown mở cửa sổ nghe tiếp, không phải LISTENING_FOR_WAKEWORD", async () => {
      vi.useFakeTimers();
      const ctx = setup();
      await toiCooldown(ctx, true);
      expect(ctx.controller.state).toBe("FOLLOW_UP_WINDOW");
      expect(ctx.callbacks.onFollowUpWindowStarted).toHaveBeenCalledTimes(1);
    });

    it("hasMoreToRead=false ⇒ về LISTENING_FOR_WAKEWORD như cũ, không mở cửa sổ", async () => {
      vi.useFakeTimers();
      const ctx = setup();
      await toiCooldown(ctx, false);
      expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
      expect(ctx.callbacks.onFollowUpWindowStarted).not.toHaveBeenCalled();
    });

    it("nghe được tiếng nói trong cửa sổ ⇒ CAPTURING_COMMAND thẳng, onArming(true) — không beep", async () => {
      vi.useFakeTimers();
      const ctx = setup();
      await toiCooldown(ctx, true);
      ctx.callbacks.onArming.mockClear();

      ctx.emit(...Array(160).fill(0.3));

      expect(ctx.controller.state).toBe("CAPTURING_COMMAND");
      expect(ctx.callbacks.onArming).toHaveBeenCalledTimes(1);
      expect(ctx.callbacks.onArming).toHaveBeenCalledWith(true);
      expect(ctx.callbacks.onCaptureStarted).toHaveBeenLastCalledWith("wake_word");
    });

    it(`hết ${FOLLOW_UP_WINDOW_MS}ms mà không ai nói ⇒ về LISTENING_FOR_WAKEWORD, báo onFollowUpWindowExpired`, async () => {
      vi.useFakeTimers();
      const ctx = setup();
      await toiCooldown(ctx, true);

      await vi.advanceTimersByTimeAsync(FOLLOW_UP_WINDOW_MS);

      expect(ctx.callbacks.onFollowUpWindowExpired).toHaveBeenCalledTimes(1);
      expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
    });

    it("đóng overlay giữa cửa sổ (cancelCapture) ⇒ về LISTENING_FOR_WAKEWORD ngay, không đợi hết giờ", async () => {
      vi.useFakeTimers();
      const ctx = setup();
      await toiCooldown(ctx, true);

      ctx.controller.cancelCapture();

      expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
      // Hẹn giờ hết cửa sổ đã bị huỷ theo — không còn gọi onFollowUpWindowExpired sau đó.
      await vi.advanceTimersByTimeAsync(FOLLOW_UP_WINDOW_MS);
      expect(ctx.callbacks.onFollowUpWindowExpired).not.toHaveBeenCalled();
    });

    it("mic thật không đóng giữa cửa sổ — cùng MicrophonePipeline, không gọi lại getUserMedia", async () => {
      vi.useFakeTimers();
      const ctx = setup();
      await toiCooldown(ctx, true);
      const soLanMoMicTruoc = ctx.source.mock.calls.length;

      ctx.emit(...Array(160).fill(0.3));

      expect(ctx.source).toHaveBeenCalledTimes(soLanMoMicTruoc);
    });
  });

  // Issue #342: vạch sóng phải đọc RMS thật thay vì nhịp CSS cố định.
  describe("onLevel — mức 0..1 cho vạch sóng phản ứng theo giọng nói thật", () => {
    it("chuẩn hoá theo đỉnh RMS của chính lượt ghi, không phải một thang tuyệt đối", async () => {
      const ctx = setup();
      await ctx.controller.enable();
      await ctx.controller.activateManual();

      // Khung to nhất từ đầu tới giờ ⇒ level = 1 (chính nó là đỉnh).
      ctx.emit(...Array(160).fill(0.3));
      expect(ctx.callbacks.onLevel).toHaveBeenLastCalledWith(1);

      // Khung nhỏ hơn nhưng vẫn là giọng nói (không phải im lặng) ⇒ so với đỉnh
      // 0.3 đã thấy, không so với một ngưỡng tuyệt đối cố định.
      ctx.emit(...Array(160).fill(0.15));
      expect(ctx.callbacks.onLevel).toHaveBeenLastCalledWith(0.5);
    });

    it("mic tắt tiếng ⇒ chưa từng có đỉnh nào ⇒ level luôn 0, không nhảy", async () => {
      const ctx = setup();
      await ctx.controller.enable();
      await ctx.controller.activateManual();
      ctx.callbacks.onLevel.mockClear();

      ctx.emit(...Array(160).fill(0));
      ctx.emit(...Array(160).fill(0));
      ctx.emit(...Array(160).fill(0));

      expect(ctx.callbacks.onLevel).toHaveBeenCalledTimes(3);
      for (const call of ctx.callbacks.onLevel.mock.calls) expect(call[0]).toBe(0);
    });
  });
});

/**
 * Ngân sách cứng cho chuỗi nghe tiếp — phanh 2 của spec §3.2.
 *
 * Phanh 1 (`keepListening` từ backend) dựa vào "xe hiểu được câu vừa rồi". Nhưng một câu
 * nói với NGƯỜI cũng có thể hiểu được: đo 29/08, "Trời nóng quá bật điều hòa lên đi em"
 * ra `completed`. Nên cần một trần **không phụ thuộc nội dung**.
 *
 * Hai nửa, và mỗi nửa bịt một hình dạng khác: đếm lượt không chặn được một chuỗi lượt
 * NGẮN kéo dài mãi; đồng hồ tường không chặn được năm lượt dồn trong ba giây.
 */
describe("ngân sách chuỗi nghe tiếp", () => {
  /** Mở phiên bằng bấm mic, kết thúc lượt đầu, tới cửa sổ nghe tiếp thứ nhất. */
  async function moChuoi(ctx: ReturnType<typeof setup>) {
    await ctx.controller.enable();
    await ctx.controller.activateManual();
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, true);
    await vi.advanceTimersByTimeAsync(500);
  }

  /** Một lượt nối: nói trong cửa sổ, kết thúc lượt, chờ hết cooldown. */
  async function noiTiep(ctx: ReturnType<typeof setup>) {
    ctx.emit(...Array(1600).fill(0.3));
    await vi.advanceTimersByTimeAsync(0);
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, true);
    await vi.advanceTimersByTimeAsync(500);
  }

  it("mở được cửa sổ đầu tiên khi backend bảo còn nghe", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await moChuoi(ctx);
    expect(ctx.controller.state).toBe("FOLLOW_UP_WINDOW");
  });

  it("chạm trần số lượt nối thì về nghe tên gọi, dù backend vẫn bảo còn nghe", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await moChuoi(ctx);
    for (let i = 1; i < MAX_CHAINED_FOLLOW_UPS; i += 1) {
      await noiTiep(ctx);
      expect(ctx.controller.state).toBe("FOLLOW_UP_WINDOW");
    }
    await noiTiep(ctx);
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
  });

  it("quá trần đồng hồ tường thì không mở nữa, dù mới một lượt", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await ctx.controller.enable();
    await ctx.controller.activateManual();
    await vi.advanceTimersByTimeAsync(FOLLOW_UP_SESSION_MAX_MS + 1);
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, true);
    await vi.advanceTimersByTimeAsync(500);
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
  });

  it("bấm mic lại thì cả hai bộ đếm chạy lại từ đầu", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await ctx.controller.enable();
    await ctx.controller.activateManual();
    await vi.advanceTimersByTimeAsync(FOLLOW_UP_SESSION_MAX_MS + 1);
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, true);
    await vi.advanceTimersByTimeAsync(500);
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");

    await ctx.controller.activateManual();
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, true);
    await vi.advanceTimersByTimeAsync(500);
    expect(ctx.controller.state).toBe("FOLLOW_UP_WINDOW");
  });

  it("backend bảo thôi thì đóng ngay, không cần chạm trần nào", async () => {
    vi.useFakeTimers();
    const ctx = setup();
    await ctx.controller.enable();
    await ctx.controller.activateManual();
    await ctx.controller.stopCapture();
    ctx.controller.responseBoundary(false, false);
    await vi.advanceTimersByTimeAsync(500);
    expect(ctx.controller.state).toBe("LISTENING_FOR_WAKEWORD");
  });
});
