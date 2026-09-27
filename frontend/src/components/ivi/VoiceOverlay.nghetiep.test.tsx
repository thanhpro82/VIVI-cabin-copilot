// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { CONTINUE_READING_COMMAND, OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";
import { VoiceOverlay } from "./VoiceOverlay";

/** Thay cho nút mic ở HomeView — VoiceOverlay tự nó không mở được. */
function OverlayOpener() {
  const { openVoice, stopVoice } = useDriverShell();
  return (
    <>
      <button type="button" data-testid="open" onClick={openVoice} />
      <button type="button" data-testid="stop" onClick={stopVoice} />
    </>
  );
}

vi.mock("@/lib/audio/wavRecorder", () => ({ startWavRecording: vi.fn() }));
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

const { startWavRecording } = await import("@/lib/audio/wavRecorder");
const { sessionService } = await import("@/lib/services/session");
const { turnService } = await import("@/lib/services/turn");

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

/**
 * Nút "Nghe tiếp" (issue #116).
 *
 * Vì sao test qua Provider thật thay vì stub context: thứ dễ hỏng nhất không
 * phải cái nút, mà là **cờ có đi được từ `assistant.response` tới chỗ render
 * hay không** — đúng đoạn mà `citations` từng bị Provider vứt mất (issue #111).
 */
describe("VoiceOverlay — nút Nghe tiếp", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    vi.useFakeTimers();
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({
      sessionId: "ses_1",
      vehicleId: "vehicle-demo-01",
      status: "active",
      startedAt: "2026-01-01T00:00:00Z",
      canDrive: true,
      pool: null,
    });
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "t1" });
    vi.mocked(turnService.sendVoice).mockResolvedValue({ turnId: "t1" });
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    });
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
    // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
    // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
    // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
    // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
      cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.resetAllMocks();
  });

  /** Mở overlay rồi đẩy một câu trả lời sổ tay vào. */
  async function answerWith(hasMoreToRead: boolean) {
    render(
      <DriverShellProvider>
        <OverlayOpener />
        <VoiceOverlay />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    // Mở overlay bằng đường thật (openVoice) rồi dừng ghi, để tới pha hiển thị
    // câu trả lời chứ không phải pha đang-thu. VoiceOverlay không tự mở được —
    // nút mic nằm ở HomeView, nên test phải cấp một lối gọi tương đương.
    act(() => screen.getByTestId("open").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => screen.getByTestId("stop").click());
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() =>
      emit({
        type: "assistant.response",
        turnId: "t1",
        result: {
          displayText: "Áp suất lốp tiêu chuẩn là 2,4 bar.",
          speakText: "Áp suất lốp tiêu chuẩn là 2,4 bar.",
          citations: [],
          outcomes: [],
          hasMoreToRead,
          moMicNgan: false,
        },
      }),
    );
    await act(async () => {
      vi.advanceTimersByTime(2100);
    });
  }

  it("còn phần chưa đọc thì hiện nút", async () => {
    await answerWith(true);
    expect(screen.getByRole("button", { name: /nghe tiếp/i })).toBeDefined();
  });

  it("đọc hết rồi thì KHÔNG có nút — nút bấm vào ngõ cụt còn tệ hơn không có", async () => {
    await answerWith(false);
    expect(screen.queryByRole("button", { name: /nghe tiếp/i })).toBeNull();
  });

  /**
   * Nút gửi đúng câu người dùng phải NÓI nếu không bấm — cùng một intent
   * `manual_continue` ở backend, nên nút và giọng nói không thể lệch nhau. Gửi
   * chuỗi khác (vd "Đọc tiếp") là tạo ra một đường thứ hai mà STT không nhận.
   */
  it("bấm nút gửi đúng câu kích hoạt, không phải một chuỗi tự chế", async () => {
    await answerWith(true);

    await act(async () => {
      screen.getByRole("button", { name: /nghe tiếp/i }).click();
      // `send()` đợi `sessionReadyRef` xong mới gọi sendText — phải nhường
      // control cho chuỗi .then() chạy hết, không thì đo lúc chưa gửi.
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(turnService.sendText).toHaveBeenCalledWith(CONTINUE_READING_COMMAND);
  });
});
