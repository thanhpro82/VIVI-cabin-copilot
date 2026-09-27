import { MicrophonePipeline, type FrameSubscription } from "@/lib/audio/microphonePipeline";
import { ARM_GUARD_SAMPLES, PCM_SAMPLE_RATE } from "@/lib/audio/pcm";
import { ArmGuardBuffer } from "@/lib/audio/armGuardBuffer";
import { createPipelineRecording, type WavRecording } from "@/lib/audio/pipelineRecording";
import type { WakeDetection, WakeWordDetector } from "./types";
import { transition, type WakeEvent, type WakeMachine, type WakeState } from "./wakeWordState";

const FALSE_WAKE_TIMEOUT_MS = 4_000;
const MAX_CAPTURE_MS = 12_000;
const COMMAND_SILENCE_MS = 900;
const RESPONSE_COOLDOWN_MS = 500;
// Speech gate for command capture. Measured against a real microphone (2026-08-18),
// speech and the room's own noise floor sat far closer together than a fixed threshold
// can separate across rooms and devices, so the gate tracks a live noise floor (an EMA
// over frames it did not classify as speech) and fires SPEECH_RMS_MARGIN above it --
// the "adapt to the room" approach real VAD implementations use.
//
// Deliberately NOT shared with pcm.ts's SILENCE_RMS_THRESHOLD (kept at 0.02, reverted
// after an attempt to share these broke the manual pipeline in an unrelated way).
//
// The estimate is min-tracking and deliberately does NOT depend on the speech decision
// it feeds. An EMA taken only over frames already classified as silence deadlocks: once
// ambient noise sits above the current threshold every frame is called speech, so no
// frame ever updates the floor, the threshold stays stale forever, the silence counter
// never advances and the capture hangs open until MAX_CAPTURE_MS. Tracking the running
// minimum instead -- fast downward, slow upward creep on every frame regardless of
// classification -- is what lets the estimate climb out of a too-low value.
//
// NOISE_FLOOR_MAX is the other load-bearing half: it sits below real speech, so neither
// the upward creep nor a noisy stretch (including the arm beep's own speaker->mic echo
// tail) can ever push the threshold above the voice it exists to detect.
const SPEECH_RMS_MARGIN = 0.0002;
const NOISE_FLOOR_MIN = 0.0002;
/**
 * Headroom for the floor to track a genuinely noisy room. Measured through this exact
 * browser pipeline, real speech lands at 0.03-0.32 RMS and a quiet room at 0.0000-0.0007,
 * so 0.01 stays about 3x below the quietest observed speech while leaving the estimate
 * room to climb more than 10x above a quiet-room floor. An earlier 0.001 was set from a
 * single ambiguous reading and sat too low: any room whose noise exceeded it pinned every
 * frame above the threshold, so the capture read as continuous speech and never auto-stopped.
 */
const NOISE_FLOOR_MAX = 0.01;
/**
 * Once speech has actually been heard, silence is additionally judged RELATIVE to how
 * loud that speech was: anything under this fraction of the utterance's peak counts as
 * silence even if it clears the absolute noise-floor gate. An absolute threshold alone
 * cannot end-point reliably, because it has to be low enough to hear a quiet talker yet
 * high enough to sit above a noisy room, and a single room can violate both at once --
 * which is what left captures running until MAX_CAPTURE_MS. Scaling with the speaker's
 * own level sidesteps the absolute-level question entirely.
 */
const SILENCE_PEAK_RATIO = 0.08;
/** Downward tracking, per millisecond: settles onto a newly quiet room in ~100 ms. */
const NOISE_FLOOR_FALL_ALPHA_PER_MS = 0.023;
/** Upward creep, per millisecond: doubles in ~500 ms, bounded by NOISE_FLOOR_MAX. */
const NOISE_FLOOR_RISE_PER_MS = 1.001386;
const INITIAL_NOISE_FLOOR = 0.0003;
/**
 * Duration of the arm beep (`playArmBeep` in DriverShellProvider.tsx), in milliseconds.
 * Shared here so the beep's actual playback length and the controller's default
 * `armLatencyMs` (the delay before "beep fired" starts real command capture) can never
 * drift apart — command capture must not begin before the beep audio finishes playing,
 * or the beep's speaker->mic echo can be mistaken for post-wake speech.
 */
