// @vitest-environment jsdom
/**
 * Hộp thoại duyệt chỉ được đóng bởi **lượt của chính nó** — và phải tự hết hạn.
 *
 * Người dùng báo từ test tay 20/08: *"nếu nhận diện sai ở phần HITL thì phần phê duyệt
 * đó bị bỏ qua và không thể truy cập lại; các lệnh phê duyệt sau đó thì toàn báo là
 * đang có lệnh phê duyệt đang chờ."*
 *
 * Hai triệu chứng, một gốc. Nhánh terminal đóng hộp thoại cho **mọi** `turn.completed`
 * / `turn.canceled` / `turn.failed`, bất kể lượt nào — nên một câu nói chệch giữa lúc
 * chờ duyệt (rơi xuống tra sổ tay hoặc tán gẫu) kết thúc bình thường và **cuốn theo hộp
 * thoại**. Phía server phê duyệt vẫn treo nguyên, và vì mỗi phiên chỉ được một phê
 * duyệt chờ, mọi lệnh S2 sau đó nhận `approval_already_pending` cho tới lúc nó hết hạn.
 *
 * Đo trên backend thật cùng ngày, cùng một phiên:
 *
 *     mở kính bên lái 30%   -> waiting_approval
 *     xin chào              -> completed          (lượt lạc, KHÔNG đụng phê duyệt)
 *     mở kính bên phụ 40%   -> "Đang có một lệnh chờ bạn xác nhận"
 *     ...33 giây sau...     -> waiting_approval    (server tự mở khoá khi hết hạn)
 *
 * Tức server đúng; chỗ hỏng là client. Hai ca đặc biệt đã được vá trước đây
 * (`APPROVAL_INTENT_AMBIGUOUS` ở #147, "chờ chạm" ở #207) là hai trường hợp riêng của
 * đúng luật chung mà file này khoá.
 */
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

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

const PHIEN = { sessionId: "ses_1", vehicleId: "vehicle-demo-01", status: "active", startedAt: "2026-01-01T00:00:00Z" };

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

const TTL_MS = 30_000;

function duyetCanXacNhan(): DriverEvent {
  return {
    type: "approval.required",
    turnId: "turn_goc",
    approvalId: "appr-1",
    planId: "plan-1",
    approvedVehicleStateVersion: 3,
    expiresAt: new Date(Date.now() + TTL_MS).toISOString(),
  };
}

function Consumer() {
  const { pendingApproval, toast } = useDriverShell();
  return (
    <>
      <span data-testid="cho-duyet">{pendingApproval ? pendingApproval.approvalId : "khong"}</span>
      <span data-testid="toast">{toast ?? ""}</span>
    </>
  );
}

