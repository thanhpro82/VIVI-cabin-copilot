import { describe, expect, it } from "vitest";
import { transition, type WakeMachine } from "./wakeWordState";

const idle: WakeMachine = { state: "IDLE", waitingForTts: false, waitingForCooldown: false };

describe("wake-word transition table", () => {
  it("wake detection arms instead of capturing directly; manual activation still captures directly", () => {
    expect(transition(idle, { type: "WAKE_DETECTED" })).toBe(idle);
    const listening = transition(idle, { type: "READY" });

    const arming = transition(listening, { type: "WAKE_DETECTED" });
    expect(arming.state).toBe("ARMING");

    const manualCapture = transition(listening, { type: "MANUAL_ACTIVATE" });
    expect(manualCapture.state).toBe("CAPTURING_COMMAND");
  });

  it("ignores a repeat wake/manual trigger while arming or capturing", () => {
    const listening = transition(idle, { type: "READY" });
    const arming = transition(listening, { type: "WAKE_DETECTED" });
    expect(transition(arming, { type: "WAKE_DETECTED" })).toBe(arming);
    expect(transition(arming, { type: "MANUAL_ACTIVATE" })).toBe(arming);

    const capture = transition(arming, { type: "BEEP_FIRED" });
    expect(capture.state).toBe("CAPTURING_COMMAND");
    expect(transition(capture, { type: "WAKE_DETECTED" })).toBe(capture);
    expect(transition(capture, { type: "MANUAL_ACTIVATE" })).toBe(capture);
  });

  it("cancels out of arming back to listening or idle, same as canceling a capture", () => {
    const listening = transition(idle, { type: "READY" });
    const arming = transition(listening, { type: "WAKE_DETECTED" });
    expect(transition(arming, { type: "CAPTURE_CANCELED", resume: true })).toEqual(listening);
    expect(transition(arming, { type: "CAPTURE_CANCELED", resume: false })).toEqual(idle);
  });

  it("submits a capture into processing", () => {
    const capture = transition(transition(idle, { type: "READY" }), { type: "MANUAL_ACTIVATE" });
    expect(transition(capture, { type: "CAPTURE_SUBMITTED" })).toEqual({
      state: "PROCESSING", waitingForTts: false, waitingForCooldown: false,
    });
  });

  it("waits through approval TTS and cooldown before listening again", () => {
    const processing: WakeMachine = { state: "PROCESSING", waitingForTts: false, waitingForCooldown: false };
    const tts = transition(processing, { type: "RESPONSE_BOUNDARY", ttsPlaying: true });
    expect(tts).toEqual({ ...processing, waitingForTts: true });
    const cooldown = transition(tts, { type: "TTS_ENDED" });
    expect(cooldown).toEqual({ ...processing, waitingForCooldown: true });
    expect(transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: false })).toEqual({
      state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false,
    });
  });

  // Issue #343 mở cửa sổ nghe tiếp sau lượt có `hasMoreToRead`. Từ 29/08 (spec
  // `docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md`) cờ ấy đổi
  // thành `keepListening` — do BACKEND tính từ kết cục cuối của lượt.
  //
  // Đổi tên chứ không giữ, vì hai thứ khác nghĩa hẳn: `hasMoreToRead` nói "còn đoạn sổ
  // tay chưa đọc", `keepListening` nói "hội thoại đang chạy, cứ nghe tiếp". Giữ tên cũ
  // cho một nghĩa mới là đúng cách để test xanh mà bảo vệ nhầm thứ.
  describe("FOLLOW_UP_WINDOW — cửa sổ nghe tiếp khi backend bảo còn nghe", () => {
    const cooldown: WakeMachine = { state: "PROCESSING", waitingForTts: false, waitingForCooldown: true };

    it("keepListening=true ⇒ vào FOLLOW_UP_WINDOW thay vì LISTENING_FOR_WAKEWORD", () => {
      expect(transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: true })).toEqual({
        state: "FOLLOW_UP_WINDOW", waitingForTts: false, waitingForCooldown: false,
      });
    });

    it("keepListening=false ⇒ về LISTENING_FOR_WAKEWORD, đòi gọi tên lại", () => {
      expect(transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: false })).toEqual({
        state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false,
      });
    });

    it("nghe được tiếng nói ⇒ CAPTURING_COMMAND thẳng, không qua ARMING (không beep)", () => {
      const followUp = transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: true });
      expect(transition(followUp, { type: "FOLLOW_UP_SPEECH_DETECTED" })).toEqual({
        state: "CAPTURING_COMMAND", waitingForTts: false, waitingForCooldown: false,
      });
    });

    it("hết giờ mà không ai nói ⇒ về LISTENING_FOR_WAKEWORD", () => {
      const followUp = transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: true });
      expect(transition(followUp, { type: "FOLLOW_UP_TIMEOUT" })).toEqual({
        state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false,
      });
    });

    it("bị huỷ giữa chừng (đóng overlay) ⇒ cùng ngữ nghĩa CAPTURE_CANCELED như ARMING/CAPTURING_COMMAND", () => {
      const followUp = transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: true });
      expect(transition(followUp, { type: "CAPTURE_CANCELED", resume: true })).toEqual({
        state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false,
      });
      expect(transition(followUp, { type: "CAPTURE_CANCELED", resume: false })).toEqual({
        state: "IDLE", waitingForTts: false, waitingForCooldown: false,
      });
    });

    it("bỏ qua trigger lạ (BEEP_FIRED/WAKE_DETECTED) khi đang ở FOLLOW_UP_WINDOW", () => {
      const followUp = transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: true });
      expect(transition(followUp, { type: "WAKE_DETECTED" })).toBe(followUp);
      expect(transition(followUp, { type: "BEEP_FIRED" })).toBe(followUp);
    });
  });

  it("disables from every state, including arming, and keeps canceled manual capture idle when not resuming", () => {
    const states: WakeMachine[] = [
      idle,
      { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false },
      { state: "ARMING", waitingForTts: false, waitingForCooldown: false },
      { state: "CAPTURING_COMMAND", waitingForTts: false, waitingForCooldown: false },
      { state: "PROCESSING", waitingForTts: true, waitingForCooldown: false },
      { state: "FOLLOW_UP_WINDOW", waitingForTts: false, waitingForCooldown: false },
    ];
    for (const state of states) expect(transition(state, { type: "DISABLE" })).toEqual(idle);
    const manual = transition(states[1], { type: "MANUAL_ACTIVATE" });
    expect(transition(manual, { type: "CAPTURE_CANCELED", resume: false })).toEqual(idle);
  });
});