export const ARM_BEEP_DURATION_MS = 150;
const DEFAULT_ARM_LATENCY_MS = ARM_BEEP_DURATION_MS;
/**
 * How long a "hasMoreToRead" turn keeps listening for a follow-up WITHOUT the wake
 * phrase, after cooldown elapses (issue #343). Half of MAX_CAPTURE_MS: long enough for
 * one follow-up sentence ("nghe tiếp"), short enough to keep the no-wake-phrase window
 * — the one stretch where any speech reaches the backend unfiltered — small.
 */
export const FOLLOW_UP_WINDOW_MS = 6_000;

/**
 * Trần số lượt nối liên tiếp kể từ một lần mở phiên ("Hey VIVI" hoặc bấm mic) — phanh 2
 * của spec §3.2, nửa thứ nhất.
 *
 * Phanh 1 (`keepListening` từ backend) dựa vào *"xe hiểu được câu vừa rồi"*. Nhưng một câu
 * nói với NGƯỜI cũng có thể hiểu được: đo 29/08, `"Trời nóng quá bật điều hòa lên đi em"`
 * ra `completed`. Nên cần một trần **không phụ thuộc nội dung**.
 *
 * 5 là ước lượng, **không phải số đo** — repo chưa có vòng user research nào. Đo lại bằng
 * `scripts/do_phan_bo_luot.py` rồi chỉnh.
 */
export const MAX_CHAINED_FOLLOW_UPS = 5;

/**
 * Trần đồng hồ tường cho cả một chuỗi nghe tiếp, tính từ lần mở phiên gần nhất — phanh 2,
 * nửa thứ hai.
 *
 * Cần cả hai nửa vì mỗi nửa bịt một hình dạng khác: đếm lượt không chặn được một chuỗi
 * lượt **ngắn** kéo dài mãi; đồng hồ tường không chặn được năm lượt dồn trong ba giây.
 */
export const FOLLOW_UP_SESSION_MAX_MS = 60_000;
type CaptureMode = "manual" | "wake_word";

export interface WakeWordControllerCallbacks {
  onStateChange(state: WakeState): void;
  /**
   * `silent`: true when arming came from the follow-up window (issue #343) — the driver
   * was just invited to keep talking, so no beep, unlike a fresh wake-phrase detection.
   */
  onArming(silent: boolean): void;
  onCaptureStarted(mode: CaptureMode): void;
  onCommandReady(audio: Blob, mode: CaptureMode): void;
  onSilentClose(): void;
  onWakeUnavailable(message: string): void;
  /** Follow-up window opened (issue #343) — UI can start a FOLLOW_UP_WINDOW_MS countdown. */
  onFollowUpWindowStarted(): void;
  /** Follow-up window closed without speech — UI should end the countdown and beep low. */
  onFollowUpWindowExpired(): void;
  /**
   * Fires once per captured frame with a 0..1 level, for level-reactive UI (issue #342).
   * Normalized against this capture's own running `peakRms`, not a fixed absolute scale
   * — `autoGainControl: true` on the pipeline compresses raw RMS, so an absolute mapping
   * would read as flat. Before any speech is heard (no peak yet) the level is 0.
   */
  onLevel?(level: number): void;
}

export interface WakeWordControllerDeps {
  pipeline: MicrophonePipeline;
  detector: WakeWordDetector;
  callbacks: WakeWordControllerCallbacks;
  setTimer: typeof setTimeout;
  clearTimer: typeof clearTimeout;
  /** Delay between an accepted wake trigger and the beep being treated as fired. Default ARM_BEEP_DURATION_MS. */
  armLatencyMs?: number;
}

