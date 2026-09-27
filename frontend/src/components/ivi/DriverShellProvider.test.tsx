// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

vi.mock("@/lib/audio/wavRecorder", () => ({
  startWavRecording: vi.fn(),
}));

const { startWavRecording } = await import("@/lib/audio/wavRecorder");

/**
 * Test cho race điều kiện đã sửa ở TASK-FE-BE-003 mục 1.1: `send()` phải đợi
 * `createDriverSession()` hoàn tất rồi mới gọi `turnService.sendText()` —
 * trước fix, bấm nút trước khi round-trip HTTP tạo session xong khiến lệnh
 * bị nuốt lỗi (throw "Chưa có session...") mà người dùng không biết vì sao.
 */

vi.mock("@/lib/services/session", () => ({
  sessionService: {
    getCurrentDriverSession: vi.fn(),
    createDriverSession: vi.fn(),
    getStoredSession: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("@/lib/services/turn", () => ({
  turnService: {
    getVehicleState: vi.fn(),
    sendText: vi.fn(),
    sendVoice: vi.fn(),
    decideApproval: vi.fn(),
    getCitation: vi.fn(),
    subscribe: vi.fn(),
  },
}));

const { sessionService } = await import("@/lib/services/session");
const { turnService } = await import("@/lib/services/turn");

const DRIVER_SESSION = {
  sessionId: "ses_test_1",
  vehicleId: "vehicle-demo-01",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
  canDrive: true,
  pool: null,
};

function TestConsumer() {
  const { send, pending } = useDriverShell();
  return (
    <button type="button" onClick={() => send("bật điều hòa")} data-pending={pending}>
      go
    </button>
  );
}

describe("DriverShellProvider.send()", () => {
  beforeEach(() => {
    vi.mocked(turnService.getVehicleState).mockResolvedValue({
      vehicleId: "vehicle-demo-01",
      stateVersion: 1,
      observedAt: "2026-01-01T00:00:00Z",
      motion: { speedKph: 0, gear: "P", ignition: "ON" },
      hvac: { power: false, temperatureC: 24, fanLevel: 0 },
      windows: { frontLeft: 0, frontRight: 0, rearLeft: 0, rearRight: 0 },
      doors: { frontLeft: "closed", frontRight: "closed", rearLeft: "closed", rearRight: "closed" },
      media: { status: "stopped", volume: 30, track: null },
      navigation: { status: "idle", destinationId: null },
      seat: {
        frontLeft: { heating: 0, foreAft: 50, recline: 50, height: 50 },
        frontRight: { heating: 0, foreAft: 50, recline: 50, height: 50 },
      },
      lights: { headlight: "auto", interior: false },
      trunk: { position: "closed" },
    });
    // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
    // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
    // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
    // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "turn_1" });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("KHÔNG gọi sendText() trong lúc createDriverSession() còn đang chờ — và lượt bấm đó bị BỎ, không xếp hàng", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(null);
    let resolveCreateSession!: (session: typeof DRIVER_SESSION) => void;
    vi.mocked(sessionService.createDriverSession).mockReturnValue(
      new Promise((resolve) => {
        resolveCreateSession = resolve;
      }),
    );

    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );

    const button = screen.getByText("go");
    act(() => button.click());

    // Session round-trip chưa xong — sendText() chưa được phép gọi.
    expect(turnService.sendText).not.toHaveBeenCalled();

    await act(async () => {
      resolveCreateSession(DRIVER_SESSION);
      // Nhường control cho chain .then() trong bootstrap()/send() chạy hết.
      await Promise.resolve();
      await Promise.resolve();
    });

    // Kể từ issue #241 (PM/PO review PR #246) lượt bấm lúc CHƯA xác nhận kết
    // nối bị BỎ hẳn, không xếp hàng chờ `sessionReadyRef` như trước: lúc bấm,
    // FE chưa có bằng chứng nào là backend còn sống, nên gửi đi là đúng cái
    // UAT-008 cấm. Tài xế đã nhận toast và bấm lại — chứ không phải lệnh tự
    // bay đi vài trăm mili-giây sau, khi họ không còn nhìn nữa.
    expect(turnService.sendText).not.toHaveBeenCalled();

    // Bấm lại sau khi `subscribe()` đã phát `ui.policy` (bootstrap xong) thì gửi.
    act(() => screen.getByText("go").click());
    await waitFor(() => {
      expect(turnService.sendText).toHaveBeenCalledWith("bật điều hòa");
    });
  });

  it("session đã có sẵn (không cần tạo mới) thì gọi sendText() ngay, không phải đợi", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);

    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );

    // Để bootstrap() (vẫn async dù không cần tạo session) chạy xong trước khi bấm.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const button = screen.getByText("go");
    act(() => button.click());

    await waitFor(() => {
      expect(turnService.sendText).toHaveBeenCalledWith("bật điều hòa");
    });
    expect(sessionService.createDriverSession).not.toHaveBeenCalled();
  });
});

const ROUTINE_PREVIEW = {
  routineId: "rtn_ve_nha",
  routineName: "Về nhà",
  steps: [{ index: 0, action: "navigation", description: "dẫn đường tới Nhà" }],
};

function PreviewConsumer() {
  const { activeView, setActiveView, routinePreview, send } = useDriverShell();
  return (
    <div>
      <span data-testid="preview-view">{activeView}</span>
      <span data-testid="preview-name">{routinePreview?.preview.routineName ?? ""}</span>
      <button type="button" onClick={() => send("Xem trước Routine Về nhà")}>preview</button>
      <button type="button" onClick={() => setActiveView("home")}>home</button>
    </div>
  );
}

