// @vitest-environment jsdom
/**
 * Mic của lượt phê duyệt (#207b) — ba lỗ mà #203 để lại, đo trên chính mã của nó.
 *
 * #203 đã làm phần khó: `approval.required` tới thì tự ghi âm, không bắt tài xế chạm
 * mic. Ba chỗ dưới đây là phần còn thiếu, và cả ba đều **im lặng** — không có lỗi nào
 * hiện ra, chỉ có một cái mic không mở hoặc một dòng chữ biến mất.
 *
 * 1. **Mở mic ≠ bắt đầu một lượt mới.** `openVoice()` trần dọn `lastTurn` — với lệnh S2
 *    gõ bằng chữ, đó là dòng "tài xế vừa nói/gõ gì" của chính lượt đang chờ duyệt.
 * 2. **Autoplay bị chặn thì `ended` không bao giờ tới.** Element vẫn nằm trong ref với
 *    `ended=false`, `error=null`, nên `shouldStartCloseTimerImmediately` trả false và
 *    effect ngồi đợi mãi. Mic không mở, và không có gì báo.
 * 3. **Lượt trả lời hỏng thì không ai đánh thức effect.** `pendingApproval` cố ý giữ
 *    nguyên tham chiếu ở nhánh mơ hồ, mà nó là dependency duy nhất — nên xe mời "bạn
 *    nói lại giúp tôi nhé" vào một cái mic đã tắt.
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

// Mốc hết hạn phải là **tương lai thật**, không phải hằng số 2026-01-01: từ khi hộp
// thoại tự gỡ theo `expires_at` (bug "hộp thoại duyệt biến mất"), một mốc trong quá
// khứ nghĩa là fixture đang mô tả một phê duyệt ĐÃ CHẾT, và hộp thoại biến mất ngay —
// test đỏ vì fixture, không phải vì hành vi.
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

const LENH_S2 = "Mở kính bên lái 30%";

const APPROVAL_REQUIRED: DriverEvent = {
  type: "approval.required",
  turnId: "turn_goc",
  approvalId: "appr-123",
  planId: "plan-1",
  approvedVehicleStateVersion: 3,
  expiresAt: HET_HAN(),
};

/**
 * `Audio` giả — cần điều khiển được `paused`/`ended`, thứ jsdom không cho.
 *
 * Đây cũng là chỗ duy nhất phân biệt được "đang đọc thật" với "bị autoplay chặn":
 * cả hai đều `ended=false, error=null`, chỉ khác `paused`.
 */
class AudioGia {
  static cuoi: AudioGia | null = null;
  static biChan = false;
  static khongTaiDuoc = false;
  paused = true;
  /** Bằng chứng có tiếng thật sự phát ra. `!paused` một mình thì không đủ — xem
   * `CHO_AM_THANH_MS` và ca "chưa tải được" dưới cuối file. */
  currentTime = 0;
  ended = false;
  error: unknown = null;
  private nghe: Record<string, Array<() => void>> = {};

  constructor(public src: string) {
    AudioGia.cuoi = this;
  }
  addEventListener(ten: string, fn: () => void) {
    (this.nghe[ten] ??= []).push(fn);
  }
  removeEventListener(ten: string, fn: () => void) {
    this.nghe[ten] = (this.nghe[ten] ?? []).filter((f) => f !== fn);
  }
  ban(ten: string) {
    [...(this.nghe[ten] ?? [])].forEach((fn) => fn());
  }
  play() {
    if (AudioGia.biChan) return Promise.reject(new Error("NotAllowedError"));
    this.paused = false;
    // `AudioGia.khongTaiDuoc`: đã gọi `play()`, không `paused`, mà đồng hồ đứng im —
    // trạng thái thật quan sát được trên Chrome ngày 20/08 (readyState 0).
    if (!AudioGia.khongTaiDuoc) this.currentTime = 0.4;
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
  }
}

const NOI: DriverEvent = {
  type: "assistant.speech",
  turnId: "turn_goc",
  audioBase64: "AAAA",
  mimeType: "audio/wav",
};