/** Coordinates one shared microphone pipeline across offline wake detection and command capture. */
export class WakeWordController {
  private machine: WakeMachine = { state: "IDLE", waitingForTts: false, waitingForCooldown: false };
  private readonly buffer = new ArmGuardBuffer(ARM_GUARD_SAMPLES);
  private listeningSubscription: FrameSubscription | null = null;
  private armingSubscription: FrameSubscription | null = null;
  private captureSubscription: FrameSubscription | null = null;
  private followUpSubscription: FrameSubscription | null = null;
  private recording: WavRecording | null = null;
  private captureMode: CaptureMode | null = null;
  private armingThroughSequence = -1;
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private generation = 0;
  private enabledIntent = false;
  private visible = true;
  private disposed = false;
  private detectorAvailable = false;
  private postWakeSpeech = false;
  private silenceMs = 0;
  private noiseFloorRms = INITIAL_NOISE_FLOOR;
  private peakRms = 0;
  /** Backend có bảo còn nghe tiếp không, của lượt đang chờ hết cooldown (spec §3.1) —
   * `responseBoundary()` ghi, `scheduleCooldown()` đọc đúng một lần khi timer nổ. */
  private pendingKeepListening = false;
  /** Số lượt đã nối liên tiếp trong chuỗi hiện tại. Reset khi mở phiên mới. */
  private soLuotNoi = 0;
  /** `Date.now()` lúc mở chuỗi hiện tại. `0` = chưa có chuỗi nào đang chạy.
   *
   * Dùng `Date.now()` chứ không thêm nguồn thời gian vào `deps`: controller chỉ tiêm
   * `setTimer`/`clearTimer`, và `vi.useFakeTimers()` đã giả lập luôn `Date.now()`, nên
   * test vẫn điều khiển được thời gian mà không phải nới hợp đồng `deps`. */
  private chuoiBatDauAt = 0;

  constructor(private readonly deps: WakeWordControllerDeps) {}
  get state(): WakeState { return this.machine.state; }

  async enable(): Promise<void> {
    if (this.disposed) return;
    this.enabledIntent = true;
    await this.startListening();
  }

  async disable(): Promise<void> {
    if (this.disposed) return;
    this.enabledIntent = false;
    this.invalidate(); this.stopCaptureResources(); this.stopListening(); this.deps.detector.pause();
    this.apply({ type: "DISABLE" }); this.buffer.clear();
    await this.deps.pipeline.stop();
  }

  async activateManual(): Promise<void> {
    if (this.disposed || !this.visible || this.machine.state === "ARMING" || this.machine.state === "CAPTURING_COMMAND" || this.machine.state === "PROCESSING" || this.machine.state === "FOLLOW_UP_WINDOW") return;
    if (this.machine.state === "IDLE") {
      const generation = this.generation;
      try { await this.deps.pipeline.start(); }
      catch (error) { if (this.isCurrent(generation)) this.deps.callbacks.onWakeUnavailable(this.errorMessage(error)); return; }
      if (!this.isCurrent(generation) || !this.visible || this.disposed) return;
      this.apply({ type: "READY" });
    }
    this.moChuoiMoi();
    this.apply({ type: "MANUAL_ACTIVATE" });
    this.deps.detector.pause();
    this.stopListening();
    this.beginCommandCapture("manual", new Float32Array(0), 0);
  }

  async stopCapture(): Promise<void> { await this.submitCapture(); }

  /** Cancels an in-progress arm, command capture, or follow-up window (issue #343) without
   * turning any PCM captured so far into a backend turn. */
  cancelCapture(): void {
    if (
      this.disposed ||
      (this.machine.state !== "ARMING" &&
        this.machine.state !== "CAPTURING_COMMAND" &&
        this.machine.state !== "FOLLOW_UP_WINDOW")
    )
      return;
    this.invalidate();
    this.stopCaptureResources();
    const resume = this.enabledIntent && this.visible;
    this.apply({ type: "CAPTURE_CANCELED", resume });
    if (resume) this.resumeAfterBoundary();
  }