/**
 * Ngữ nghĩa mới của cờ, viết riêng để nó không lẫn vào bảng chuyển trạng thái.
 *
 * Bảng này cố ý **không** đếm lượt nối và không biết đồng hồ: nó là một hàm thuần. Cả hai
 * nửa của ngân sách cứng (spec §3.2 — số lượt nối và trần đồng hồ tường) nằm ở
 * `WakeWordController`, nơi đã giữ timer. Gộp một bộ đếm vào đây là bắt mọi test bảng
 * dựng thêm một field không liên quan tới điều chúng đang kiểm.
 */
describe("keepListening là quyết định của backend, không phải của FE", () => {
  const cooldown: WakeMachine = { state: "PROCESSING", waitingForTts: false, waitingForCooldown: true };

  it("bảng chuyển KHÔNG tự quyết gì — nó chỉ đi theo cờ được truyền vào", () => {
    expect(transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: true }).state).toBe("FOLLOW_UP_WINDOW");
    expect(transition(cooldown, { type: "COOLDOWN_ELAPSED", keepListening: false }).state).toBe("LISTENING_FOR_WAKEWORD");
  });

  it("COOLDOWN_ELAPSED không có tác dụng khi chưa tới lượt chờ cooldown", () => {
    const dangDoiTts: WakeMachine = { state: "PROCESSING", waitingForTts: true, waitingForCooldown: false };
    expect(transition(dangDoiTts, { type: "COOLDOWN_ELAPSED", keepListening: true })).toBe(dangDoiTts);
  });
});
