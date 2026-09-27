// @vitest-environment jsdom
/**
 * Tự chuyển màn theo giọng nói — hai nhịp (#174).
 *
 * Nhịp 1: `plan.ready` chỉ GHI NHỚ `steps`, tuyệt đối không đổi màn.
 * Nhịp 2: `tool.result` với `status="completed"` mới tra `stepId` rồi đổi màn.
 *
 * Vì sao phải tách hai nhịp: `plan.ready` thuộc giai đoạn định tuyến, phát TRƯỚC
 * khi rẽ nhánh chính sách, nên nó bắn cho cả lượt S3. Bám nó thì nói "mở
 * YouTube" lúc xe đang chạy sẽ MỞ VIDEO XONG rồi mới bị chặn — luật an toàn của
 * ADR-023 thành trang trí.
 *
 * Test "lượt bị chặn" bên dưới là test duy nhất đỏ nếu ai đó sau này "dọn dẹp"
 * bằng cách chuyển màn ngay ở `plan.ready`. Đừng bỏ nó.
 */
import { act, cleanup, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, ToolResultStatus } from "@/lib/services/turn/types";
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

const { sessionService } = await import("@/lib/services/session");
const { turnService } = await import("@/lib/services/turn");

const PHIEN = {
  sessionId: "ses_view_1",
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

interface BuocTho {
  stepId: string;
  tool: string;
  domain: string | null;
  args?: Record<string, unknown>;
}

function planReady(steps: BuocTho[]): DriverEvent {
  return {
    type: "plan.ready",
    turnId: "turn_1",
    routeKind: "action",
    planId: "plan_1",
    summary: "làm gì đó",
    requiresApproval: false,
    steps: steps.map((step) => ({ ...step, args: step.args ?? {} })),
  };
}

function toolResult(stepId: string, status: ToolResultStatus): DriverEvent {
  return { type: "tool.result", turnId: "turn_1", stepId, status, errorCode: status === "completed" ? null : "failed" };
}

let datManThuCong: ReturnType<typeof useDriverShell>["setActiveView"] | null = null;

function ManDangXem() {
  const { activeView, setActiveView } = useDriverShell();
  useEffect(() => {
    datManThuCong = setActiveView;
  }, [setActiveView]);
  return <span data-testid="man">{activeView}</span>;
}

function man(): string {
  return screen.getByTestId("man").textContent ?? "";
}

async function dungProvider() {
  let goi: (event: DriverEvent) => void = () => {};
  vi.mocked(turnService.subscribe).mockImplementation((cb) => {
    goi = cb;
    return () => {};
  });
  render(
    <DriverShellProvider>
      <ManDangXem />
    </DriverShellProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  return {
    phat: async (event: DriverEvent) => {
      await act(async () => {
        goi(event);
        await Promise.resolve();
      });
    },
  };
}

describe("tự chuyển màn theo tool.result", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("plan.ready MỘT MÌNH không đổi màn", async () => {
    const { phat } = await dungProvider();
    expect(man()).toBe("home");

    await phat(planReady([{ stepId: "s1", tool: "set_hvac_power", domain: "hvac" }]));

    expect(man()).toBe("home");
  });

  it.each([
    ["set_hvac_power", "hvac", "vehicle"],
    ["media_control", "media", "music"],
    ["set_navigation", "navigation", "map"],
  ])("%s (domain %s) completed thì sang màn %s", async (tool, domain, view) => {
    const { phat } = await dungProvider();

    await phat(planReady([{ stepId: "s1", tool, domain }]));
    await phat(toolResult("s1", "completed"));

    expect(man()).toBe(view);
  });

  it("open_app completed thì sang đúng app — đọc args vì domain là null", async () => {
    const { phat } = await dungProvider();

    await phat(
      planReady([{ stepId: "s1", tool: "open_app", domain: null, args: { app: "youtube" } }]),
    );
    await phat(toolResult("s1", "completed"));

    expect(man()).toBe("youtube");
  });

  it("LƯỢT BỊ CHẶN: plan.ready có open_app rồi action.blocked, không tool.result — màn KHÔNG đổi", async () => {
    // Đây là test đỏ nếu ai đó chuyển màn ở `plan.ready`. Kịch bản thật: nói
    // "mở YouTube" khi xe không ở số P thì ADR-023 hạ xuống S3 và chặn trước
    // khi thực thi. Nếu màn đã nhảy sang YouTube thì luật an toàn chỉ còn là chữ.
    const { phat } = await dungProvider();

    await phat(
      planReady([{ stepId: "s1", tool: "open_app", domain: null, args: { app: "youtube" } }]),
    );
    await phat({ type: "action.blocked", turnId: "turn_1", reason: "safety_blocked" });

    expect(man()).toBe("home");
  });

  it.each<ToolResultStatus>([
    "failed",
    "timeout",
    "skipped_due_to_prior_failure",
    "skipped_external_state_change",
  ])("trạng thái %s không đổi màn — chỉ completed mới chứng minh việc đã xảy ra", async (status) => {
    const { phat } = await dungProvider();

    await phat(planReady([{ stepId: "s1", tool: "media_control", domain: "media" }]));
    await phat(toolResult("s1", status));

    expect(man()).toBe("home");
  });

  it("kế hoạch nhiều bước dừng ở bước completed ĐẦU TIÊN có ánh xạ", async () => {
    // "bật điều hòa rồi mở nhạc": không có cờ chống nháy thì màn nhảy sang
    // vehicle rồi lập tức sang music, tài xế không kịp đọc gì.
    const { phat } = await dungProvider();

    await phat(
      planReady([
        { stepId: "s1", tool: "set_hvac_power", domain: "hvac" },
        { stepId: "s2", tool: "media_control", domain: "media" },
      ]),
    );
    await phat(toolResult("s1", "completed"));
    await phat(toolResult("s2", "completed"));

    expect(man()).toBe("vehicle");
  });

  it("bước không có ánh xạ không chiếm mất lượt của bước sau", async () => {
    // `query_manual` trả null; nếu cờ chống nháy bật ngay ở bước đó thì bước
    // điều khiển phía sau sẽ không bao giờ đổi được màn.
    const { phat } = await dungProvider();

    await phat(
      planReady([
        { stepId: "s1", tool: "query_manual", domain: null },
        { stepId: "s2", tool: "set_navigation", domain: "navigation" },
      ]),
    );
    await phat(toolResult("s1", "completed"));
    await phat(toolResult("s2", "completed"));

    expect(man()).toBe("map");
  });

  it("lượt MỚI được đổi màn lại — cờ chống nháy reset theo plan.ready", async () => {
    const { phat } = await dungProvider();

    await phat(planReady([{ stepId: "s1", tool: "media_control", domain: "media" }]));
    await phat(toolResult("s1", "completed"));
    expect(man()).toBe("music");

    await phat(planReady([{ stepId: "s9", tool: "set_navigation", domain: "navigation" }]));
    await phat(toolResult("s9", "completed"));
    expect(man()).toBe("map");
  });

  it("tool.result tới mà chưa có plan.ready thì giữ nguyên màn, không đoán", async () => {
    const { phat } = await dungProvider();

    await phat(toolResult("s-la", "completed"));

    expect(man()).toBe("home");
  });
});

/**
 * Tự chuyển màn khi Routine có bước navigation (#294 review — phát hiện lúc test
 * spike: chạy Routine "Về nhà" không hề chuyển sang màn Bản đồ).
 *
 * Khác `tool.result`: đợi tới `routine.finished` mới đổi màn, không đổi ngay khi
 * bước navigation completed. Routine có panel tiến độ riêng của chính nó (#276
 * "UI giữ chi tiết") — đổi màn giữa chừng sẽ unmount panel đó trước khi các bước
 * sau kịp hiện xong.
 */
describe("tự chuyển màn khi Routine có bước navigation", () => {
  beforeEach(() => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(PHIEN as never);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(TRANG_THAI_XE as never);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  function routineStarted(executionId: string): DriverEvent {
    return {
      type: "routine.started",
      executionId,
      routineId: "rt_ve_nha",
      routineName: "Về nhà",
      routineVersion: 1,
      steps: [
        { index: 0, action: "navigation", description: "dẫn đường tới Nhà" },
        { index: 1, action: "hvac_power", description: "bật điều hòa" },
      ],
      startedAt: "2026-01-01T00:00:00Z",
    };
  }

  function routineStep(executionId: string, index: number, action: string, status: "completed" | "failed"): DriverEvent {
    return { type: "routine.step", executionId, index, action, status, description: "", errorCode: null };
  }

  function routineFinished(executionId: string): DriverEvent {
    return {
      type: "routine.finished",
      executionId,
      routineId: "rt_ve_nha",
      status: "completed",
      terminalReason: null,
      results: [],
      completedAt: "2026-01-01T00:00:01Z",
      // Không có câu tổng kết đọc to (#396): bộ test này chỉ đo phép đổi màn,
      // và `null` là đúng nhánh fail-open mà backend trả khi TTS lỗi/rỗng.
      audioBase64: null,
      mimeType: null,
    };
  }

  it("bước navigation completed MỘT MÌNH chưa đổi màn — đợi routine.finished", async () => {
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_1"));
    await phat(routineStep("rex_1", 0, "navigation", "completed"));

    expect(man()).toBe("home");
  });

  it("routine.finished sau bước navigation completed thì sang màn Bản đồ", async () => {
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_1"));
    await phat(routineStep("rex_1", 0, "navigation", "completed"));
    await phat(routineStep("rex_1", 1, "hvac_power", "completed"));
    await phat(routineFinished("rex_1"));

    expect(man()).toBe("map");
  });

  it("routine không có bước navigation thì không đổi màn", async () => {
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_2"));
    await phat(routineStep("rex_2", 1, "hvac_power", "completed"));
    await phat(routineFinished("rex_2"));

    expect(man()).toBe("home");
  });

  it("bước navigation FAILED không đổi màn — chỉ completed mới chứng minh việc đã xảy ra", async () => {
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_3"));
    await phat(routineStep("rex_3", 0, "navigation", "failed"));
    await phat(routineFinished("rex_3"));

    expect(man()).toBe("home");
  });

  it("lần chạy MỚI reset đúng cờ — lần trước có navigation, lần này không thì không đổi màn nữa", async () => {
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_4"));
    await phat(routineStep("rex_4", 0, "navigation", "completed"));
    await phat(routineFinished("rex_4"));
    expect(man()).toBe("map");

    // Đổi tay sang màn khác để lượt sau CÓ chỗ mà chứng minh nó không tự nhảy
    // lại — nếu để nguyên "map" thì lượt sau không đổi màn cũng ra "map", test
    // không phân biệt được "cờ đã reset đúng" với "cờ vẫn còn true từ lượt cũ".
    await act(async () => {
      datManThuCong?.("home");
    });
    expect(man()).toBe("home");

    await phat(routineStarted("rex_5"));
    await phat(routineStep("rex_5", 1, "hvac_power", "completed"));
    await phat(routineFinished("rex_5"));

    expect(man()).toBe("home");
  });

  it("bước navigation TRỄ của lần chạy CŨ không làm lần chạy MỚI đổi màn (#395 review)", async () => {
    // A bắt đầu và có navigation, nhưng sự kiện completed của nó tới TRỄ — sau
    // khi B đã bắt đầu. B không có navigation. Nếu cờ không so executionId thì
    // routine.finished của B vẫn đổi màn dựa trên bước navigation của A.
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_A"));
    await phat(routineStarted("rex_B"));
    await phat(routineStep("rex_A", 0, "navigation", "completed"));
    await phat(routineStep("rex_B", 0, "hvac_power", "completed"));
    await phat(routineFinished("rex_B"));

    expect(man()).toBe("home");
  });

  it("CẢ CẶP sự kiện trễ của lần chạy CŨ cũng không cướp màn của lần chạy đang chạy (#395 review vòng 2)", async () => {
    // Khác ca ngay trên ở chỗ lần chạy cũ tự đi trọn vòng đời của nó khi tới muộn:
    // cả `navigation/completed` LẪN `routine.finished` đều là của A. Phép so
    // `routineNavCompletedRef.current === event.executionId` một mình vẫn lọt, vì
    // A tự khớp với chính A — nên màn nhảy sang Bản đồ trong khi B mới là thứ
    // đang chạy và đang hiển thị. Cổng "có phải lần chạy đang hiển thị không"
    // mới là thứ chặn được ca này.
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_A"));
    await phat(routineStarted("rex_B"));
    await phat(routineStep("rex_A", 0, "navigation", "completed"));
    await phat(routineFinished("rex_A"));

    expect(man()).toBe("home");
  });

  it("routine.finished phát lại không đổi màn lần thứ hai — tiêu chí replay của #276", async () => {
    const { phat } = await dungProvider();

    await phat(routineStarted("rex_6"));
    await phat(routineStep("rex_6", 0, "navigation", "completed"));
    await phat(routineFinished("rex_6"));
    expect(man()).toBe("map");

    await act(async () => {
      datManThuCong?.("home");
    });
    await phat(routineFinished("rex_6"));

    expect(man()).toBe("home");
  });
});