  /**
   * `keepListening`: backend có bảo hội thoại còn đang chạy không (spec §3.1)? Cất cho
   * `scheduleCooldown()`, nơi quyết định — khi timer cooldown thật sự nổ — mở cửa sổ nghe
   * tiếp hay quay thẳng về LISTENING_FOR_WAKEWORD.
   *
   * Thay `hasMoreToRead` của #343: nó nói *"còn đoạn sổ tay chưa đọc"*, còn cờ mới nói
   * *"hội thoại đang chạy"*. Giữ tên cũ cho nghĩa mới là cách để test xanh mà bảo vệ
   * nhầm thứ.
   */
  responseBoundary(ttsPlaying: boolean, keepListening: boolean): void {
    if (this.disposed) return;
    this.pendingKeepListening = keepListening;
    const before = this.machine;
    this.apply({ type: "RESPONSE_BOUNDARY", ttsPlaying });
    if (before === this.machine || this.machine.state !== "PROCESSING" || !this.machine.waitingForCooldown) return;
    this.scheduleCooldown();
  }

  ttsEnded(): void {
    if (this.disposed) return;
    const wasWaiting = this.machine.waitingForTts;
    this.apply({ type: "TTS_ENDED" });
    if (wasWaiting && this.machine.waitingForCooldown) this.scheduleCooldown();
  }

  async visibilityChanged(visible: boolean): Promise<void> {
    if (this.disposed || this.visible === visible) return;
    this.visible = visible;
    if (!visible) {
      this.invalidate(); this.stopCaptureResources(); this.stopListening(); this.deps.detector.pause();
      if (this.machine.state !== "PROCESSING") this.apply({ type: "DISABLE" });
      this.buffer.clear(); await this.deps.pipeline.stop(); return;
    }
    if (this.enabledIntent && this.machine.state !== "PROCESSING" && this.machine.state !== "ARMING" && this.machine.state !== "CAPTURING_COMMAND") {
      await this.startListening();
    }
  }

  async dispose(): Promise<void> {
    if (this.disposed) return;
    this.disposed = true; this.enabledIntent = false; this.invalidate(); this.stopCaptureResources(); this.stopListening();
    this.deps.detector.dispose(); this.buffer.clear(); await this.deps.pipeline.stop();
  }

  private async startListening(): Promise<void> {
    if (this.disposed || !this.visible || !this.enabledIntent || this.machine.state === "PROCESSING" || this.machine.state === "ARMING" || this.machine.state === "CAPTURING_COMMAND") return;
    const generation = this.generation;
    try {
      await this.deps.detector.load();
      if (!this.isCurrent(generation) || !this.enabledIntent || !this.visible) return;
      this.detectorAvailable = true;
      await this.deps.pipeline.start();
    } catch (error) {
      if (this.isCurrent(generation)) { this.detectorAvailable = false; this.deps.callbacks.onWakeUnavailable(this.errorMessage(error)); }
      return;
    }
    if (!this.isCurrent(generation) || !this.enabledIntent || !this.visible) return;
    this.apply({ type: "READY" }); this.subscribeListening(generation);
  }

  private subscribeListening(generation: number): void {
    if (this.machine.state !== "LISTENING_FOR_WAKEWORD" || this.listeningSubscription || !this.detectorAvailable) return;
    this.listeningSubscription = this.deps.pipeline.subscribe((frame) => {
      if (!this.isCurrent(generation) || this.machine.state !== "LISTENING_FOR_WAKEWORD") return;
      this.buffer.push(frame); this.deps.detector.accept(frame);
    });
    this.deps.detector.resume(generation, (detection) => this.handleDetection(generation, detection), (message) => {
      if (this.isCurrent(generation)) { this.detectorAvailable = false; this.deps.callbacks.onWakeUnavailable(message); }
    });
  }

  private handleDetection(generation: number, _detection: WakeDetection): void {
    if (!this.isCurrent(generation) || this.machine.state !== "LISTENING_FOR_WAKEWORD") return;
    this.beginArming();
  }

