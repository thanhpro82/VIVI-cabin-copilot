// @vitest-environment jsdom
/**
 * `approval.required` tới thì tự bắt đầu ghi âm ngay — tài xế không cần chạm
 * mic để trả lời "đồng ý"/"từ chối" (yêu cầu người dùng: "hạn chế bấm nút hết
 * cỡ"). Trước thay đổi này overlay giọng nói không tự mở lại: nếu lệnh gốc
 * cũng được nói bằng giọng (không phải gõ chữ), `voiceOpen` đã true từ lúc mở
 * overlay cho lệnh gốc và không có gì đặt lại false trong lúc chờ duyệt, nên
 * nút mic ở `Dock.tsx` (`disabled={voiceOpen}`) bị khoá — tài xế mắc kẹt,
 * không có cách nào (kể cả bấm) để trả lời bằng giọng.
 *
 * Phải đợi TTS hỏi xong ("Bạn có đồng ý không?") rồi mới bắt đầu ghi — bắt
 * đầu ngay khi `pendingApproval` được set sẽ cắt ngang câu hỏi
 * (`openVoice()` gọi `stopSpeech()`). Fail-open theo đúng cơ chế đã có ở
 * `shouldStartCloseTimerImmediately`: không có audio / audio lỗi / bị chặn
 * autoplay đều phải bắt đầu ghi ngay, không treo chờ một `ended` không bao
 * giờ tới.
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

  // Mốc hết hạn phải là **tương lai thật**, không phải một hằng số 2026-01-01: từ khi
  // hộp thoại tự gỡ theo `expires_at` (bug "hộp thoại duyệt biến mất"), một mốc trong
  // quá khứ nghĩa là fixture đang mô tả một phê duyệt ĐÃ CHẾT, và hộp thoại biến mất
  // ngay — test đỏ vì fixture, không phải vì hành vi.
const HET_HAN = () => new Date(Date.now() + 30_000).toISOString();

vi.mock("@/lib/audio/wavRecorder", () => ({
  startWavRecording: vi.fn(),
  createSpeechEnergyTracker: vi.fn(() => ({ push: () => false, reset: () => {} })),
}));

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

const PHIEN = {
  sessionId: "ses_vi_1",
  vehicleId: "vehicle-demo-01",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
};

const TRANG_THAI_XE = {
  vehicleId: "vehicle-demo-01",
  stateVersion: 3,
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

const APPROVAL_REQUIRED: DriverEvent = {
  type: "approval.required",
  turnId: "turn_goc",
  approvalId: "appr-123",
  planId: "plan-1",
  approvedVehicleStateVersion: 3,
  expiresAt: HET_HAN(),
};

function Consumer() {
  const { voiceOpen, recording, openVoice, stopVoice } = useDriverShell();
  return (
    <div>
      <span data-testid="trang-thai">
        {voiceOpen ? "mo" : "dong"}/{recording ? "dang-ghi" : "khong-ghi"}
      </span>
      <button type="button" onClick={openVoice} data-testid="open-voice">
        open
      </button>
      <button type="button" onClick={stopVoice} data-testid="stop-voice">
        stop
      </button>
    </div>
  );
}

async function dungProvider() {
  let phat: (event: DriverEvent) => void = () => {};
  vi.mocked(turnService.subscribe).mockImplementation((cb) => {
    phat = cb;
  // Cả mock.ts lẫn real.ts đều phát `ui.policy` ngay sau handshake, và kể từ
  // issue #241 Provider coi "chưa nhận policy nào" là CHƯA xác nhận kết nối
  // (fail-closed, chặn mọi lượt gửi). Test double phải phát y như hàng thật,
  // không thì mọi test dưới đây chạy trong trạng thái `connecting`.
    cb({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY });
    return () => {};
  });
  const view = render(
    <DriverShellProvider>
      <Consumer />
    </DriverShellProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return { phat, view };
}

describe("approval.required -> tự động ghi âm, không cần bấm mic", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("không có assistant.speech (fail-open) — bắt đầu ghi ngay khi approval.required tới", async () => {
    const recorder = { stop: vi.fn().mockResolvedValue(new Blob()), cancel: vi.fn(), hadSpeech: () => true };
    vi.mocked(startWavRecording).mockResolvedValue(recorder as never);
    const { phat } = await dungProvider();

    await act(async () => {
      phat(APPROVAL_REQUIRED);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startWavRecording).toHaveBeenCalled();
  });

  it("mic đang mở sẵn từ lệnh gốc nói bằng giọng (voiceOpen đã true, recorder đã dừng) vẫn tự ghi lại được", async () => {
    // Đúng ca lỗi ban đầu: lệnh gốc bằng giọng khiến voiceOpen=true rồi
    // recorder đã dừng (đợi duyệt) — không phải trạng thái "chưa mở" mà
    // effect có thể lầm tưởng là "khỏi cần làm gì".
    const recorder = { stop: vi.fn().mockResolvedValue(new Blob()), cancel: vi.fn(), hadSpeech: () => true };
    vi.mocked(startWavRecording).mockResolvedValue(recorder as never);
    vi.mocked(turnService.sendVoice).mockResolvedValue({ turnId: "turn_goc" } as never);
    const { phat, view } = await dungProvider();

    // Mở overlay bằng đường thật (bấm mic) rồi dừng ghi — mô phỏng lệnh gốc
    // đã nói xong và gửi lên BE, giống hệt trạng thái thật lúc approval tới.
    await act(async () => {
      view.getByTestId("open-voice").click();
      await Promise.resolve();
    });
    await act(async () => {
      view.getByTestId("stop-voice").click();
      await Promise.resolve();
    });
    expect(view.getByTestId("trang-thai").textContent).toBe("mo/khong-ghi");

    vi.mocked(startWavRecording).mockClear();

    await act(async () => {
      phat(APPROVAL_REQUIRED);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startWavRecording).toHaveBeenCalled();
  });
});
