export type WakeState =
  | "IDLE"
  | "LISTENING_FOR_WAKEWORD"
  | "ARMING"
  | "CAPTURING_COMMAND"
  | "PROCESSING"
  | "FOLLOW_UP_WINDOW";

export type WakeEvent =
  | { type: "READY" }
  | { type: "WAKE_DETECTED" }
  | { type: "MANUAL_ACTIVATE" }
  | { type: "BEEP_FIRED" }
  | { type: "CAPTURE_SUBMITTED" }
  | { type: "CAPTURE_CANCELED"; resume: boolean }
  | { type: "RESPONSE_BOUNDARY"; ttsPlaying: boolean }
  | { type: "TTS_ENDED" }
  /**
   * Backend có bảo **còn nghe tiếp** không — quyết định LISTENING_FOR_WAKEWORD hay
   * FOLLOW_UP_WINDOW.
   *
   * Thay `hasMoreToRead` của #343 từ 29/08 (spec
   * `docs/superpowers/specs/2026-08-29-cua-so-nghe-tiep-mo-sau-moi-luot.md` §3.1). Đổi
   * tên chứ không giữ, vì hai thứ khác nghĩa hẳn: `hasMoreToRead` nói *"còn đoạn sổ tay
   * chưa đọc"*, `keepListening` nói *"hội thoại đang chạy, cứ nghe tiếp"*. Giữ tên cũ cho
   * một nghĩa mới là đúng cách để một test xanh mà bảo vệ nhầm thứ.
   *
   * Quyết định nằm ở **backend** (`src/agents/nghe_tiep.py`) vì FE chỉ nghe thấy *tiếng*
   * — nó không phân biệt được "mức 2" với "lát nữa mở cốp lấy đồ nhé".
   */
  | { type: "COOLDOWN_ELAPSED"; keepListening: boolean }
  /** Nghe được tiếng nói trong cửa sổ nghe tiếp — vào thẳng CAPTURING_COMMAND, không cần "Hey Vi Vi". */
  | { type: "FOLLOW_UP_SPEECH_DETECTED" }
  /** Hết `FOLLOW_UP_WINDOW_MS` mà không ai nói. */
  | { type: "FOLLOW_UP_TIMEOUT" }
  | { type: "DISABLE" };

export interface WakeMachine {
  state: WakeState;
  waitingForTts: boolean;
  waitingForCooldown: boolean;
}

export function transition(machine: WakeMachine, event: WakeEvent): WakeMachine {
  if (event.type === "DISABLE") return { state: "IDLE", waitingForTts: false, waitingForCooldown: false };
  switch (machine.state) {
    case "IDLE":
      return event.type === "READY" ? { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false } : machine;
    case "LISTENING_FOR_WAKEWORD":
      if (event.type === "WAKE_DETECTED") return { state: "ARMING", waitingForTts: false, waitingForCooldown: false };
      if (event.type === "MANUAL_ACTIVATE") return { state: "CAPTURING_COMMAND", waitingForTts: false, waitingForCooldown: false };
      return machine;
    case "ARMING":
      if (event.type === "BEEP_FIRED") return { state: "CAPTURING_COMMAND", waitingForTts: false, waitingForCooldown: false };
      if (event.type === "CAPTURE_CANCELED") return { state: event.resume ? "LISTENING_FOR_WAKEWORD" : "IDLE", waitingForTts: false, waitingForCooldown: false };
      return machine;
    case "CAPTURING_COMMAND":
      if (event.type === "CAPTURE_SUBMITTED") return { state: "PROCESSING", waitingForTts: false, waitingForCooldown: false };
      if (event.type === "CAPTURE_CANCELED") return { state: event.resume ? "LISTENING_FOR_WAKEWORD" : "IDLE", waitingForTts: false, waitingForCooldown: false };
      return machine;
    case "PROCESSING":
      if (event.type === "RESPONSE_BOUNDARY") return { ...machine, waitingForTts: event.ttsPlaying, waitingForCooldown: !event.ttsPlaying };
      if (event.type === "TTS_ENDED" && machine.waitingForTts) return { ...machine, waitingForTts: false, waitingForCooldown: true };
      if (event.type === "COOLDOWN_ELAPSED" && machine.waitingForCooldown) {
        // Bảng này cố ý KHÔNG đếm lượt nối và không biết đồng hồ — nó là một hàm
        // thuần. Cả hai nửa của ngân sách cứng (spec §3.2) nằm ở `WakeWordController`,
        // nơi đã giữ timer, và chúng gộp vào chính cờ `keepListening` truyền xuống đây.
        return { state: event.keepListening ? "FOLLOW_UP_WINDOW" : "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false };
      }
      return machine;
    case "FOLLOW_UP_WINDOW":
      if (event.type === "FOLLOW_UP_SPEECH_DETECTED") return { state: "CAPTURING_COMMAND", waitingForTts: false, waitingForCooldown: false };
      if (event.type === "FOLLOW_UP_TIMEOUT") return { state: "LISTENING_FOR_WAKEWORD", waitingForTts: false, waitingForCooldown: false };
      if (event.type === "CAPTURE_CANCELED") return { state: event.resume ? "LISTENING_FOR_WAKEWORD" : "IDLE", waitingForTts: false, waitingForCooldown: false };
      return machine;
  }
}