  /** Wake phrase accepted: arm (beep/overlay), suppress detection, keep only a short guard buffer rolling. */
  private beginArming(): void {
    this.moChuoiMoi();
    this.apply({ type: "WAKE_DETECTED" });
    this.deps.detector.pause();
    this.stopListening();
    this.buffer.clear();
    this.armingThroughSequence = -1;
    const generation = this.generation;
    this.armingSubscription = this.deps.pipeline.subscribe((frame) => {
      if (!this.isCurrent(generation) || this.machine.state !== "ARMING") return;
      this.buffer.push(frame);
      this.armingThroughSequence = frame.sequence;
    });
    this.deps.callbacks.onArming(false);
    this.schedule(this.deps.armLatencyMs ?? DEFAULT_ARM_LATENCY_MS, generation, () => this.fireBeep(generation));
  }

  private fireBeep(generation: number): void {
    if (!this.isCurrent(generation) || this.machine.state !== "ARMING") return;
    this.armingSubscription?.unsubscribe(); this.armingSubscription = null;
    const guardSnapshot = this.buffer.snapshotThrough(this.armingThroughSequence);
    const afterSequence = this.armingThroughSequence;
    this.apply({ type: "BEEP_FIRED" });
    this.beginCommandCapture("wake_word", guardSnapshot, afterSequence);
  }

  private beginCommandCapture(mode: CaptureMode, initialPcm: Float32Array, afterSequence: number): void {
    this.captureMode = mode; this.postWakeSpeech = mode === "manual"; this.silenceMs = 0;
    this.noiseFloorRms = INITIAL_NOISE_FLOOR;
    this.peakRms = 0;
    this.recording = createPipelineRecording(this.deps.pipeline, { initialPcm, afterSequence });
    const generation = this.generation;
    this.captureSubscription = this.deps.pipeline.subscribe((frame) => this.observeCaptureFrame(generation, frame.samples));
    this.deps.callbacks.onCaptureStarted(mode);
    // Only a capture that never heard ANY speech is a false wake. Firing this
    // unconditionally discarded live captures mid-utterance: speak a command
    // that runs past FALSE_WAKE_TIMEOUT_MS (or start speaking late) and the
    // whole recording was thrown away with no turn ever sent. Once speech has
    // been heard, ending the capture belongs to the silence detector or to
    // MAX_CAPTURE_MS, never here.
    if (mode === "wake_word") {
      this.schedule(FALSE_WAKE_TIMEOUT_MS, generation, () => {
        if (!this.postWakeSpeech) this.silentClose();
      });
    }
    this.schedule(MAX_CAPTURE_MS, generation, () => void this.submitCapture());
  }

  private observeCaptureFrame(generation: number, samples: Float32Array): void {
    if (!this.isCurrent(generation) || this.machine.state !== "CAPTURING_COMMAND" || !this.recording) return;
    let sum = 0; for (const sample of samples) sum += sample * sample;
    const rms = samples.length > 0 ? Math.sqrt(sum / samples.length) : 0;
    // Before any speech is heard the gate is purely absolute, so a quiet talker is never
    // locked out. Once speech has been heard the peak-relative floor also applies, which
    // is what lets a capture end-point in a room whose noise clears the absolute gate.
    const relativeGate = this.postWakeSpeech ? this.peakRms * SILENCE_PEAK_RATIO : 0;
    const speech = rms >= Math.max(this.noiseFloorRms + SPEECH_RMS_MARGIN, relativeGate);
    const duration = (samples.length / PCM_SAMPLE_RATE) * 1000;
    this.trackNoiseFloor(rms, duration);
    if (speech) this.peakRms = Math.max(this.peakRms, rms);
    this.deps.callbacks.onLevel?.(this.peakRms > 0 ? Math.min(1, rms / this.peakRms) : 0);
    if (speech) { this.postWakeSpeech = true; this.silenceMs = 0; return; }
    if (this.postWakeSpeech) { this.silenceMs += duration; if (this.silenceMs >= COMMAND_SILENCE_MS) void this.submitCapture(); }
  }