describe("DriverShellProvider — Routine preview có cấu trúc", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "turn_preview", routinePreview: ROUTINE_PREVIEW });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("assistant.response qua WebSocket mở màn Routines và lưu preview", async () => {
    render(<DriverShellProvider><PreviewConsumer /></DriverShellProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    act(() => emit({
      type: "assistant.response",
      turnId: "turn_ws",
      result: {
        displayText: "Xem trước",
        speakText: "Xem trước",
        citations: [],
        outcomes: [],
        hasMoreToRead: false,
        moMicNgan: false,
        routinePreview: ROUTINE_PREVIEW,
      },
    }));

    expect(screen.getByTestId("preview-view").textContent).toBe("routines");
    expect(screen.getByTestId("preview-name").textContent).toBe("Về nhà");
  });

  it("response REST của lệnh chữ mở màn Routines kể cả khi WS chưa tới", async () => {
    render(<DriverShellProvider><PreviewConsumer /></DriverShellProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    act(() => screen.getByText("preview").click());

    await waitFor(() => expect(screen.getByTestId("preview-view").textContent).toBe("routines"));
    expect(screen.getByTestId("preview-name").textContent).toBe("Về nhà");
  });

  it("replay cùng turnId không kéo người dùng trở lại màn Routines", async () => {
    render(<DriverShellProvider><PreviewConsumer /></DriverShellProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const event: DriverEvent = {
      type: "assistant.response",
      turnId: "turn_same",
      result: {
        displayText: "Xem trước",
        speakText: "Xem trước",
        citations: [],
        outcomes: [],
        hasMoreToRead: false,
        moMicNgan: false,
        routinePreview: ROUTINE_PREVIEW,
      },
    };

    act(() => emit(event));
    expect(screen.getByTestId("preview-view").textContent).toBe("routines");
    act(() => screen.getByText("home").click());
    act(() => emit(event));

    expect(screen.getByTestId("preview-view").textContent).toBe("home");
  });
});

const ROUTINE_SETUP_REQUIRED = { routineId: "rtn_di_lam", maLoi: "chua_dat_dia_diem", thieu: ["office"] };

function SetupRequiredConsumer() {
  const { activeView, setActiveView, routineSetupRequired, send } = useDriverShell();
  return (
    <div>
      <span data-testid="setup-view">{activeView}</span>
      <span data-testid="setup-thieu">{routineSetupRequired?.setup.thieu.join(",") ?? ""}</span>
      <button type="button" onClick={() => send("Chạy Routine Đi làm")}>run</button>
      <button type="button" onClick={() => setActiveView("home")}>home</button>
    </div>
  );
}

describe("DriverShellProvider — Routine setup-required (#385)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
    vi.mocked(turnService.sendText).mockResolvedValue({
      turnId: "turn_setup",
      routineSetupRequired: ROUTINE_SETUP_REQUIRED,
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("assistant.response qua WebSocket mở màn Routines và lưu tín hiệu thiếu địa điểm", async () => {
    render(<DriverShellProvider><SetupRequiredConsumer /></DriverShellProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    act(() => emit({
      type: "assistant.response",
      turnId: "turn_ws",
      result: {
        displayText: "Chưa đặt địa điểm Cơ quan nên chưa chạy được Routine này.",
        speakText: "Chưa đặt địa điểm Cơ quan nên chưa chạy được Routine này.",
        citations: [],
        outcomes: [],
        hasMoreToRead: false,
        moMicNgan: false,
        routineSetupRequired: ROUTINE_SETUP_REQUIRED,
      },
    }));

    expect(screen.getByTestId("setup-view").textContent).toBe("routines");
    expect(screen.getByTestId("setup-thieu").textContent).toBe("office");
  });

  it("response REST của lệnh chữ mở màn Routines kể cả khi WS chưa tới", async () => {
    render(<DriverShellProvider><SetupRequiredConsumer /></DriverShellProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });

    act(() => screen.getByText("run").click());

    await waitFor(() => expect(screen.getByTestId("setup-view").textContent).toBe("routines"));
    expect(screen.getByTestId("setup-thieu").textContent).toBe("office");
  });

  it("replay cùng turnId không kéo người dùng trở lại màn Routines", async () => {
    render(<DriverShellProvider><SetupRequiredConsumer /></DriverShellProvider>);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const event: DriverEvent = {
      type: "assistant.response",
      turnId: "turn_same",
      result: {
        displayText: "x",
        speakText: "x",
        citations: [],
        outcomes: [],
        hasMoreToRead: false,
        moMicNgan: false,
        routineSetupRequired: ROUTINE_SETUP_REQUIRED,
      },
    };

    act(() => emit(event));
    expect(screen.getByTestId("setup-view").textContent).toBe("routines");
    act(() => screen.getByText("home").click());
    act(() => emit(event));

    expect(screen.getByTestId("setup-view").textContent).toBe("home");
  });
});

/**
 * Test cho PM/PO review PR0 (điểm 1, phần "chạm dừng thủ công vẫn hoạt động,
 * timer không gửi lần hai") và điểm 2 (lượt mới không bị lượt cũ ghi đè UI).
 * VAD tự nó (RMS/im lặng thuần) đã test riêng ở wavRecorder.test.ts — ở đây
 * test tầng tích hợp: `startWavRecording()` được mock, tập trung vào hành vi
 * của `DriverShellProvider` xung quanh nó.
 */
function VoiceTestConsumer() {
  const { openVoice, stopVoice, send, lastTurn, voiceOpen, turnHistory, closeVoice, speaking, stopSpeaking } =
    useDriverShell();
  return (
    <div>
      <button type="button" onClick={openVoice} data-testid="open-voice">
        open
      </button>
      <button type="button" onClick={stopSpeaking} data-testid="stop-speaking">
        hush
      </button>
      <span data-testid="speaking">{String(speaking)}</span>
      <button type="button" onClick={stopVoice} data-testid="stop-voice">
        stop
      </button>
      <button type="button" onClick={() => send("bật điều hòa")} data-testid="send">
        send
      </button>
      <button type="button" onClick={closeVoice} data-testid="close-voice">
        close
      </button>
      <span data-testid="last-turn-vivi">{lastTurn?.vivi ?? ""}</span>
      <span data-testid="last-turn-citations">
        {(lastTurn?.citations ?? []).map((c) => c.citationId).join("|")}
      </span>
      <span data-testid="voice-open">{String(voiceOpen)}</span>
      <span data-testid="turn-history">{turnHistory.join("|")}</span>
    </div>
  );
}

const VEHICLE_STATE: VehicleState = {
  vehicleId: "vehicle-demo-01",
  stateVersion: 1,
  observedAt: "2026-01-01T00:00:00Z",
  motion: { speedKph: 0, gear: "P", ignition: "ON" },
  hvac: { power: false, temperatureC: 24, fanLevel: 0 },
  windows: { frontLeft: 0, frontRight: 0, rearLeft: 0, rearRight: 0 },
  doors: { frontLeft: "closed", frontRight: "closed", rearLeft: "closed", rearRight: "closed" },
  media: { status: "stopped", volume: 30, track: null },
  navigation: { status: "idle", destinationId: null },
  seat: {
    frontLeft: { heating: 0, foreAft: 50, recline: 50, height: 50 },
    frontRight: { heating: 0, foreAft: 50, recline: 50, height: 50 },
  },
  lights: { headlight: "auto", interior: false },
  trunk: { position: "closed" },
};

describe("DriverShellProvider — dừng ghi âm (VAD/thủ công)", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
    // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
    // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
    // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  it("chạm dừng thủ công gửi WAV lên BE; gọi dừng lần 2 (vd timer/VAD tới muộn) không gửi lần hai", async () => {
    const recorder = {
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    };
    vi.mocked(startWavRecording).mockResolvedValue(recorder);
    vi.mocked(turnService.sendVoice).mockResolvedValue({ turnId: "turn_voice_1" });

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    await waitFor(() => expect(startWavRecording).toHaveBeenCalled());
    await act(async () => {
      await Promise.resolve();
    });

    // Chạm dừng lần 1 — thủ công.
    await act(async () => {
      screen.getByTestId("stop-voice").click();
      await Promise.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(turnService.sendVoice).toHaveBeenCalledTimes(1));

    // Chạm/gọi dừng lần 2 (mô phỏng timer 12s hoặc VAD tới muộn sau khi đã
    // dừng thủ công) — recorderRef đã null nên phải no-op, không gửi lại.
    await act(async () => {
      screen.getByTestId("stop-voice").click();
      await Promise.resolve();
    });
    expect(turnService.sendVoice).toHaveBeenCalledTimes(1);
    expect(recorder.stop).toHaveBeenCalledTimes(1);
  });

  it("ghi chỉ toàn im lặng/ồn nền (hadSpeech() false) — không gọi sendVoice, báo 'chưa nghe rõ'", async () => {
    const recorder = {
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => false,
    };
    vi.mocked(startWavRecording).mockResolvedValue(recorder);

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    await waitFor(() => expect(startWavRecording).toHaveBeenCalled());
    await act(async () => {
      await Promise.resolve();
    });

    await act(async () => {
      screen.getByTestId("stop-voice").click();
      await Promise.resolve();
    });

    expect(recorder.cancel).toHaveBeenCalledTimes(1);
    expect(recorder.stop).not.toHaveBeenCalled();
    expect(turnService.sendVoice).not.toHaveBeenCalled();
  });
});

