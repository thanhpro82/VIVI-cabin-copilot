import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCKED_UI_POLICY } from "./types";
import type { DriverEvent } from "./types";

const UNLOCKED_UI_POLICY_WIRE = {
  allow_text_input: true,
  lock_small_controls: false,
  enlarge_mic_button: false,
  max_visible_actions: 6,
  prefer_voice_confirmation: false,
  allow_detailed_document_browsing: true,
};

/**
 * Test cho `realTurnService.subscribe()` — cơ chế reconnect + replay cursor
 * (xem docs/tasks/TASK-FE-BE-003 mục 1.2). Không có server thật nên tự dựng
 * `FakeWebSocket` giả lập đúng phần API `real.ts` dùng (`addEventListener`,
 * `send`, `close`) — đủ để lái kịch bản open/message/close mà không cần
 * network thật.
 */

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly protocols: string[];
  sent: string[] = [];
  private listeners: Record<string, ((ev: { data?: string }) => void)[]> = {};

  constructor(url: string, protocols: string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, cb: (ev: { data?: string }) => void) {
    (this.listeners[type] ??= []).push(cb);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.emitClose();
  }

  // --- Trợ giúp giả lập server phía test ---

  emitOpen() {
    for (const cb of this.listeners.open ?? []) cb({});
  }

  emitMessage(payload: unknown) {
    for (const cb of this.listeners.message ?? []) cb({ data: JSON.stringify(payload) });
  }

  /** Server-side/network close — không phải do client tự gọi .close().
   *
   * `code` mặc định `undefined` để giữ nguyên ý nghĩa "rớt mạng" của các test
   * cũ; truyền `4401`/`4403` khi muốn giả lập server từ chối vì token/quyền. */
  emitClose(code?: number) {
    for (const cb of this.listeners.close ?? []) cb({ code } as { data?: string });
  }

  lastSentInit(): Record<string, unknown> {
    const raw = this.sent.at(-1);
    if (!raw) throw new Error("chưa gửi connection.init nào");
    return JSON.parse(raw) as Record<string, unknown>;
  }
}

const STORED_SESSION = {
  accessToken: "tok-abc",
  tokenType: "Bearer",
  expiresAt: "2099-01-01T00:00:00Z",
  user: { userId: "usr_driver_01", role: "driver" as const, displayName: "Demo Driver" },
};

const DRIVER_SESSION = {
  sessionId: "ses_test_1",
  vehicleId: "vehicle-demo-01",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
};

vi.mock("../session", () => ({
  sessionService: {
    getStoredSession: vi.fn(() => STORED_SESSION),
    getCurrentDriverSession: vi.fn(() => DRIVER_SESSION),
  },
}));

// Giữ `isAuthFailureCode` thật (nó chỉ so mã lỗi), chỉ theo dõi lời gọi báo lỗi.
const reportAuthFailure = vi.fn();
vi.mock("../shared/authFailure", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../shared/authFailure")>()),
  reportAuthFailure: (message: string) => reportAuthFailure(message),
}));

async function freshRealTurnService() {
  vi.resetModules();
  const mod = await import("./real");
  return mod.realTurnService;
}