  /** Min-tracking noise estimate: runs on every frame, never gated on the speech decision. */
  private trackNoiseFloor(rms: number, durationMs: number): void {
    const tracked =
      rms < this.noiseFloorRms
        ? this.noiseFloorRms + (rms - this.noiseFloorRms) * Math.min(1, NOISE_FLOOR_FALL_ALPHA_PER_MS * durationMs)
        : this.noiseFloorRms * NOISE_FLOOR_RISE_PER_MS ** durationMs;
    this.noiseFloorRms = Math.min(NOISE_FLOOR_MAX, Math.max(NOISE_FLOOR_MIN, tracked));
  }

  private async submitCapture(): Promise<void> {
    if (this.disposed || this.machine.state !== "CAPTURING_COMMAND" || !this.recording || !this.captureMode) return;
    const generation = this.generation; const recording = this.recording; const mode = this.captureMode;
    this.stopCaptureResources(); const audio = await recording.stop();
    if (!this.isCurrent(generation) || this.disposed || this.machine.state !== "CAPTURING_COMMAND") return;
    if (mode === "wake_word" && !this.postWakeSpeech) { this.silentClose(); return; }
    this.apply({ type: "CAPTURE_SUBMITTED" }); this.deps.callbacks.onCommandReady(audio, mode);
  }

  private silentClose(): void {
    if (this.disposed || this.machine.state !== "CAPTURING_COMMAND") return;
    this.stopCaptureResources(); this.deps.callbacks.onSilentClose();
    const resume = this.enabledIntent && this.visible;
    this.apply({ type: "CAPTURE_CANCELED", resume });
    if (resume) this.resumeAfterBoundary();
  }

  /** Mở một chuỗi nghe tiếp mới: cả hai bộ đếm của phanh 2 chạy lại từ đầu.
   *
   * Gọi ở CẢ HAI đường vào — wake word và bấm mic tay. Mỗi lần tài xế chủ động gọi trợ lý
   * là một cuộc mới, nên ngân sách của cuộc trước không được đè lên nó.
   */
  private moChuoiMoi(): void {
    this.soLuotNoi = 0;
    this.chuoiBatDauAt = Date.now();
  }

  private scheduleCooldown(): void {
    const generation = this.generation;
    // Ba điều kiện gộp vào đúng một cờ trước khi xuống bảng chuyển trạng thái — bảng ấy
    // là hàm thuần và cố ý không biết gì về ngân sách. Thứ tự `&&` không quan trọng;
    // gộp ở đây thì cả ba phanh cùng một chỗ, đọc một lượt là thấy hết.
    const conNganSach = this.soLuotNoi < MAX_CHAINED_FOLLOW_UPS;
    const conHan = this.chuoiBatDauAt > 0 && Date.now() - this.chuoiBatDauAt <= FOLLOW_UP_SESSION_MAX_MS;
    const keepListening = this.pendingKeepListening && conNganSach && conHan;
    this.schedule(RESPONSE_COOLDOWN_MS, generation, () => {
      this.apply({ type: "COOLDOWN_ELAPSED", keepListening });
      if (this.machine.state === "FOLLOW_UP_WINDOW") this.soLuotNoi += 1;
      else this.soLuotNoi = 0;
      if (this.machine.state === "FOLLOW_UP_WINDOW" && this.enabledIntent && this.visible) {
        this.beginFollowUpListening();
        return;
      }
      if (this.machine.state === "LISTENING_FOR_WAKEWORD" && this.enabledIntent && this.visible) this.resumeAfterBoundary();
    });
  }