describe("DriverShellProvider — lượt mới không bị lượt cũ ghi đè UI", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "t1" });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  /**
   * Trước issue #111, Provider chỉ giữ `displayText` và vứt mảng `citations`
   * của `assistant.response` — nên không có gì để `CitationList` hiển thị và cờ
   * `allowDetailedDocumentBrowsing` không có consumer nào.
   */
  it("giữ lại citations của assistant.response, không chỉ mỗi displayText", async () => {
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("send").click());
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: {
          displayText: "Áp suất lốp tiêu chuẩn là 2.4 bar.",
          speakText: "Áp suất lốp tiêu chuẩn là 2.4 bar.",
          citations: [
            { citationId: "cit_1", documentTitle: "Sổ tay VF9", section: "Lốp", page: 88, excerpt: "..." },
            { citationId: "cit_2", documentTitle: "Sổ tay VF9", section: "Bảo dưỡng", page: 91, excerpt: "..." },
          ],
          outcomes: [], hasMoreToRead: false,
          moMicNgan: false,
        },
      }),
    );
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });

    expect(screen.getByTestId("last-turn-citations").textContent).toBe("cit_1|cit_2");
  });

  it("lượt điều khiển không có trích dẫn thì mảng rỗng, không phải undefined", async () => {
    // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
    // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
    // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
    // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("send").click());

    expect(screen.getByTestId("last-turn-citations").textContent).toBe("");
  });

  it("assistant.response của lượt CŨ tới muộn (đang hoãn theo MIN_TRANSCRIPT_VISIBLE_MS) sau khi lượt MỚI đã bắt đầu — không ghi đè lastTurn", async () => {
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Lượt 1: gõ lệnh, transcript.final tới ngay (giả lập giống lượt qua
    // giọng nói) rồi assistant.response tới trong lúc transcript vừa hiện —
    // bị afterTranscriptHold hoãn ~3s vì elapsed ~0 < MIN_TRANSCRIPT_VISIBLE_MS.
    act(() => screen.getByTestId("send").click());
    act(() => emit({ type: "transcript.final", turnId: "t1", text: "bật điều hòa", confidence: 0.9 }));
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: { displayText: "Đã bật điều hòa.", speakText: "Đã bật điều hòa.", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );

    // Lượt 2 bắt đầu TRƯỚC KHI hoãn của lượt 1 chạy xong — turnGenerationRef
    // tăng, phải làm lượt 1 thành "cũ".
    act(() => screen.getByTestId("send").click());
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");

    // Hết thời gian hoãn của lượt 1 — timer cũ nổ nhưng phải bị bỏ qua
    // (generation không khớp nữa), KHÔNG được ghi "Đã bật điều hòa." đè lên
    // UI của lượt 2.
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");

    // Lượt 2 tới response riêng của nó — phải hiện đúng, không lẫn lượt 1.
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1b",
        result: { displayText: "Đã tắt điều hòa.", speakText: "Đã tắt điều hòa.", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã tắt điều hòa.");
  });
});

/**
 * Ngắt lời khi VIVI đang đọc (issue #106).
 *
 * Bối cảnh: `assistant.speech` từng tạo `new Audio(...).play()` rồi **thả trôi**
 * — không giữ tham chiếu nên không có cách nào gọi `pause()`. Một câu trả lời
 * sổ tay đo được **65,6 giây** và tài xế không có đường nào dừng.
 */