async function dungProvider() {
  let phat: (event: DriverEvent) => void = () => {};
  vi.mocked(turnService.subscribe).mockImplementation((cb) => {
    phat = cb;
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
    /** Bắn event **không** bọc `act` — để dựng được khe giữa lúc handler chạy (ref đã
     *  đổi, đồng bộ) và lúc React flush effect (cleanup mới huỷ hẹn giờ cũ). */
    phatTho: (event: DriverEvent) => phat(event),
  };
}

const choDuyet = (view: ReturnType<typeof render>) => view.getByTestId("cho-duyet").textContent;

describe("hộp thoại duyệt", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
    vi.mocked(startWavRecording).mockResolvedValue({
      stop: vi.fn().mockResolvedValue(new Blob()),
      cancel: vi.fn(),
      hadSpeech: () => true,
    } as never);
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("một lượt KHÁC kết thúc thì hộp thoại còn nguyên", async () => {
    // Đúng ca người dùng gặp: nói chệch một câu giữa lúc chờ duyệt, câu ấy rơi xuống
    // tán gẫu và kết thúc bình thường. Nó không liên quan gì tới phê duyệt, nên nó
    // không được phép lấy đi đường duy nhất để tài xế quyết.
    const { view, phat } = await dungProvider();
    await phat(duyetCanXacNhan());
    expect(choDuyet(view)).toBe("appr-1");

    await phat({ type: "turn.completed", turnId: "turn_tan_gau" });

    expect(choDuyet(view)).toBe("appr-1");
  });

  it("lượt hỏng của người khác cũng không được cuốn theo hộp thoại", async () => {
    // `turn.failed` của một lượt ghi âm rỗng là ca thật và hay gặp nhất khi test tay.
    const { view, phat } = await dungProvider();
    await phat(duyetCanXacNhan());

    await phat({ type: "turn.failed", turnId: "turn_ghi_am_hong", code: "STT_FAILED" });

    expect(choDuyet(view)).toBe("appr-1");
  });

  it("lượt GỐC kết thúc thì hộp thoại đóng — đó là đường đóng đúng", async () => {
    // Duyệt xong, server resume đúng lượt đã sinh ra phê duyệt rồi kết thúc nó. Đây là
    // nửa còn lại: siết luật mà cắt mất đường này thì hộp thoại không bao giờ đóng.
    const { view, phat } = await dungProvider();
    await phat(duyetCanXacNhan());

    await phat({ type: "turn.completed", turnId: "turn_goc" });

    expect(choDuyet(view)).toBe("khong");
  });

  it("từ chối: turn.canceled của lượt gốc cũng đóng hộp thoại", async () => {
    const { view, phat } = await dungProvider();
    await phat(duyetCanXacNhan());

    await phat({ type: "turn.canceled", turnId: "turn_goc", reason: "approval_rejected" });

    expect(choDuyet(view)).toBe("khong");
  });

  it("hết hạn thì hộp thoại tự gỡ và nói ra lý do", async () => {
    // Thứ dọn một hộp thoại đã chết TRƯỚC bản này là "một lượt bất kỳ khác kết thúc" —
    // đúng cái vừa bị bỏ. Không có effect hết hạn thì hộp thoại nằm lại mãi, và hai nút
    // của nó chỉ dẫn tới `APPROVAL_EXPIRED`.
    vi.useFakeTimers();
    const { view, phat } = await dungProvider();
    await phat(duyetCanXacNhan());
    expect(choDuyet(view)).toBe("appr-1");

    await act(async () => {
      vi.advanceTimersByTime(TTL_MS + 2500);
      await Promise.resolve();
    });

    expect(choDuyet(view)).toBe("khong");
    expect(view.getByTestId("toast").textContent).toContain("Hết thời gian");
  });

  it("hẹn giờ của phê duyệt CŨ không được gỡ hộp thoại của phê duyệt MỚI", async () => {
    // Ca @thanhpro82 nêu ở review #219, cùng lớp rủi ro với bug gốc: A hết hạn, rồi
    // trong 2 giây nới thì B tới. Hẹn giờ đã đặt cho A không được phép chạm vào B.
    vi.useFakeTimers();
    const { view, phat, phatTho } = await dungProvider();
    await phat(duyetCanXacNhan());
    expect(choDuyet(view)).toBe("appr-1");

    // Qua mốc hết hạn của A, nhưng CHƯA tới mốc gỡ (30 s + 2 s nới).
    await act(async () => {
      vi.advanceTimersByTime(TTL_MS + 1000);
      await Promise.resolve();
    });

    // B tới trong khe ấy — và hẹn giờ của A đến hạn **trước khi React kịp flush effect**.
    //
    // Đây là chỗ duy nhất guard theo `approvalId` có tác dụng, nên test phải dựng đúng
    // nó: `phatTho` chạy handler ngoài `act` (ref đã trỏ sang B, đồng bộ), rồi đẩy đồng
    // hồ **trong cùng một act** trước khi cleanup của effect kịp huỷ hẹn giờ của A.
    // Bọc `act` quanh mỗi bước như bình thường thì cleanup chạy trước và test xanh dù
    // có guard hay không — tức không kiểm được gì.
    await act(async () => {
      phatTho({
        ...duyetCanXacNhan(),
        turnId: "turn_goc_2",
        approvalId: "appr-2",
        expiresAt: new Date(Date.now() + TTL_MS).toISOString(),
      } as DriverEvent);
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
    });

    expect(choDuyet(view)).toBe("appr-2");
    expect(view.getByTestId("toast").textContent).not.toContain("Hết thời gian");
  });

  it("chưa tới hạn thì KHÔNG gỡ sớm", async () => {
    // Nới hai giây là để chịu lệch đồng hồ server/trình duyệt; gỡ sớm là mất một lệnh
    // của tài xế, còn giữ lâu hơn một chút thì cùng lắm là nghe "xác nhận đã hết hạn".
    vi.useFakeTimers();
    const { view, phat } = await dungProvider();
    await phat(duyetCanXacNhan());

    await act(async () => {
      vi.advanceTimersByTime(TTL_MS - 1000);
      await Promise.resolve();
    });

    expect(choDuyet(view)).toBe("appr-1");
  });
});