  /**
   * Passively listens for ANY speech (not the wake phrase) for FOLLOW_UP_WINDOW_MS after a
   * "hasMoreToRead" turn (issue #343) — the driver was just invited to keep talking, so
   * requiring "Hey Vi Vi" again would be asking them to call the assistant's name mid-reply.
   * Reuses the same noise-floor-relative speech gate `observeCaptureFrame` uses once
   * post-wake speech has been heard; here nothing has been heard yet, so the gate stays
   * purely absolute (no relative/peak term), same as capture's pre-speech phase.
   */
  private beginFollowUpListening(): void {
    if (this.disposed || !this.visible || !this.enabledIntent) return;
    this.noiseFloorRms = INITIAL_NOISE_FLOOR;
    const generation = this.generation;
    this.followUpSubscription = this.deps.pipeline.subscribe((frame) => this.observeFollowUpFrame(generation, frame.sequence, frame.samples));
    this.deps.callbacks.onFollowUpWindowStarted();
    this.schedule(FOLLOW_UP_WINDOW_MS, generation, () => {
      if (this.machine.state !== "FOLLOW_UP_WINDOW") return;
      this.followUpSubscription?.unsubscribe();
      this.followUpSubscription = null;
      // FOLLOW_UP_TIMEOUT always maps FOLLOW_UP_WINDOW -> LISTENING_FOR_WAKEWORD
      // (see wakeWordState.ts) — no need to re-check machine.state after apply().
      this.apply({ type: "FOLLOW_UP_TIMEOUT" });
      this.deps.callbacks.onFollowUpWindowExpired();
      if (this.enabledIntent && this.visible) this.resumeAfterBoundary();
    });
  }

  private observeFollowUpFrame(generation: number, sequence: number, samples: Float32Array): void {
    if (!this.isCurrent(generation) || this.machine.state !== "FOLLOW_UP_WINDOW") return;
    let sum = 0; for (const sample of samples) sum += sample * sample;
    const rms = samples.length > 0 ? Math.sqrt(sum / samples.length) : 0;
    const duration = (samples.length / PCM_SAMPLE_RATE) * 1000;
    const speech = rms >= this.noiseFloorRms + SPEECH_RMS_MARGIN;
    this.trackNoiseFloor(rms, duration);
    if (!speech) return;
    this.followUpSubscription?.unsubscribe();
    this.followUpSubscription = null;
    this.apply({ type: "FOLLOW_UP_SPEECH_DETECTED" });
    // No beep (`silent: true`) — the driver was already invited to keep talking; a beep
    // here would say "start now" a beat after they may already have started.
    this.deps.callbacks.onArming(true);
    // This frame IS the first bit of speech — carry it into the capture as initialPcm
    // (same idea as the arm guard-buffer snapshot) instead of dropping it.
    this.beginCommandCapture("wake_word", samples, sequence);
  }

  private resumeAfterBoundary(): void {
    if (this.disposed || !this.visible || !this.enabledIntent) return;
    this.buffer.clear(); this.subscribeListening(this.generation);
  }
  private stopListening(): void { this.listeningSubscription?.unsubscribe(); this.listeningSubscription = null; }
  private stopCaptureResources(): void {
    this.armingSubscription?.unsubscribe(); this.armingSubscription = null;
    this.captureSubscription?.unsubscribe(); this.captureSubscription = null;
    this.followUpSubscription?.unsubscribe(); this.followUpSubscription = null;
    this.recording?.cancel(); this.recording = null; this.captureMode = null; this.clearTimers();
  }
  private invalidate(): void { this.generation += 1; this.clearTimers(); }
  private clearTimers(): void { for (const timer of this.timers) this.deps.clearTimer(timer); this.timers.clear(); }
  private schedule(delay: number, generation: number, callback: () => void): void {
    const timer = this.deps.setTimer(() => { this.timers.delete(timer); if (this.isCurrent(generation)) callback(); }, delay);
    this.timers.add(timer);
  }
  private apply(event: WakeEvent): void { const before = this.machine; this.machine = transition(this.machine, event); if (before.state !== this.machine.state) this.deps.callbacks.onStateChange(this.machine.state); }
  private isCurrent(generation: number): boolean { return !this.disposed && generation === this.generation; }
  private errorMessage(error: unknown): string { return error instanceof Error ? error.message : String(error); }
}