function Consumer() {
  const { voiceOpen, recording, lastTurn, turnHistory, send, stopVoice, pendingApproval } = useDriverShell();
  return (
    <div>
      <span data-testid="trang-thai">
        {voiceOpen ? "mo" : "dong"}/{recording ? "dang-ghi" : "khong-ghi"}
      </span>
      <span data-testid="hop-thoai">{pendingApproval?.approvalId ?? "(khong)"}</span>
      <span data-testid="nguoi-noi">{lastTurn?.user ?? "(rong)"}</span>
      <span data-testid="lich-su">{turnHistory.length}</span>
      <button type="button" onClick={() => send(LENH_S2)} data-testid="gui">
        gửi
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
  return {
    view,
    async phat(...events: DriverEvent[]) {
      await act(async () => {
        events.forEach((e) => phat(e));
        await Promise.resolve();
        await Promise.resolve();
      });
    },
  };
}

function recorderGia(coTieng: boolean) {
  return {
    stop: vi.fn().mockResolvedValue(new Blob()),
    cancel: vi.fn(),
    hadSpeech: () => coTieng,
  };
}

describe("mic của lượt phê duyệt", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
    vi.mocked(turnService.sendText).mockResolvedValue({ turnId: "turn_goc" } as never);
    vi.mocked(turnService.sendVoice).mockResolvedValue({ turnId: "turn_y_dinh" } as never);
    vi.mocked(startWavRecording).mockResolvedValue(recorderGia(true) as never);
    AudioGia.biChan = false;
    AudioGia.khongTaiDuoc = false;
    AudioGia.cuoi = null;
    vi.stubGlobal("Audio", AudioGia);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("mở mic để trả lời KHÔNG được xoá dòng lệnh mà tài xế vừa gõ", async () => {
    // `openVoice()` trần dọn `lastTurn` về null vì nó khai báo "một lượt MỚI bắt đầu".
    // Câu hỏi duyệt LÀ lượt hiện tại, nên dọn ở đây là xoá đúng thứ tài xế đang trả lời:
    // tới lúc câu trả lời tới, `setLastTurn` đọc `prev?.user ?? ""` và thẻ kết quả hiện
    // ra với ô "bạn đã nói" trống trơn.
    const { view, phat } = await dungProvider();

    await act(async () => {
      view.getByTestId("gui").click();
      await Promise.resolve();
    });
    expect(view.getByTestId("nguoi-noi").textContent).toBe(LENH_S2);

    await phat(APPROVAL_REQUIRED);
    expect(startWavRecording).toHaveBeenCalled(); // mic đã tự mở (hành vi của #203)

    await phat(
      {
        type: "assistant.response",
        turnId: "turn_goc",
        result: {
          displayText: "Đã mở kính.",
          speakText: "Đã mở kính.",
          citations: [],
          outcomes: [],
          hasMoreToRead: false,
          moMicNgan: false,
        },
      } as DriverEvent,
      { type: "turn.completed", turnId: "turn_goc" },
    );

    expect(view.getByTestId("nguoi-noi").textContent).toBe(LENH_S2);
    expect(view.getByTestId("lich-su").textContent).toBe("0");
  });

  it("autoplay bị chặn thì mic vẫn phải mở — `ended` sẽ không bao giờ tới", async () => {
    // Kiểu hỏng tệ nhất: nó im lặng, và nó xảy ra đúng trên máy dễ hỏng nhất (trang
    // chưa có cử chỉ người dùng nào). Element bị chặn vẫn nằm trong `activeSpeechRef`
    // với `ended=false, error=null`, nên `shouldStartCloseTimerImmediately` trả false
    // và effect đăng ký nghe một sự kiện không bao giờ phát.
    vi.useFakeTimers();
    AudioGia.biChan = true;
    const { phat } = await dungProvider();

    await phat(NOI, APPROVAL_REQUIRED);
    expect(startWavRecording).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startWavRecording).toHaveBeenCalled();
  });

  it("audio đang đọc thật thì đường lui KHÔNG được cắt ngang câu hỏi", async () => {
    // Nửa còn lại của ca trên, và là lý do đường lui phải hỏi `paused` chứ không chỉ
    // đếm giờ: câu hỏi duyệt đọc mất vài giây, hẹn giờ nổ ở giây thứ 1,2 mà mở mic thì
    // micro thu đúng giọng của xe, VAD thấy có tiếng rồi cắt, và ta gửi lên STT một bản
    // ghi giọng của chính mình.
    vi.useFakeTimers();
    const { phat } = await dungProvider();

    await phat(NOI, APPROVAL_REQUIRED);
    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
    });
    expect(startWavRecording).not.toHaveBeenCalled();

    await act(async () => {
      AudioGia.cuoi?.ban("ended");
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(startWavRecording).toHaveBeenCalledTimes(1);

    // Và đúng MỘT lần: `ended` của lượt sau (hoặc effect chạy lại) không được mở thêm
    // một recorder đè lên bản ghi đang chạy.
    await act(async () => {
      AudioGia.cuoi?.ban("ended");
      await Promise.resolve();
    });
    expect(startWavRecording).toHaveBeenCalledTimes(1);
  });

  it("tự mở mic KHÔNG xoá hộp thoại duyệt đang chờ", async () => {
    // Hộp thoại là đường lui khi giọng nói trượt. Mở mic mà đóng mất nó thì tài xế
    // không còn cách nào quyết — và mỗi phiên chỉ được một phê duyệt chờ, nên họ cũng
    // không ra được lệnh S2 nào khác cho tới lúc nó hết hạn.
    const { view, phat } = await dungProvider();

    await phat(APPROVAL_REQUIRED);

    expect(startWavRecording).toHaveBeenCalled();
    expect(view.getByTestId("hop-thoai").textContent).toBe("appr-123");
  });

  it("audio đã gọi play() nhưng chưa tải được thì vẫn phải mở mic", async () => {
    // Đo thật trên Chrome 20/08: một `Audio` có thể ở trạng thái `paused=false`,
    // `readyState=0`, `currentTime=0`, `duration` NaN, `error=null` — đã gọi `play()`,
    // chưa hề tải, và `ended` sẽ **không bao giờ** tới. Hỏi mỗi `paused` thì đường lui
    // hoãn vô hạn đúng cái ca nó sinh ra để cứu, nên cổng phải hỏi cả đồng hồ:
    // `currentTime > 0` mới là bằng chứng có tiếng thật sự phát ra.
    vi.useFakeTimers();
    AudioGia.khongTaiDuoc = true;
    const { phat } = await dungProvider();

    await phat(NOI, APPROVAL_REQUIRED);
    expect(startWavRecording).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startWavRecording).toHaveBeenCalled();
  });

  it("câu mơ hồ thì mic mở lại — lời mời nói lại phải rơi vào một cái mic đang mở", async () => {
    // `pendingApproval` cố ý giữ nguyên tham chiếu ở nhánh này (giữ hộp thoại, xem
    // `moHoConCho`), mà nó là dependency duy nhất của effect tự mở mic — nên không có
    // gì đánh thức effect, và mic đã tắt từ lúc `stopVoiceAndSend`.
    const { view, phat } = await dungProvider();
    await phat(APPROVAL_REQUIRED);
    expect(startWavRecording).toHaveBeenCalledTimes(1);

    await act(async () => {
      view.getByTestId("stop-voice").click();
      await Promise.resolve();
    });
    await phat(
      { type: "error", code: "APPROVAL_INTENT_AMBIGUOUS", message: "Tôi chưa rõ…", retryable: true },
      { type: "turn.failed", turnId: "turn_y_dinh", code: "APPROVAL_INTENT_AMBIGUOUS" },
    );

    expect(startWavRecording).toHaveBeenCalledTimes(2);
  });

  it("bản ghi không vượt ngưỡng tiếng nói thì mic mở lại", async () => {
    // Ca này KHÔNG gửi gì lên BE (xem `hadSpeech()` trong `stopVoiceAndSend`), nên
    // không có sự kiện nào từ server để dựa vào. Chỉ nghe `turn.failed` thì nó rơi
    // vào khoảng trống.
    vi.mocked(startWavRecording).mockResolvedValue(recorderGia(false) as never);
    const { view, phat } = await dungProvider();
    await phat(APPROVAL_REQUIRED);
    expect(startWavRecording).toHaveBeenCalledTimes(1);

    await act(async () => {
      view.getByTestId("stop-voice").click();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(startWavRecording).toHaveBeenCalledTimes(2);
  });

  it("mở lại tối đa 2 lần rồi trả về cho nút bấm", async () => {
    // Không có trần thì mic-im-lặng tự nuôi chính nó: mở -> không ai nói -> mở lại, cho
    // tới lúc phê duyệt hết hạn. Tài xế không hiểu vì sao mic cứ bật, và hộp thoại vẫn
    // ở đó để chạm — đó mới là đường lui đúng khi giọng nói đã trượt ba lần.
    vi.mocked(startWavRecording).mockResolvedValue(recorderGia(false) as never);
    const { view, phat } = await dungProvider();
    await phat(APPROVAL_REQUIRED);

    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        view.getByTestId("stop-voice").click();
        await Promise.resolve();
        await Promise.resolve();
      });
    }

    expect(startWavRecording).toHaveBeenCalledTimes(3); // 1 lần đầu + 2 lần mở lại
  });
});