describe("DriverShellProvider — ngắt lời TTS", () => {
  class FakeAudio extends EventTarget {
    ended = false;
    error: MediaError | null = null;
    paused = false;
    play() {
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
  }
  const createdAudios: FakeAudio[] = [];
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    vi.useFakeTimers();
    createdAudios.length = 0;
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "t2" });
    vi.mocked(turnService.sendVoice).mockResolvedValue({ turnId: "t1" });
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    });
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.resetAllMocks();
    vi.unstubAllGlobals();
  });

  /** Mở overlay và cho VIVI bắt đầu đọc; trả về đúng audio đang phát. */
  async function startSpeaking() {
    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // Dừng ghi rồi mới tới lượt VIVI đọc — đúng thứ tự thật. Bỏ bước này thì
    // recorder còn sống và `openVoice()` lần sau tự no-op (chốt chặn gọi lặp),
    // tức test sẽ đo một tình huống không bao giờ xảy ra ngoài đời.
    act(() => screen.getByTestId("stop-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => emit({ type: "assistant.speech", turnId: "t1", audioBase64: "AAAA", mimeType: "audio/wav" }));
    await act(async () => {
      await Promise.resolve();
    });

    const audio = createdAudios.at(-1);
    if (!audio) throw new Error("không có audio nào được tạo");
    expect(audio.paused).toBe(false);
    expect(screen.getByTestId("speaking").textContent).toBe("true");
    return audio;
  }

  it("bấm mic khi đang đọc thì im ngay — bắt đầu nói là ý định ngắt lời", async () => {
    const audio = await startSpeaking();

    act(() => screen.getByTestId("open-voice").click());

    expect(audio.paused).toBe(true);
    expect(screen.getByTestId("speaking").textContent).toBe("false");
  });

  it("lượt mới bằng chữ cũng ngắt lời lượt cũ, không chồng giọng", async () => {
    const audio = await startSpeaking();

    act(() => screen.getByTestId("send").click());

    expect(audio.paused).toBe(true);
  });

  /**
   * `send()`/`openVoice()` chỉ ngắt lời cho lượt do CHÍNH máy này bắt đầu.
   * `turn.accepted` bắt cả lượt tới từ nơi khác trên cùng session.
   */
  it("turn.accepted từ server ngắt lời, kể cả lượt không do máy này bắt đầu", async () => {
    const audio = await startSpeaking();

    act(() => emit({ type: "turn.accepted", turnId: "t9", inputMode: "voice" }));

    expect(audio.paused).toBe(true);
    expect(screen.getByTestId("speaking").textContent).toBe("false");
  });

  /**
   * Regression: trước issue #106, đóng thẻ chỉ ẩn giao diện còn giọng vẫn đọc
   * tiếp tới hết — và lúc đó thẻ đã biến mất nên không còn gì để bấm dừng.
   */
  it("đóng thẻ khi đang đọc thì TẮT TIẾNG luôn, không để giọng chạy mồ côi", async () => {
    const audio = await startSpeaking();

    act(() => screen.getByTestId("close-voice").click());

    expect(audio.paused).toBe(true);
    expect(screen.getByTestId("speaking").textContent).toBe("false");
    expect(screen.getByTestId("voice-open").textContent).toBe("false");
  });

  it("nút Dừng đọc tắt tiếng nhưng GIỮ thẻ lại để còn đọc chữ", async () => {
    const audio = await startSpeaking();

    act(() => screen.getByTestId("stop-speaking").click());

    expect(audio.paused).toBe(true);
    expect(screen.getByTestId("speaking").textContent).toBe("false");
    expect(screen.getByTestId("voice-open").textContent).toBe("true");
  });

  /**
   * `pause()` không phát `ended`, nên nhánh "đóng theo audio" mất mốc của nó.
   * Không xử lý thì thẻ treo trên màn hình vĩnh viễn sau khi bấm Dừng đọc.
   */
  it("bấm Dừng đọc xong thẻ vẫn tự đóng sau CLOSE_AFTER_AUDIO_MS", async () => {
    await startSpeaking();
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: { displayText: "Câu trả lời rất dài.", speakText: "Câu trả lời rất dài.", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });

    act(() => screen.getByTestId("stop-speaking").click());
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    await act(async () => {
      vi.advanceTimersByTime(4600);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("false");
  });

  it("audio đọc hết tự nhiên thì cờ speaking tự hạ, không cần ai bấm", async () => {
    const audio = await startSpeaking();

    await act(async () => {
      audio.ended = true;
      audio.dispatchEvent(new Event("ended"));
    });

    expect(screen.getByTestId("speaking").textContent).toBe("false");
    expect(audio.paused).toBe(false);
  });
});

describe("DriverShellProvider — đóng overlay theo audio, tap-outside, lịch sử", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "t1" });
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  it("closeVoice() đóng ngay lập tức, không đợi audio hay hẹn giờ nào", async () => {
    // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
    // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
    // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
    // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    act(() => screen.getByTestId("close-voice").click());
    expect(screen.getByTestId("voice-open").textContent).toBe("false");
  });

  it("có audio TTS đang phát dở — overlay KHÔNG tự đóng cho tới khi audio 'ended', rồi đợi thêm CLOSE_AFTER_AUDIO_MS", async () => {
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    // Không dùng `new (real)Audio(...)` — jsdom tự đặt `.error` gần như ngay
    // lập tức với nguồn base64 giả không phải audio thật, làm test không
    // kiểm soát được thời điểm. Audio giả tối thiểu (EventTarget +
    // play/pause/ended/error) đủ cho DriverShellProvider dùng, kiểm soát
    // được chính xác lúc nào "ended" xảy ra.
    class FakeAudio extends EventTarget {
      ended = false;
      error: MediaError | null = null;
      play() {
        return Promise.resolve();
      }
      pause() {}
    }
    const createdAudios: FakeAudio[] = [];
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Hiệu ứng đóng theo audio chỉ chạy khi overlay ĐANG MỞ (voiceOpen) —
    // phải mở qua openVoice() thật, không phải send() (send() không đụng
    // voiceOpen, đúng như trước giờ — chỉ overlay giọng nói mới có audio).
    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    // assistant.speech tới trước — tạo 1 HTMLAudioElement thật (jsdom hỗ trợ
    // constructor + EventTarget, chỉ .play() thật là not-implemented — đã có
    // .catch(() => {}) trong code xử lý đúng ca này).
    act(() =>
      emit({
        type: "assistant.speech",
        turnId: "t1",
        audioBase64: "AAAA",
        mimeType: "audio/wav",
      }),
    );
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: { displayText: "Đã bật điều hòa.", speakText: "Đã bật điều hòa.", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );
    // MIN_TRANSCRIPT_VISIBLE_MS (transcriptShownAtRef null ở lượt gõ chữ) —
    // elapsed = Infinity nên áp dụng ngay, không hoãn.
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã bật điều hòa.");
    expect(createdAudios).toHaveLength(1);

    // Audio còn "đang phát" (chưa dispatch 'ended') — dù có đợi rất lâu,
    // overlay KHÔNG được tự đóng.
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    // Audio phát xong — bắt đầu đếm CLOSE_AFTER_AUDIO_MS (4500ms).
    act(() => createdAudios[0].dispatchEvent(new Event("ended")));
    await act(async () => {
      vi.advanceTimersByTime(4400);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true"); // chưa đủ 4500ms

    await act(async () => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("false");

    vi.unstubAllGlobals();
  });

  it("hasMoreToRead=true — overlay KHÔNG tự đóng dù audio đã 'ended' và đợi rất lâu (issue #343)", async () => {
    // Trước bản sửa cho #343: hiệu ứng đóng-theo-audio không phân biệt lượt
    // còn mời "nghe tiếp" hay không, nên nó tự đóng thẻ ngay sau
    // CLOSE_AFTER_AUDIO_MS — giấu mất nút "Nghe tiếp" và (giả sử wake word
    // bật) cửa sổ nghe tiếp ngay lúc chúng còn tác dụng. Đóng lại giờ là việc
    // của cửa sổ nghe tiếp (onFollowUpWindowExpired) hoặc tài xế bấm tay.
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    class FakeAudio extends EventTarget {
      ended = false;
      error: MediaError | null = null;
      play() {
        return Promise.resolve();
      }
      pause() {}
    }
    const createdAudios: FakeAudio[] = [];
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    act(() =>
      emit({
        type: "assistant.speech",
        turnId: "t1",
        audioBase64: "AAAA",
        mimeType: "audio/wav",
      }),
    );
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: {
          displayText: "Đây là đoạn đầu của sổ tay.",
          speakText: "Đây là đoạn đầu của sổ tay.",
          citations: [],
          outcomes: [],
          hasMoreToRead: true,
          moMicNgan: false,
        },
      }),
    );
    expect(createdAudios).toHaveLength(1);

    // Audio đọc xong — với hasMoreToRead=false đây là lúc CLOSE_AFTER_AUDIO_MS
    // bắt đầu đếm (xem test bên trên); với true thì không có hẹn giờ nào cả.
    act(() => createdAudios[0].dispatchEvent(new Event("ended")));
    await act(async () => {
      vi.advanceTimersByTime(60_000); // rất lâu — không có hẹn giờ nào để "chưa đủ"
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    vi.unstubAllGlobals();
  });

  it("lịch sử giữ tối đa 3 câu trả lời gần nhất, mới nhất ở cuối; đóng overlay thì dọn sạch", async () => {
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
    // Mỗi lượt một turnId RIÊNG — backend cấp `turn_id` duy nhất cho từng lượt
    // (`docs/api_spec.md`), và từ khi Provider lọc kết quả tới muộn theo turnId,
    // một test double phát lại cùng một id cho mọi lượt sẽ mô tả một hệ không tồn
    // tại: lượt 2 "kế thừa" đúng id mà lượt 1 vừa để lại.
    let soLuot = 0;
    vi.mocked(turnService.sendVoice).mockImplementation(async () => ({ turnId: `t${++soLuot}` }));

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    async function runTurn(replyText: string, turnId: string) {
      act(() => screen.getByTestId("open-voice").click());
      // startWavRecording() là async — nhường control để .then() gán
      // recorderRef chạy xong trước khi lượt kế tiếp gọi lại openVoice()
      // (guard voiceStartingRef/recorderRef mới hoạt động đúng).
      await act(async () => {
        await Promise.resolve();
        await Promise.resolve();
      });
      act(() =>
        emit({
          type: "assistant.response",
          turnId,
          result: { displayText: replyText, speakText: replyText, citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
        }),
      );
      // Phải dừng ghi thật (giải phóng recorderRef) — không thì openVoice()
      // của lượt kế tiếp bị chặn ngay từ guard chống mở lặp, không chạy gì cả.
      await act(async () => {
        screen.getByTestId("stop-voice").click();
        await Promise.resolve();
        await Promise.resolve();
      });
    }

    // Lượt N gửi xong mới biết id của nó, nên câu trả lời của lượt N mang id mà
    // `sendVoice` đã cấp ở lượt TRƯỚC đó trong dòng thời gian của test này: lượt 1
    // chưa gọi sendVoice lúc emit, lượt 2 emit sau khi lượt 1 đã stop-voice, v.v.
    await runTurn("Trả lời 1", "t1");
    await runTurn("Trả lời 2", "t2"); // lúc mở lượt này, "Trả lời 1" chuyển vào lịch sử
    await runTurn("Trả lời 3", "t3");
    await runTurn("Trả lời 4", "t4");

    // Tối đa 3 mục, mới nhất ở cuối — "Trả lời 1" đã bị đẩy ra khỏi lịch sử;
    // "Trả lời 4" là lượt HIỆN TẠI (lastTurn), chưa vào lịch sử vì chưa có
    // lượt nào mới hơn thay thế nó.
    expect(screen.getByTestId("turn-history").textContent).toBe("Trả lời 1|Trả lời 2|Trả lời 3");

    act(() => screen.getByTestId("close-voice").click());
    expect(screen.getByTestId("turn-history").textContent).toBe("");
  });

  it("tap-outside (closeVoice) lúc đang ghi phải huỷ recorder + clear timer 12s — VAD/timer tới muộn không được gửi audio lên BE (blocker PM/PO review PR #102)", async () => {
    // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
    // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
    // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
    // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
    const recorder = {
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    };
    let capturedOnSilenceDetected: (() => void) | undefined;
    vi.mocked(startWavRecording).mockImplementation(async (options) => {
      capturedOnSilenceDetected = options?.onSilenceDetected;
      return recorder;
    });

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startWavRecording).toHaveBeenCalled();

    // Tap-outside — gọi closeVoice() trực tiếp (KHÁC nút "stop-voice" chủ
    // động), đúng đường đi thật của scrim onClick trong VoiceOverlay.
    act(() => screen.getByTestId("close-voice").click());

    expect(recorder.cancel).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("voice-open").textContent).toBe("false");

    // VAD tới muộn (mô phỏng: onSilenceDetected bắn sau khi đã đóng) — không
    // được gửi gì lên BE, vì recorderRef đã null từ lúc closeVoice().
    act(() => capturedOnSilenceDetected?.());
    await act(async () => {
      await Promise.resolve();
    });
    expect(turnService.sendVoice).not.toHaveBeenCalled();
    expect(recorder.stop).not.toHaveBeenCalled();

    // Timer MAX_RECORDING_MS (12s) cũng đã bị clear ở closeVoice() — trôi
    // qua mốc đó vẫn không có gì được gửi.
    await act(async () => {
      vi.advanceTimersByTime(12_000);
    });
    expect(turnService.sendVoice).not.toHaveBeenCalled();
    expect(recorder.stop).not.toHaveBeenCalled();
  });

  it("audio TTS của lượt CŨ tới 'ended' muộn KHÔNG được đóng overlay của lượt MỚI đã bắt đầu (PM/PO + reviewer lifecycle concern, PR #102)", async () => {
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    class FakeAudio extends EventTarget {
      ended = false;
      error: MediaError | null = null;
      play() {
        return Promise.resolve();
      }
      pause() {}
    }
    const createdAudios: FakeAudio[] = [];
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Lượt 1: có audio TTS + câu trả lời — effect đóng-theo-audio gắn
    // listener vào ĐÚNG audio1 (đóng gói qua closure lúc effect chạy).
    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() =>
      emit({ type: "assistant.speech", turnId: "t1", audioBase64: "AAAA", mimeType: "audio/wav" }),
    );
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: { displayText: "Trả lời 1", speakText: "Trả lời 1", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Trả lời 1");
    expect(createdAudios).toHaveLength(1);
    const audio1 = createdAudios[0];

    // Giải phóng recorderRef của lượt 1 trước — guard chống mở lặp trong
    // openVoice() (voiceStartingRef/recorderRef) sẽ chặn lượt 2 nếu chưa
    // dừng ghi lượt 1 (cùng lý do helper runTurn() ở test lịch sử phía trên).
    await act(async () => {
      screen.getByTestId("stop-voice").click();
      await Promise.resolve();
      await Promise.resolve();
    });

    // Mở lượt MỚI trước khi audio1 kịp "ended" — openVoice() reset lastTurn
    // (đẩy "Trả lời 1" vào history) và pause() audio1, nhưng KHÔNG dispatch
    // "ended" (giống hệt hành vi pause() thật của trình duyệt).
    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");

    // audio1 (mồ côi, không còn được activeSpeechRef trỏ tới) giờ mới bắn
    // "ended" muộn — effect đã cleanup listener của nó khi lastTurn đổi
    // (reset về null lúc openVoice() lượt mới) nên sự kiện này phải KHÔNG có
    // tác dụng gì lên lượt mới.
    act(() => audio1.dispatchEvent(new Event("ended")));
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    // Lượt 2 chưa có lastTurn.vivi (chưa trả lời) nên effect đóng-theo-audio
    // còn chưa kích hoạt đếm giờ nào cả — "ended" mồ côi của audio1 không
    // được phép đóng overlay đang mở cho lượt 2.
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    vi.unstubAllGlobals();
  });

  /**
   * Khe hẹp giữa hai test kề trên, và là khe DUY NHẤT chưa ai bọc: test
   * "đợi 'ended' rồi mới đếm" để hẹn giờ chạy trọn vẹn, còn test "'ended' mồ
   * côi" thì thay audio TRƯỚC khi 'ended' kịp bắn nên chưa hề có hẹn giờ nào.
   * Ở đây 'ended' đã bắn (hẹn giờ ĐANG đếm dở) thì lượt mới mới đè audio lên.
   *
   * Hỏng thì tài xế thấy: đang nghe VIVI trả lời lượt 2, thẻ thoại tự biến
   * mất giữa chừng vì hẹn giờ mồ côi của lượt 1 tới hạn.
   *
   * Lưới an toàn của cơ chế này là `speechStopCount` (xem docstring của nó
   * trong DriverShellProvider): `stopSpeech()` nhích bộ đếm ⇒ effect
   * đóng-theo-audio chạy lại ⇒ cleanup gỡ listener audio cũ + clearTimeout.
   * Bỏ `speechStopCount` khỏi mảng dependency của effect đó là test này đỏ.
   */
  it("audio lượt MỚI đè lên lúc hẹn giờ đóng của lượt CŨ đang đếm dở — huỷ hẹn giờ cũ, gỡ listener cũ, tắt tiếng audio cũ", async () => {
    let emit: (event: DriverEvent) => void = () => {};
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      // Xem chú thích ở describe đầu tiên: test double phải phát `ui.policy` như hàng thật.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });

    // Audio giả (lý do không dùng Audio thật của jsdom: xem test dòng ~657).
    // Có ghi sổ add/remove listener để chứng minh "listener cũ đã được gỡ"
    // bằng bằng chứng trực tiếp thay vì chỉ suy ra từ hành vi — hai thứ đó
    // hỏng theo kiểu khác nhau. Lưu ý listener `{ once: true }` khi bắn thì
    // EventTarget tự gỡ bên trong, KHÔNG gọi qua removeEventListener, nên sổ
    // `removed` chỉ ghi đúng phần cleanup tường minh của effect.
    class FakeAudio extends EventTarget {
      ended = false;
      error: MediaError | null = null;
      paused = false;
      readonly removed: string[] = [];
      override removeEventListener(
        type: string,
        callback: EventListenerOrEventListenerObject | null,
        options?: boolean | EventListenerOptions,
      ) {
        this.removed.push(type);
        super.removeEventListener(type, callback, options);
      }
      play() {
        return Promise.resolve();
      }
      pause() {
        this.paused = true;
      }
    }
    const createdAudios: FakeAudio[] = [];
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    act(() => screen.getByTestId("open-voice").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // ---- Lượt 1: có audio + câu trả lời ⇒ effect gắn listener vào audio1.
    act(() =>
      emit({ type: "assistant.speech", turnId: "t1", audioBase64: "AAAA", mimeType: "audio/wav" }),
    );
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: { displayText: "Trả lời 1", speakText: "Trả lời 1", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );
    expect(createdAudios).toHaveLength(1);
    const audio1 = createdAudios[0];

    // audio1 đọc xong ⇒ hẹn giờ CLOSE_AFTER_AUDIO_MS (4500ms) bắt đầu đếm.
    // `.ended = true` cho khớp trình duyệt thật — `shouldStartCloseTimerImmediately`
    // đọc đúng thuộc tính này, không đọc sự kiện.
    act(() => {
      audio1.ended = true;
      audio1.dispatchEvent(new Event("ended"));
    });

    // Mới 2000/4500ms — còn 2500ms nữa mới đóng. Đây là điều kiện tiên quyết
    // của cả test: hẹn giờ phải đang treo THẬT tại thời điểm audio bị thay.
    await act(async () => {
      vi.advanceTimersByTime(2000);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    // ---- Lượt 2 tới, đè audio lên khi hẹn giờ cũ còn 2500ms.
    act(() =>
      emit({ type: "assistant.speech", turnId: "t2", audioBase64: "BBBB", mimeType: "audio/wav" }),
    );
    expect(createdAudios).toHaveLength(2);
    const audio2 = createdAudios[1];

    // AC3 — lượt mới tắt tiếng audio cũ, không để hai giọng chồng nhau.
    expect(audio1.paused).toBe(true);
    // AC1 — listener của effect trên audio cũ đã được gỡ.
    expect(audio1.removed).toEqual(expect.arrayContaining(["ended", "error"]));

    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t2",
        result: { displayText: "Trả lời 2", speakText: "Trả lời 2", citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
      }),
    );
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Trả lời 2");

    // AC2 — 10s trôi qua, thừa sức nuốt trọn 2500ms còn lại của hẹn giờ cũ.
    // Overlay lượt 2 vẫn phải mở: audio2 chưa 'ended' nên chưa có gì để đếm.
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    // audio1 mồ côi bắn 'ended' lần nữa (vd trình duyệt phát lại sự kiện đệm)
    // cũng không được đặt hẹn giờ mới lên lượt 2.
    act(() => audio1.dispatchEvent(new Event("ended")));
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("true");

    // Chốt ngược lại: cơ chế đóng vẫn SỐNG, chỉ là đã chuyển sang bám audio2.
    // Không có khẳng định này thì test vẫn xanh cả khi effect chết hẳn và
    // overlay không bao giờ đóng nữa — tức là bọc nhầm một lỗi khác.
    act(() => {
      audio2.ended = true;
      audio2.dispatchEvent(new Event("ended"));
    });
    await act(async () => {
      vi.advanceTimersByTime(4500);
    });
    expect(screen.getByTestId("voice-open").textContent).toBe("false");

    vi.unstubAllGlobals();
  });
});