describe("realTurnService.subscribe()", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    reportAuthFailure.mockClear();
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("tự reconnect (mở WebSocket mới) sau khi socket rớt bất ngờ", async () => {
    const service = await freshRealTurnService();
    service.subscribe(() => {});

    expect(FakeWebSocket.instances).toHaveLength(1);
    const first = FakeWebSocket.instances[0];
    first.emitOpen();

    // Server/network rớt kết nối — không phải unsubscribe của client.
    first.emitClose();

    // Chưa reconnect ngay — có backoff (1s cho lần đầu).
    expect(FakeWebSocket.instances).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(1000);

    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("gửi last_event_id/last_sequence trong connection.init khi reconnect", async () => {
    const service = await freshRealTurnService();
    const events: DriverEvent[] = [];
    service.subscribe((e) => events.push(e));

    const first = FakeWebSocket.instances[0];
    first.emitOpen();

    // Lần đầu connect KHÔNG kèm cursor (chưa có event nào).
    expect(first.lastSentInit()).not.toHaveProperty("last_event_id");

    // Server phát 1 event có event_id/sequence trước khi rớt kết nối.
    first.emitMessage({
      type: "turn.completed",
      event_id: "evt_00000000000000000001",
      sequence: 7,
      turn_id: "turn_1",
      trace_id: "tr_1",
      payload: {},
    });
    expect(events).toContainEqual({ type: "turn.completed", turnId: "turn_1" });

    first.emitClose();
    await vi.advanceTimersByTimeAsync(1000);

    expect(FakeWebSocket.instances).toHaveLength(2);
    const second = FakeWebSocket.instances[1];
    second.emitOpen();

    expect(second.lastSentInit()).toMatchObject({
      last_event_id: "evt_00000000000000000001",
      last_sequence: 7,
    });
  });

  it("REPLAY_CURSOR_INVALID xoá cursor và reconnect lại từ đầu (không kèm cursor)", async () => {
    const service = await freshRealTurnService();
    service.subscribe(() => {});

    const first = FakeWebSocket.instances[0];
    first.emitOpen();
    first.emitMessage({
      type: "turn.completed",
      event_id: "evt_1",
      sequence: 1,
      turn_id: "turn_1",
      trace_id: "tr_1",
      payload: {},
    });

    // Server phát lỗi cursor rồi tự đóng socket (đúng hành vi thật của BE —
    // xem src/api/ws.py: gửi "error" terminal rồi close(code=1003)).
    first.emitMessage({
      type: "error",
      event_id: "evt_2",
      sequence: 2,
      payload: { code: "REPLAY_CURSOR_INVALID", message: "...", retryable: false, terminal: true, details: {} },
    });
    first.emitClose();

    await vi.advanceTimersByTimeAsync(1000);

    expect(FakeWebSocket.instances).toHaveLength(2);
    const second = FakeWebSocket.instances[1];
    second.emitOpen();

    expect(second.lastSentInit()).not.toHaveProperty("last_event_id");
    expect(second.lastSentInit()).not.toHaveProperty("last_sequence");
  });

  it("REPLAY_WINDOW_EXPIRED cũng xoá cursor và reconnect lại từ đầu", async () => {
    const service = await freshRealTurnService();
    service.subscribe(() => {});

    const first = FakeWebSocket.instances[0];
    first.emitOpen();
    first.emitMessage({
      type: "turn.completed",
      event_id: "evt_1",
      sequence: 1,
      turn_id: "turn_1",
      trace_id: "tr_1",
      payload: {},
    });
    first.emitMessage({
      type: "error",
      payload: { code: "REPLAY_WINDOW_EXPIRED", message: "...", retryable: true, terminal: true, details: {} },
    });
    first.emitClose();

    await vi.advanceTimersByTimeAsync(1000);

    const second = FakeWebSocket.instances[1];
    second.emitOpen();
    expect(second.lastSentInit()).not.toHaveProperty("last_event_id");
  });

  it("lỗi xác thực terminal (AUTH_REQUIRED/FORBIDDEN) dừng hẳn, không reconnect nữa", async () => {
    const service = await freshRealTurnService();
    const events: DriverEvent[] = [];
    service.subscribe((e) => events.push(e));

    const first = FakeWebSocket.instances[0];
    first.emitOpen();
    first.emitMessage({
      type: "error",
      payload: { code: "AUTH_REQUIRED", message: "token hết hạn", retryable: false, terminal: true, details: {} },
    });
    first.emitClose();

    // Báo lỗi cho UI qua onEvent — case "error" vẫn map bình thường.
    expect(events).toContainEqual({
      type: "error",
      code: "AUTH_REQUIRED",
      message: "token hết hạn",
      retryable: false,
    });

    // Cho thời gian trôi qua rất xa (nhiều lần backoff tối đa) — vẫn không
    // được tạo thêm WebSocket nào, vì `stopped = true` chặn scheduleReconnect.
    await vi.advanceTimersByTimeAsync(60_000);

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("lỗi xác thực terminal cũng fail-closed: policy đang mở → AUTH_REQUIRED/FORBIDDEN → khoá ngay, không reconnect (PM/PO review PR #100, blocker thứ 2)", async () => {
    const service = await freshRealTurnService();
    const events: DriverEvent[] = [];
    service.subscribe((e) => events.push(e));

    const first = FakeWebSocket.instances[0];
    first.emitOpen();

    // Policy đang MỞ trước khi lỗi xác thực xảy ra.
    first.emitMessage({
      type: "ui.policy",
      event_id: "evt_1",
      sequence: 1,
      payload: { ui_policy: UNLOCKED_UI_POLICY_WIRE },
    });
    expect(events.at(-1)).toMatchObject({ type: "ui.policy", uiPolicy: { lockSmallControls: false } });

    // Server báo lỗi xác thực terminal RỒI tự đóng socket (đúng thứ tự thật:
    // message "error" trước, "close" theo ngay sau) — đây là ca trước đây bị
    // bỏ sót: handler "close" tự return sớm vì `stopped` đã true, nên khoá
    // phải xảy ra ở message handler, không phải chờ tới close.
    //
    // Trong CÙNG message handler, code phát "ui.policy" (khoá) TRƯỚC rồi mới
    // phát tiếp "error" đã map từ chính message đó (thứ tự đúng như code chạy
    // trong real.ts) — nên event khoá là event áp CHÓT, không phải cuối cùng.
    first.emitMessage({
      type: "error",
      payload: { code: "AUTH_REQUIRED", message: "token hết hạn", retryable: false, terminal: true, details: {} },
    });
    expect(events.at(-2)).toEqual({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });
    expect(events.at(-1)).toEqual({
      type: "error",
      code: "AUTH_REQUIRED",
      message: "token hết hạn",
      retryable: false,
    });

    first.emitClose();

    // Không reconnect sau lỗi xác thực (giữ đúng hành vi cũ) — và không có
    // sự kiện ui.policy nào khác phát thêm sau close (đã khoá đủ ở message).
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(events.filter((e) => e.type === "ui.policy")).toHaveLength(2);
  });

  it("close code 4401 dừng hẳn và báo hết phiên, không reconnect (không phụ thuộc frame error)", async () => {
    // Nhánh terminal-error chỉ chạy khi server kịp gửi frame trước khi đóng.
    // Handshake bị từ chối (token chết) thì thứ duy nhất tới nơi là close code —
    // trước đây `close` handler không nhận `event` nên ca này rơi vào đúng nhánh
    // "rớt mạng": reconnect 8 giây/lần, vĩnh viễn, với đúng token đã chết.
    const service = await freshRealTurnService();
    const events: DriverEvent[] = [];
    service.subscribe((e) => events.push(e));

    const first = FakeWebSocket.instances[0];
    first.emitOpen();
    first.emitClose(4401);

    expect(events.at(-1)).toEqual({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });
    expect(reportAuthFailure).toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("close code 4403 (sai vai/Origin) dừng hẳn nhưng KHÔNG đăng xuất", async () => {
    // Hai nửa tách rời nhau, và đây là chỗ chúng từng bị gộp. Dừng reconnect thì
    // đúng — 4403 lặp lại y hệt sau mỗi 8 giây. Nhưng đăng xuất thì sai: `ws.py`
    // đóng 4403 khi sai role HOẶC Origin không nằm trong `cors_origins`, cả hai đều
    // là lỗi cấu hình với một token còn sống nguyên. Xoá phiên vừa không sửa được
    // gì, vừa giấu mất nguyên nhân thật (PM/PO review PR #157).
    const service = await freshRealTurnService();
    const events: DriverEvent[] = [];
    service.subscribe((e) => events.push(e));

    FakeWebSocket.instances[0].emitOpen();
    FakeWebSocket.instances[0].emitClose(4403);

    // Vẫn fail-closed ở tầng UI — không suy luận policy khi không chắc chắn.
    expect(events.at(-1)).toEqual({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });

    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(reportAuthFailure).not.toHaveBeenCalled();
  });

  it("mất WS fail-closed: policy đang mở → close → khoá lại ngay → mở lại đúng theo policy mới sau reconnect (PM/PO review PR #100)", async () => {
    const service = await freshRealTurnService();
    const events: DriverEvent[] = [];
    service.subscribe((e) => events.push(e));

    const first = FakeWebSocket.instances[0];
    first.emitOpen();

    // Server phát policy MỞ (xe đứng yên) — trạng thái trước khi mất kết nối.
    first.emitMessage({
      type: "ui.policy",
      event_id: "evt_1",
      sequence: 1,
      payload: { ui_policy: UNLOCKED_UI_POLICY_WIRE },
    });
    expect(events.at(-1)).toEqual({
      type: "ui.policy",
      uiPolicy: {
        allowTextInput: true,
        lockSmallControls: false,
        enlargeMicButton: false,
        maxVisibleActions: 6,
        preferVoiceConfirmation: false,
        allowDetailedDocumentBrowsing: true,
        controlsLocked: false,
      },
    });

    // Rớt kết nối bất ngờ (không phải unsubscribe) — phải khoá lại NGAY, không
    // đợi reconnect xong mới khoá, và không giữ nguyên policy MỞ cũ.
    first.emitClose();
    expect(events.at(-1)).toEqual({ type: "ui.policy", uiPolicy: LOCKED_UI_POLICY });

    // Reconnect xong, server phát lại policy MỞ — phải nhận đúng policy mới,
    // không bị kẹt ở LOCKED_UI_POLICY vĩnh viễn sau khi đã hồi phục.
    await vi.advanceTimersByTimeAsync(1000);
    const second = FakeWebSocket.instances[1];
    second.emitOpen();
    second.emitMessage({
      type: "ui.policy",
      event_id: "evt_2",
      sequence: 2,
      payload: { ui_policy: UNLOCKED_UI_POLICY_WIRE },
    });
    expect(events.at(-1)).toEqual({
      type: "ui.policy",
      uiPolicy: {
        allowTextInput: true,
        lockSmallControls: false,
        enlargeMicButton: false,
        maxVisibleActions: 6,
        preferVoiceConfirmation: false,
        allowDetailedDocumentBrowsing: true,
        controlsLocked: false,
      },
    });
  });

  it("unsubscribe() (trả về từ subscribe) dừng reconnect và đóng socket hiện tại", async () => {
    const service = await freshRealTurnService();
    const unsubscribe = service.subscribe(() => {});

    const first = FakeWebSocket.instances[0];
    first.emitOpen();

    unsubscribe();

    // .close() của client → close event bắn ra, nhưng KHÔNG được reconnect
    // vì stopped đã true trước khi close() chạy.
    await vi.advanceTimersByTimeAsync(60_000);

    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
