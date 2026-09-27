// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { DriverEvent, VehicleState } from "@/lib/services/turn/types";
import { OPEN_UI_POLICY } from "@/lib/services/turn/types";
import { DriverShellProvider, useDriverShell } from "./DriverShellProvider";

/**
 * `routine.started`/`routine.step`/`routine.finished` (#290/#292) ride chung
 * `/ws/ivi` — kiểm tra provider gộp đúng thành `routineExecution`: thay thế
 * hoàn toàn khi có lần chạy mới, cập nhật đúng bước theo index, bỏ qua event
 * của một `executionId` không khớp (lần chạy cũ/trễ), khớp bất biến backend
 * "tối đa một Routine đang chạy mỗi phiên".
 */

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

const { sessionService } = await import("@/lib/services/session");
const { turnService } = await import("@/lib/services/turn");

const DRIVER_SESSION = {
  sessionId: "ses_test",
  vehicleId: "vehicle-demo-01",
  status: "active" as const,
  startedAt: "2026-01-01T00:00:00Z",
  canDrive: true,
  pool: null,
};

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

function TestConsumer() {
  const { routineExecution } = useDriverShell();
  return <pre data-testid="routine-execution">{JSON.stringify(routineExecution)}</pre>;
}

describe("DriverShellProvider — routineExecution (#290/#292)", () => {
  let emit: (event: DriverEvent) => void = () => {};

  beforeEach(() => {
    emit = () => {};
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(DRIVER_SESSION);
    vi.mocked(turnService.getVehicleState).mockResolvedValue(VEHICLE_STATE);
    vi.mocked(turnService.subscribe).mockImplementation((cb) => {
      emit = cb;
      return () => {};
    });
  });

  afterEach(() => {
    cleanup();
    vi.resetAllMocks();
  });

  async function mount() {
    render(
      <DriverShellProvider>
        <TestConsumer />
      </DriverShellProvider>,
    );
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    act(() => emit({ type: "ui.policy", uiPolicy: OPEN_UI_POLICY }));
  }

  it("routine.started tạo state mới với steps từ payload, stepResults rỗng, terminal null", async () => {
    await mount();

    act(() =>
      emit({
        type: "routine.started",
        executionId: "rex_1",
        routineId: "rtn_1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [
          { index: 0, action: "interior_light", description: "interior_light" },
          { index: 1, action: "media_control", description: "media_control" },
        ],
        startedAt: "t0",
      }),
    );

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("routine-execution").textContent ?? "null");
      expect(parsed).toEqual({
        executionId: "rex_1",
        routineId: "rtn_1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [
          { index: 0, action: "interior_light", description: "interior_light" },
          { index: 1, action: "media_control", description: "media_control" },
        ],
        stepResults: {},
        startedAt: "t0",
        terminal: null,
      });
    });
  });

  it("routine.step cập nhật đúng index, không đụng các index khác", async () => {
    await mount();
    act(() =>
      emit({
        type: "routine.started",
        executionId: "rex_1",
        routineId: "rtn_1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [
          { index: 0, action: "interior_light", description: "interior_light" },
          { index: 1, action: "media_control", description: "media_control" },
        ],
        startedAt: "t0",
      }),
    );
    act(() =>
      emit({
        type: "routine.step",
        executionId: "rex_1",
        index: 0,
        action: "interior_light",
        status: "completed",
        description: "bật đèn trần",
        errorCode: null,
      }),
    );

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("routine-execution").textContent ?? "null");
      expect(parsed.stepResults["0"]).toEqual({
        index: 0,
        action: "interior_light",
        status: "completed",
        description: "bật đèn trần",
        errorCode: null,
      });
      expect(parsed.stepResults["1"]).toBeUndefined();
    });
  });

  it("routine.step/routine.finished của executionId KHÔNG khớp bị bỏ qua (event trễ của lần chạy cũ)", async () => {
    await mount();
    act(() =>
      emit({
        type: "routine.started",
        executionId: "rex_moi",
        routineId: "rtn_1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [],
        startedAt: "t0",
      }),
    );
    act(() =>
      emit({
        type: "routine.step",
        executionId: "rex_cu",
        index: 0,
        action: "interior_light",
        status: "completed",
        description: "bật đèn trần",
        errorCode: null,
      }),
    );
    act(() =>
      emit({
        type: "routine.finished",
        executionId: "rex_cu",
        routineId: "rtn_1",
        status: "failed",
        terminalReason: "lỗi lần chạy cũ",
        results: [],
        completedAt: "t1",
        audioBase64: null,
        mimeType: null,
      }),
    );

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("routine-execution").textContent ?? "null");
      expect(parsed.executionId).toBe("rex_moi");
      expect(parsed.stepResults).toEqual({});
      expect(parsed.terminal).toBeNull();
    });
  });

  it("routine.finished khớp executionId set terminal, giữ nguyên steps/stepResults", async () => {
    await mount();
    act(() =>
      emit({
        type: "routine.started",
        executionId: "rex_1",
        routineId: "rtn_1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [{ index: 0, action: "interior_light", description: "interior_light" }],
        startedAt: "t0",
      }),
    );
    act(() =>
      emit({
        type: "routine.finished",
        executionId: "rex_1",
        routineId: "rtn_1",
        status: "completed",
        terminalReason: "completed",
        results: [{ index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null }],
        completedAt: "t1",
        audioBase64: null,
        mimeType: null,
      }),
    );

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("routine-execution").textContent ?? "null");
      expect(parsed.terminal).toEqual({ status: "completed", terminalReason: "completed", completedAt: "t1" });
      expect(parsed.executionId).toBe("rex_1");
    });
  });

  it("routine.started thứ hai THAY THẾ hoàn toàn state của lần chạy trước (đúng một execution tại một thời điểm)", async () => {
    await mount();
    act(() =>
      emit({
        type: "routine.started",
        executionId: "rex_1",
        routineId: "rtn_1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [{ index: 0, action: "interior_light", description: "interior_light" }],
        startedAt: "t0",
      }),
    );
    act(() =>
      emit({
        type: "routine.finished",
        executionId: "rex_1",
        routineId: "rtn_1",
        status: "completed",
        terminalReason: "completed",
        results: [],
        completedAt: "t1",
        audioBase64: null,
        mimeType: null,
      }),
    );
    act(() =>
      emit({
        type: "routine.started",
        executionId: "rex_2",
        routineId: "rtn_2",
        routineName: "Đi làm",
        routineVersion: 1,
        steps: [],
        startedAt: "t2",
      }),
    );

    await waitFor(() => {
      const parsed = JSON.parse(screen.getByTestId("routine-execution").textContent ?? "null");
      expect(parsed).toMatchObject({ executionId: "rex_2", routineName: "Đi làm", terminal: null });
    });
  });

  /**
   * Câu tổng kết đọc to khi Routine chạy xong (issue #396). Dùng đúng khuôn
   * `FakeAudio`/`SpyAudio` đã có ở `DriverShellProvider.test.tsx` §"ngắt lời
   * TTS" — jsdom không hỗ trợ `.play()` thật.
   */
  describe("routine.finished — audio tổng kết (#396)", () => {
    class FakeAudio extends EventTarget {
      src: string;
      constructor(src?: string) {
        super();
        this.src = src ?? "";
      }
      play() {
        return Promise.resolve();
      }
      pause() {}
    }
    let createdAudios: FakeAudio[] = [];

    beforeEach(() => {
      createdAudios = [];
      class SpyAudio extends FakeAudio {
        constructor(src?: string) {
          super(src);
          createdAudios.push(this);
        }
      }
      vi.stubGlobal("Audio", SpyAudio);
    });

    afterEach(() => {
      vi.unstubAllGlobals();
    });

    it("có audioBase64/mimeType thì tạo đúng 1 Audio với data URI khớp", async () => {
      await mount();
      act(() =>
        emit({
          type: "routine.started",
          executionId: "rex_1",
          routineId: "rtn_1",
          routineName: "Thư giãn",
          routineVersion: 1,
          steps: [],
          startedAt: "t0",
        }),
      );
      act(() =>
        emit({
          type: "routine.finished",
          executionId: "rex_1",
          routineId: "rtn_1",
          status: "completed",
          terminalReason: "completed",
          results: [],
          completedAt: "t1",
          audioBase64: "AAAA",
          mimeType: "audio/wav",
        }),
      );

      expect(createdAudios).toHaveLength(1);
      expect(createdAudios[0].src).toBe("data:audio/wav;base64,AAAA");
    });

    it("replay routine.finished không đọc lại câu tổng kết", async () => {
      await mount();
      act(() =>
        emit({
          type: "routine.started",
          executionId: "rex_1",
          routineId: "rtn_1",
          routineName: "Thư giãn",
          routineVersion: 1,
          steps: [],
          startedAt: "t0",
        }),
      );
      const finished: DriverEvent = {
        type: "routine.finished",
        executionId: "rex_1",
        routineId: "rtn_1",
        status: "completed",
        terminalReason: "completed",
        results: [],
        completedAt: "t1",
        audioBase64: "AAAA",
        mimeType: "audio/wav",
      };

      act(() => emit(finished));
      act(() => emit(finished));

      expect(createdAudios).toHaveLength(1);
    });

    it("routine.finished trễ của execution cũ không phát hoặc ngắt tiếng hiện tại", async () => {
      await mount();
      act(() =>
        emit({
          type: "routine.started",
          executionId: "rex_moi",
          routineId: "rtn_moi",
          routineName: "Đi làm",
          routineVersion: 1,
          steps: [],
          startedAt: "t0",
        }),
      );
      act(() =>
        emit({
          type: "routine.finished",
          executionId: "rex_cu",
          routineId: "rtn_cu",
          status: "completed",
          terminalReason: "completed",
          results: [],
          completedAt: "t1",
          audioBase64: "AAAA",
          mimeType: "audio/wav",
        }),
      );

      expect(createdAudios).toHaveLength(0);
    });

    it("audioBase64 null (TTS lỗi, fail-open) thì KHÔNG tạo Audio nào", async () => {
      await mount();
      act(() =>
        emit({
          type: "routine.started",
          executionId: "rex_1",
          routineId: "rtn_1",
          routineName: "Thư giãn",
          routineVersion: 1,
          steps: [],
          startedAt: "t0",
        }),
      );
      act(() =>
        emit({
          type: "routine.finished",
          executionId: "rex_1",
          routineId: "rtn_1",
          status: "completed",
          terminalReason: "completed",
          results: [],
          completedAt: "t1",
          audioBase64: null,
          mimeType: null,
        }),
      );

      expect(createdAudios).toHaveLength(0);
    });
  });
});