/**
 * Đ6 phần A — kết quả của lượt CŨ tới sau khi lượt MỚI đã bắt đầu.
 *
 * Báo cáo @danggiap123 24/08: *"bảo bật điều hòa, nói nhỏ quá nó không nhận; một lúc
 * sau nó tự bật điều hòa. Nói tiếp mở cửa thì cửa vẫn mở nhưng text output lại hiện
 * bật điều hòa."*
 *
 * Khác ca đã có test ở trên (`assistant.response` của lượt cũ **đang bị hoãn** lúc
 * lượt mới bắt đầu): ở đây event tới **muộn hẳn**, sau khi lượt 2 đã có câu trả lời
 * trên màn. `turnGenerationRef` không bắt được ca này vì nó chụp generation **lúc
 * event tới** — lúc ấy generation đã là của lượt 2, nên guard so bằng chính nó và
 * cho qua. Chỗ sửa là lọc theo `turnId`, thứ mọi event lượt đều mang sẵn.
 */
describe("kết quả tới muộn của lượt đã bị thay thế", () => {
  class FakeAudio extends EventTarget {
    ended = false;
    error: MediaError | null = null;
    paused = false;
    play() {
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
  }
  const createdAudios: FakeAudio[] = [];
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    vi.useFakeTimers();
    createdAudios.length = 0;
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    cleanup();
    vi.clearAllMocks();
  });

  function traLoi(turnId: string, text: string): DriverEvent {
    return {
      type: "assistant.response",
      turnId,
      result: { displayText: text, speakText: text, citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
    };
  }

  async function dungHaiLuot() {
    // Mỗi lần gửi trả một turnId khác — đây là điều kiện để phân biệt hai lượt.
    vi.mocked(turnService.sendText).mockResolvedValueOnce({ turnId: "t1" }).mockResolvedValueOnce({ turnId: "t2" });
    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Lượt 1 — gửi, và để `sendText` resolve để FE biết turnId "t1".
    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    // Lượt 2 — bắt đầu trước khi lượt 1 kịp trả lời.
    act(() => screen.getByTestId("send").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("text của lượt cũ tới muộn KHÔNG đè lên câu trả lời của lượt mới", async () => {
    await dungHaiLuot();

    // Lượt 2 trả lời trước — đây là thứ đang đúng trên màn hình.
    act(() => emit(traLoi("t2", "Đã mở cửa.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã mở cửa.");

    // Rồi lượt 1 mới trả lời. Trước khi sửa, câu này ghi đè và tài xế thấy
    // "Đã bật điều hòa." trong khi việc vừa xảy ra là mở cửa.
    act(() => emit(traLoi("t1", "Đã bật điều hòa.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã mở cửa.");
  });

  it("giọng đọc của lượt cũ KHÔNG được phát", async () => {
    await dungHaiLuot();
    act(() =>
      emit({ type: "assistant.speech", turnId: "t1", audioBase64: "AAAA", mimeType: "audio/wav" }),
    );
    expect(createdAudios).toHaveLength(0);

    // Lượt hiện tại thì vẫn phát bình thường — đây là nửa chứng minh cổng lọc
    // không chặn nhầm mọi thứ.
    act(() =>
      emit({ type: "assistant.speech", turnId: "t2", audioBase64: "AAAA", mimeType: "audio/wav" }),
    );
    expect(createdAudios).toHaveLength(1);
  });

  it("lượt của thiết bị KHÁC trên cùng session vẫn hiện — không bị lọc oan", async () => {
    await dungHaiLuot();

    // turnId lạ: không phải lượt nào máy này từng gửi, nên không nằm trong tập
    // "đã bị thay thế". Nhánh `turn.accepted` cố ý bắt cả lượt như vậy (issue #106),
    // nên lọc đại trà theo "khác lượt hiện tại" sẽ cắt mất nó.
    act(() => emit(traLoi("t-may-khac", "Đã bật đèn.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã bật đèn.");
  });
});

/**
 * Đ6 phần B — race mà điều kiện approve #1 của review #307 chỉ ra.
 *
 * Bộ test ở trên luôn cho `sendText` resolve **trước** khi phát event, nên nó không
 * chứng minh được trình tự nguy hiểm: request lượt 1 còn treo → lượt 2 bắt đầu →
 * event của lượt 1 tới → *rồi* request lượt 1 mới resolve.
 *
 * Trình tự ấy không phải giả thuyết, nó là hành vi **mặc định** của `POST /turns/text`:
 * route đồng bộ, và `emit_turn_lifecycle` phát `assistant.response` xong mới trả
 * envelope. Nên với mọi lượt gõ chữ, `turnId` từ HTTP luôn tới SAU mọi event của chính
 * lượt đó — bộ lọc theo turnId của bản đầu không bao giờ kịp chạy.
 *
 * Hai hàng rào, và test dưới đây kiểm từng cái một:
 *
 * 1. `turn.accepted` — backend phát nó cho cả lượt text từ #307, ngay trước
 *    `graph.ainvoke`, tức trước mọi event khác của lượt. Đây là mỏ neo chính.
 * 2. Generation chụp **lúc gửi** — cứu khi WebSocket chưa nối và chỉ còn đường HTTP.
 */
describe("race: request còn treo khi lượt mới bắt đầu", () => {
  class FakeAudio extends EventTarget {
    ended = false;
    error: MediaError | null = null;
    paused = false;
    play() {
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
  }
  const createdAudios: FakeAudio[] = [];
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    vi.useFakeTimers();
    createdAudios.length = 0;
    class SpyAudio extends FakeAudio {
      constructor() {
        super();
        createdAudios.push(this);
      }
    }
    vi.stubGlobal("Audio", SpyAudio);
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    cleanup();
    vi.clearAllMocks();
  });

  function traLoi(turnId: string, text: string): DriverEvent {
    return {
      type: "assistant.response",
      turnId,
      result: { displayText: text, speakText: text, citations: [], outcomes: [], hasMoreToRead: false, moMicNgan: false },
    };
  }

  async function nhuong() {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  /** Lượt 1 gửi xong nhưng HTTP **chưa** resolve; lượt 2 đã bắt đầu. */
  async function haiLuotVoiHttpTreo() {
    let giaiPhongLuot1: (v: { turnId: string }) => void = () => {};
    vi.mocked(turnService.sendText)
      .mockImplementationOnce(
        () =>
          new Promise<{ turnId: string }>((res) => {
            giaiPhongLuot1 = res;
          }),
      )
      .mockResolvedValueOnce({ turnId: "t2" });

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await nhuong();

    act(() => screen.getByTestId("send").click());
    await nhuong();
    act(() => emit({ type: "turn.accepted", turnId: "t1", inputMode: "text" }));

    act(() => screen.getByTestId("send").click());
    await nhuong();
    act(() => emit({ type: "turn.accepted", turnId: "t2", inputMode: "text" }));

    return { giaiPhongLuot1 };
  }

  it("event của lượt 1 tới TRƯỚC khi request lượt 1 resolve vẫn bị chặn", async () => {
    const { giaiPhongLuot1 } = await haiLuotVoiHttpTreo();

    // Đây là điểm bản đầu thua: lúc này `turnIdHienTaiRef` của nó còn `null` (chưa
    // ai resolve), nên "t1" không nằm trong tập đã-thay-thế và event đi thẳng lên UI.
    act(() => emit(traLoi("t1", "Đã bật điều hòa.")));
    act(() => emit({ type: "assistant.speech", turnId: "t1", audioBase64: "AAAA", mimeType: "audio/wav" }));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");
    expect(createdAudios).toHaveLength(0);

    // Giờ request lượt 1 mới resolve — id về muộn KHÔNG được nhận làm lượt hiện tại.
    await act(async () => {
      giaiPhongLuot1({ turnId: "t1" });
      await Promise.resolve();
    });
    act(() => emit(traLoi("t1", "Đã bật điều hòa.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");

    // Và lượt 2 vẫn hiện bình thường — cổng lọc không chặn nhầm tất cả.
    act(() => emit(traLoi("t2", "Đã mở cửa.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã mở cửa.");
  });

  it("không có turn.accepted (WS chưa nối) thì generation lúc gửi vẫn chặn được", async () => {
    // CẢ HAI request đều treo. Đây mới là trình tự phân biệt được hai bản: id của lượt
    // 1 về trong lúc `turnIdHienTaiRef` còn `null` (lượt 2 chưa có id của nó). Bản đầu
    // đọc `null` là "chưa có lượt nào" và ghi id CŨ vào ô lượt hiện tại; bản này so
    // với generation chụp lúc gửi nên biết id ấy đã lỗi thời.
    const giaiPhong: Array<(v: { turnId: string }) => void> = [];
    vi.mocked(turnService.sendText).mockImplementation(
      () =>
        new Promise<{ turnId: string }>((res) => {
          giaiPhong.push(res);
        }),
    );

    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await nhuong();

    act(() => screen.getByTestId("send").click());
    await nhuong();
    act(() => screen.getByTestId("send").click());
    await nhuong();

    await act(async () => {
      giaiPhong[0]({ turnId: "t1" });
      await Promise.resolve();
    });
    act(() => emit(traLoi("t1", "Đã bật điều hòa.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");

    // Rồi lượt 2 resolve và trả lời — vẫn hiện đúng.
    await act(async () => {
      giaiPhong[1]({ turnId: "t2" });
      await Promise.resolve();
    });
    act(() => emit(traLoi("t2", "Đã mở cửa.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Đã mở cửa.");
  });

  it("danh sách lượt cũ có trần — phiên IVI dài không phình mãi", async () => {
    // Điều kiện approve #3. Trần là `GIOI_HAN_LUOT_CU` (32); test lái 40 lượt để
    // vượt qua nó, rồi kiểm CẢ HAI nửa của đánh đổi: lượt vừa mới bị thay thế vẫn
    // chặn được, còn lượt đã trôi quá xa thì được thả — đó là ý nghĩa của cái trần,
    // và một lượt già thế thì mọi event của nó đã tới từ lâu.
    let n = 0;
    vi.mocked(turnService.sendText).mockImplementation(async () => ({ turnId: `t${++n}` }));
    render(
      <DriverShellProvider>
        <VoiceTestConsumer />
      </DriverShellProvider>,
    );
    await nhuong();

    for (let i = 0; i < 40; i += 1) {
      act(() => screen.getByTestId("send").click());
      await nhuong();
    }

    // `t39` là lượt ngay trước lượt hiện tại (`t40`) — phải còn bị chặn.
    act(() => emit(traLoi("t39", "Kết quả cũ gần đây.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("");

    // `t1` đã rụng khỏi danh sách có trần.
    act(() => emit(traLoi("t1", "Kết quả rất cũ.")));
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    expect(screen.getByTestId("last-turn-vivi").textContent).toBe("Kết quả rất cũ.");
  });
});
