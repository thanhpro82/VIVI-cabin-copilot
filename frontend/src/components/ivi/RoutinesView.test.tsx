// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ActiveRoutinePreview, ActiveRoutineSetupRequired, RoutineExecutionState } from "./DriverShellProvider";
import type { Places } from "@/lib/services/places";
import type { Routine, RoutineExecution } from "@/lib/services/routines";
import { ServiceError } from "@/lib/services/shared/errors";
import { RoutinesView } from "./RoutinesView";

vi.mock("@/lib/services/routines", () => ({
  routinesService: {
    listRoutines: vi.fn(),
    createRoutine: vi.fn(),
    updateRoutine: vi.fn(),
    setEnabled: vi.fn(),
    deleteRoutine: vi.fn(),
    restoreDefault: vi.fn(),
    runRoutine: vi.fn(),
    getExecution: vi.fn(),
    cancelExecution: vi.fn(),
  },
}));

vi.mock("@/lib/services/places", () => ({
  placesService: {
    getPlaces: vi.fn(),
    setPlace: vi.fn(),
    clearPlace: vi.fn(),
  },
}));

vi.mock("@/lib/services/session", () => ({
  sessionService: {
    getCurrentDriverSession: vi.fn(),
  },
}));

// `RoutinesView` chỉ cần đúng một field (`routineExecution`) từ context thật
// — mock cả module thay vì bọc `<DriverShellProvider>` (bootstrap WS/session/
// wake-word phức tạp, không phải thứ những test này cần xác nhận).
let mockRoutineExecution: RoutineExecutionState | null = null;
let mockRoutinePreview: ActiveRoutinePreview | null = null;
let mockRoutineSetupRequired: ActiveRoutineSetupRequired | null = null;
vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => ({
    routineExecution: mockRoutineExecution,
    routinePreview: mockRoutinePreview,
    routineSetupRequired: mockRoutineSetupRequired,
  }),
}));

const { routinesService } = await import("@/lib/services/routines");
const { placesService } = await import("@/lib/services/places");
const { sessionService } = await import("@/lib/services/session");

const EMPTY_PLACES: Places = { home: null, office: null };

function execution(overrides: Partial<RoutineExecution> = {}): RoutineExecution {
  return {
    id: "rex_1",
    routineId: "rtn_1",
    sessionId: "ses_1",
    routineVersion: 1,
    status: "completed",
    currentIndex: 1,
    approvalId: null,
    stepsTotal: 1,
    results: [{ index: 0, action: "hvac_power", status: "completed", description: "bật điều hoà", errorCode: null }],
    terminalReason: null,
    createdAt: "t",
    updatedAt: "t",
    ...overrides,
  };
}

beforeEach(() => {
  mockRoutineExecution = null;
  mockRoutinePreview = null;
  mockRoutineSetupRequired = null;
  vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue({ sessionId: "ses_1" } as never);
});

describe("RoutinesView — preview do Agent chọn", () => {
  it("cuộn tới và làm nổi card khớp routineId", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    mockRoutinePreview = {
      turnId: "turn_1",
      preview: {
        routineId: "rtn_1",
        routineName: "Đi làm",
        steps: [{ index: 0, action: "hvac_power", description: "bật điều hòa" }],
      },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_1", name: "Đi làm" })]);

    render(<RoutinesView />);

    await screen.findByText("Đi làm");
    await waitFor(() => expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" }));
    expect(document.querySelector('[data-routine-id="rtn_1"]')?.getAttribute("data-highlighted")).toBe("true");
  });

  it("bỏ highlight sau 30 giây", async () => {
    vi.useFakeTimers();
    Element.prototype.scrollIntoView = vi.fn();
    mockRoutinePreview = {
      turnId: "turn_2",
      preview: {
        routineId: "rtn_1",
        routineName: "Đi làm",
        steps: [{ index: 0, action: "hvac_power", description: "bật điều hòa" }],
      },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_1", name: "Đi làm" })]);

    render(<RoutinesView />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(document.querySelector('[data-routine-id="rtn_1"]')?.getAttribute("data-highlighted")).toBe("true");

    act(() => vi.advanceTimersByTime(30_000));

    expect(document.querySelector('[data-routine-id="rtn_1"]')?.getAttribute("data-highlighted")).toBe("false");
    vi.useRealTimers();
  });

  it("ID chưa có trong list vẫn hiện card preview chỉ đọc từ payload backend", async () => {
    vi.useFakeTimers();
    mockRoutinePreview = {
      turnId: "turn_3",
      preview: {
        routineId: "rtn_missing",
        routineName: "Về nhà",
        steps: [{ index: 0, action: "navigation", description: "dẫn đường tới Nhà" }],
      },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_other", name: "Đi làm" })]);

    render(<RoutinesView />);

    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    const fallback = screen.getByTestId("routine-preview-fallback");
    expect(fallback.textContent).toContain("Về nhà");
    expect(fallback.textContent).toContain("dẫn đường tới Nhà");
    expect(fallback.querySelector("button")).toBeNull();
    expect(fallback.className).toContain("ring-2");

    act(() => vi.advanceTimersByTime(30_000));

    expect(fallback.className).not.toContain("ring-2");
  });
});

describe("RoutinesView — voice-run thiếu địa điểm (#385)", () => {
  it("mở thẳng PlacesPanel và làm nổi đúng hàng backend báo thiếu", async () => {
    mockRoutineSetupRequired = {
      turnId: "turn_setup_1",
      setup: { routineId: "rtn_di_lam", maLoi: "chua_dat_dia_diem", thieu: ["office"] },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_di_lam", name: "Đi làm" })]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);

    render(<RoutinesView />);

    expect(await screen.findByText("Địa điểm Nhà & Cơ quan")).toBeDefined();
    await waitFor(() => {
      const rows = document.querySelectorAll('[data-highlighted="true"]');
      expect(rows.length).toBe(1);
      expect(rows[0]?.textContent).toContain("Cơ quan");
    });
  });

  it("cả hai nhãn thiếu thì cả hai hàng nổi", async () => {
    mockRoutineSetupRequired = {
      turnId: "turn_setup_2",
      setup: { routineId: "rtn_ca_ngay", maLoi: "chua_dat_dia_diem", thieu: ["home", "office"] },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_ca_ngay", name: "Cả ngày" })]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);

    render(<RoutinesView />);

    await screen.findByText("Địa điểm Nhà & Cơ quan");
    await waitFor(() => {
      expect(document.querySelectorAll('[data-highlighted="true"]').length).toBe(2);
    });
  });

  it("mở panel bằng tay (không qua voice-run) không tự nổi hàng nào", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_1", name: "Đi làm" })]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);

    render(<RoutinesView />);
    await screen.findByText("Đi làm");
    fireEvent.click(screen.getByText("Địa điểm Nhà & Cơ quan"));

    await screen.findByText(/dùng chung hai địa điểm này/);
    expect(document.querySelectorAll('[data-highlighted="true"]').length).toBe(0);
  });

  it("gán xong địa điểm thiếu thì highlight tự hết, không cần đóng/mở lại panel", async () => {
    mockRoutineSetupRequired = {
      turnId: "turn_setup_3",
      setup: { routineId: "rtn_di_lam", maLoi: "chua_dat_dia_diem", thieu: ["office"] },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_di_lam", name: "Đi làm" })]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);
    vi.mocked(placesService.setPlace).mockResolvedValue({
      home: null,
      office: { label: "office", destinationId: "poi-work-01", name: "Cơ quan", valid: true, updatedAt: "t" },
    });

    render(<RoutinesView />);
    await waitFor(() => expect(document.querySelectorAll('[data-highlighted="true"]').length).toBe(1));

    fireEvent.click(screen.getAllByText("— Chọn địa điểm —")[1]);
    fireEvent.click(screen.getByRole("button", { name: "Cơ quan" }));

    await waitFor(() => expect(document.querySelectorAll('[data-highlighted="true"]').length).toBe(0));
    // #404 review: banner "cần địa điểm dưới đây" cũng phải hết theo, không chỉ
    // highlight của hàng — trước fix nó vẫn đọc ảnh chụp `thieu` cũ nên còn hiện.
    expect(screen.queryByText(/vừa yêu cầu chạy một chuỗi lệnh cần/)).toBeNull();
  });

  it("remount không tự mở lại panel khi địa điểm đã được gán từ trước (#404 review)", async () => {
    // `DriverShell.tsx` remount RoutinesView theo `routinePreview?.turnId` — một
    // preview không liên quan cũng làm mọi ref cục bộ (kể cả `setupOpenedForRef`)
    // reset về null. Nếu effect chỉ tin ref thì nó sẽ mở lại panel setup CŨ dù
    // địa điểm đã gán xong từ trước khi remount xảy ra.
    mockRoutineSetupRequired = {
      turnId: "turn_setup_stale",
      setup: { routineId: "rtn_di_lam", maLoi: "chua_dat_dia_diem", thieu: ["office"] },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "rtn_di_lam", name: "Đi làm" })]);
    vi.mocked(placesService.getPlaces).mockResolvedValue({
      home: null,
      office: { label: "office", destinationId: "poi-work-01", name: "Cơ quan", valid: true, updatedAt: "t" },
    });

    render(<RoutinesView />);

    await screen.findByText("Đi làm");
    // "Địa điểm Nhà & Cơ quan" cũng là nhãn nút mở panel bằng tay ở màn danh sách —
    // phải phân biệt bằng heading (chỉ PlacesPanel mới render) để không dương tính giả.
    expect(screen.queryByRole("heading", { name: "Địa điểm Nhà & Cơ quan" })).toBeNull();
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

function routine(overrides: Partial<Routine> = {}): Routine {
  return {
    id: "rtn_1",
    userId: "usr_driver_01",
    name: "Đi làm",
    icon: "briefcase",
    enabled: true,
    steps: [{ action: "hvac_power", enabled: true }],
    isDefaultTemplate: false,
    templateOrigin: null,
    needsPreview: false,
    needsSetup: false,
    runnable: true,
    version: 1,
    createdAt: "2026-08-29T00:00:00Z",
    updatedAt: "2026-08-29T00:00:00Z",
    ...overrides,
  };
}

describe("RoutinesView — danh sách", () => {
  it("hiện ba mẫu và nút Tạo chuỗi lệnh mới", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([
      routine({ id: "r1", name: "Đi làm", isDefaultTemplate: true, templateOrigin: "di_lam" }),
      routine({ id: "r2", name: "Về nhà", isDefaultTemplate: true, templateOrigin: "ve_nha" }),
      routine({ id: "r3", name: "Thư giãn", isDefaultTemplate: true, templateOrigin: "thu_gian" }),
    ]);

    render(<RoutinesView />);

    expect(await screen.findByText("Đi làm")).toBeDefined();
    expect(screen.getByText("Về nhà")).toBeDefined();
    expect(screen.getByText("Thư giãn")).toBeDefined();
    expect(screen.getByRole("button", { name: /Tạo chuỗi lệnh mới/ })).toBeDefined();
    expect(screen.getByRole("heading", { name: "Chuỗi lệnh" })).toBeDefined();
    expect(screen.getByText('Thử nói "Chạy chuỗi lệnh Thư giãn"')).toBeDefined();
  });

  it("danh sách rỗng hiện lời mời tạo Routine đầu tiên", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    render(<RoutinesView />);
    expect(await screen.findByText(/tạo chuỗi lệnh đầu tiên/)).toBeDefined();
  });

  it("needsSetup=true (backend quyết) hiện nhãn Cần thiết lập, không tự đoán từ bước navigation", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([
      routine({
        id: "r1",
        needsSetup: true,
        runnable: false,
        steps: [{ action: "navigation", destination: "home" }],
      }),
    ]);
    render(<RoutinesView />);
    expect(await screen.findByText("Cần thiết lập")).toBeDefined();
  });

  it("needsSetup=false dù có bước navigation vẫn hiện Sẵn sàng — không tự tính lại ở FE", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([
      routine({
        id: "r1",
        needsSetup: false,
        runnable: true,
        steps: [{ action: "navigation", destination: "home" }],
      }),
    ]);
    render(<RoutinesView />);
    expect(await screen.findByText("Sẵn sàng")).toBeDefined();
  });

  it("bật/tắt gọi setEnabled rồi tải lại danh sách", async () => {
    const r = routine({ id: "r1", enabled: true });
    vi.mocked(routinesService.listRoutines).mockResolvedValueOnce([r]).mockResolvedValueOnce([{ ...r, enabled: false }]);
    vi.mocked(routinesService.setEnabled).mockResolvedValue({ ...r, enabled: false });

    render(<RoutinesView />);
    const toggle = await screen.findByRole("button", { pressed: true });
    fireEvent.click(toggle);

    await waitFor(() => expect(routinesService.setEnabled).toHaveBeenCalledWith("r1", false));
    expect(routinesService.listRoutines).toHaveBeenCalledTimes(2);
  });

  it("mẫu mặc định: Khôi phục mặc định gọi restoreDefault, không có nút Xoá", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "r1", isDefaultTemplate: true, templateOrigin: "di_lam" })]);
    vi.mocked(routinesService.restoreDefault).mockResolvedValue(routine({ id: "r1", isDefaultTemplate: true }));

    render(<RoutinesView />);
    expect(await screen.findByText("Khôi phục mặc định")).toBeDefined();
    expect(screen.queryByText("Xoá")).toBeNull();

    fireEvent.click(screen.getByText("Khôi phục mặc định"));
    await waitFor(() => expect(routinesService.restoreDefault).toHaveBeenCalledWith("r1"));
  });

  it("Routine tự tạo: Xoá cần xác nhận trước khi gọi deleteRoutine", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "r1", isDefaultTemplate: false })]);
    vi.mocked(routinesService.deleteRoutine).mockResolvedValue(undefined);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Xoá"));
    expect(routinesService.deleteRoutine).not.toHaveBeenCalled();

    expect(screen.getByText("Xoá chuỗi lệnh này?")).toBeDefined();
    fireEvent.click(screen.getByText("Xác nhận xoá"));
    await waitFor(() => expect(routinesService.deleteRoutine).toHaveBeenCalledWith("r1"));
  });

  it("Xoá — bấm Thôi thì huỷ xác nhận, không gọi deleteRoutine", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([routine({ id: "r1", isDefaultTemplate: false })]);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Xoá"));
    fireEvent.click(screen.getByText("Thôi"));

    expect(screen.queryByText("Xoá chuỗi lệnh này?")).toBeNull();
    expect(routinesService.deleteRoutine).not.toHaveBeenCalled();
  });
});

describe("RoutinesView — form tạo/sửa", () => {
  it("tạo Routine mới: nhập tên, thêm một bước, submit gọi createRoutine rồi quay lại danh sách", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(routinesService.createRoutine).mockResolvedValue(routine({ id: "new" }));

    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Tạo chuỗi lệnh mới/ }));

    fireEvent.change(screen.getByPlaceholderText("Ví dụ: Đi làm"), { target: { value: "Đi chơi" } });
    fireEvent.click(screen.getByText("+ Bật/tắt điều hoà"));
    fireEvent.click(screen.getByText("Tạo chuỗi lệnh"));

    await waitFor(() =>
      expect(routinesService.createRoutine).toHaveBeenCalledWith({
        name: "Đi chơi",
        icon: "sun",
        steps: [{ action: "hvac_power", enabled: true }],
      }),
    );
    // Submit xong quay lại danh sách (form không còn hiện trường Tên chuỗi lệnh).
    await waitFor(() => expect(screen.queryByPlaceholderText("Ví dụ: Đi làm")).toBeNull());
  });

  it("sửa Routine có sẵn: form nạp đúng dữ liệu cũ, submit gọi updateRoutine với đúng id", async () => {
    const existing = routine({ id: "r1", name: "Đi làm", steps: [{ action: "hvac_temperature", temperatureC: 24 }] });
    vi.mocked(routinesService.listRoutines).mockResolvedValue([existing]);
    vi.mocked(routinesService.updateRoutine).mockResolvedValue(existing);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Sửa"));

    const nameInput = screen.getByPlaceholderText("Ví dụ: Đi làm") as HTMLInputElement;
    expect(nameInput.value).toBe("Đi làm");
    expect(screen.getByText("Nhiệt độ: 24°C")).toBeDefined();

    fireEvent.change(nameInput, { target: { value: "Đi làm sớm" } });
    fireEvent.click(screen.getByText("Lưu thay đổi"));

    await waitFor(() =>
      expect(routinesService.updateRoutine).toHaveBeenCalledWith("r1", {
        name: "Đi làm sớm",
        icon: "briefcase",
        steps: [{ action: "hvac_temperature", temperatureC: 24 }],
      }),
    );
  });

  it("lỗi từ service (ROUTINE_NAME_DUPLICATE) hiện message, không rời khỏi form", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(routinesService.createRoutine).mockRejectedValue(
      new ServiceError({ code: "ROUTINE_NAME_DUPLICATE", message: "Đã có Routine khác trùng tên này.", retryable: true }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Tạo chuỗi lệnh mới/ }));
    fireEvent.change(screen.getByPlaceholderText("Ví dụ: Đi làm"), { target: { value: "Đi làm" } });
    fireEvent.click(screen.getByText("+ Bật/tắt điều hoà"));
    fireEvent.click(screen.getByText("Tạo chuỗi lệnh"));

    expect(await screen.findByText("Đã có Routine khác trùng tên này.")).toBeDefined();
    // Vẫn ở form — trường Tên chuỗi lệnh còn nguyên giá trị vừa nhập.
    expect(screen.getByPlaceholderText("Ví dụ: Đi làm")).toBeDefined();
  });

  it("giới hạn 4 bước: nút thêm bị khoá khi đã đủ, không cho vượt MAX_STEPS", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Tạo chuỗi lệnh mới/ }));

    const addHvacPower = screen.getByText("+ Bật/tắt điều hoà");
    fireEvent.click(addHvacPower);
    fireEvent.click(addHvacPower);
    fireEvent.click(addHvacPower);
    fireEvent.click(addHvacPower);

    expect(screen.getByText("Các bước (4/4)")).toBeDefined();
    expect((addHvacPower as HTMLButtonElement).disabled).toBe(true);

    // "Sưởi ghế (cả hai)" cần 2 slot — cũng phải bị khoá khi chỉ còn 0 chỗ trống.
    const addBothSeats = screen.getByText("+ Sưởi ghế (cả hai)");
    expect((addBothSeats as HTMLButtonElement).disabled).toBe(true);
  });

  it("Huỷ quay lại danh sách, không gọi createRoutine", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    render(<RoutinesView />);
    fireEvent.click(await screen.findByRole("button", { name: /Tạo chuỗi lệnh mới/ }));
    fireEvent.click(screen.getByText("Huỷ"));

    expect(screen.queryByPlaceholderText("Ví dụ: Đi làm")).toBeNull();
    expect(routinesService.createRoutine).not.toHaveBeenCalled();
  });
});

describe("RoutinesView — địa điểm Nhà/Cơ quan (#284)", () => {
  it("mở màn địa điểm hiện đúng ba trạng thái: chưa gán, hợp lệ, và đích đã biến mất", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(placesService.getPlaces).mockResolvedValue({
      home: { label: "home", destinationId: "poi-home-01", name: "Nhà", valid: true, updatedAt: "t" },
      office: { label: "office", destinationId: "poi-cu", name: null, valid: false, updatedAt: "t" },
    });

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Địa điểm Nhà & Cơ quan"));

    expect(await screen.findByText("Hiện tại: Nhà")).toBeDefined();
    expect(screen.getByText(/không còn trong danh sách offline/)).toBeDefined();
  });

  it("cả hai chưa gán -> hiện 'Chưa thiết lập' cho cả Nhà và Cơ quan, không có nút Bỏ gán", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Địa điểm Nhà & Cơ quan"));

    expect(await screen.findAllByText(/Chưa thiết lập/)).toHaveLength(2);
    expect(screen.queryByText("Bỏ gán")).toBeNull();
  });

  it("chọn một địa điểm cho Nhà gọi setPlace(\"home\", id) và cập nhật hiển thị", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);
    vi.mocked(placesService.setPlace).mockResolvedValue({
      home: { label: "home", destinationId: "poi-home-01", name: "Nhà", valid: true, updatedAt: "t" },
      office: null,
    });

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Địa điểm Nhà & Cơ quan"));
    await screen.findAllByText(/Chưa thiết lập/);

    // Hàng "Nhà" đứng trước hàng "Cơ quan" — dropdown đầu tiên là của Nhà.
    const selects = screen.getAllByText("— Chọn địa điểm —");
    fireEvent.click(selects[0]);
    fireEvent.click(screen.getByRole("button", { name: "Nhà" })); // "Nhà" là tên POI poi-home-01 trong fixture

    await waitFor(() => expect(placesService.setPlace).toHaveBeenCalledWith("home", "poi-home-01"));
    expect(await screen.findByText("Hiện tại: Nhà")).toBeDefined();
  });

  it("Bỏ gán gọi clearPlace rồi tải lại", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(placesService.getPlaces)
      .mockResolvedValueOnce({
        home: { label: "home", destinationId: "poi-home-01", name: "Nhà", valid: true, updatedAt: "t" },
        office: null,
      })
      .mockResolvedValueOnce(EMPTY_PLACES);
    vi.mocked(placesService.clearPlace).mockResolvedValue(undefined);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Địa điểm Nhà & Cơ quan"));
    fireEvent.click(await screen.findByText("Bỏ gán"));

    await waitFor(() => expect(placesService.clearPlace).toHaveBeenCalledWith("home"));
    expect(await screen.findAllByText(/Chưa thiết lập/)).toHaveLength(2);
  });

  it("lỗi PLACE_DESTINATION_INVALID hiện message, không làm sập màn", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);
    vi.mocked(placesService.setPlace).mockRejectedValue(
      new ServiceError({ code: "PLACE_DESTINATION_INVALID", message: "Điểm đến không hợp lệ.", retryable: true }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Địa điểm Nhà & Cơ quan"));
    await screen.findAllByText(/Chưa thiết lập/);

    fireEvent.click(screen.getAllByText("— Chọn địa điểm —")[0]);
    fireEvent.click(screen.getByRole("button", { name: "Nhà" }));

    expect(await screen.findByText("Điểm đến không hợp lệ.")).toBeDefined();
  });

  it("Đóng quay lại danh sách và tải lại Routines (needs_setup có thể vừa đổi)", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([]);
    vi.mocked(placesService.getPlaces).mockResolvedValue(EMPTY_PLACES);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Địa điểm Nhà & Cơ quan"));
    await screen.findAllByText(/Chưa thiết lập/);
    expect(routinesService.listRoutines).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByText("Đóng"));

    expect(screen.queryByText(/Chưa thiết lập/)).toBeNull();
    await waitFor(() => expect(routinesService.listRoutines).toHaveBeenCalledTimes(2));
  });
});

const TWO_STEP_ROUTINE = routine({
  id: "r1",
  name: "Thư giãn",
  runnable: true,
  steps: [
    { action: "interior_light", enabled: true },
    { action: "media_control", controlAction: "play" },
  ],
});

describe("RoutinesView — chạy Routine, panel tiến độ (#292)", () => {
  it("routine.runnable=false không hiện nút Chạy chuỗi lệnh", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([{ ...TWO_STEP_ROUTINE, runnable: false }]);
    render(<RoutinesView />);
    await screen.findByText("Thư giãn");
    expect(screen.queryByText("Chạy chuỗi lệnh")).toBeNull();
  });

  it("bấm Chạy chuỗi lệnh gọi runRoutine đúng id/sessionId, mở panel với x/y từ routine.steps đã có sẵn", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
    vi.mocked(routinesService.runRoutine).mockResolvedValue(
      execution({ id: "rex_1", routineId: "r1", status: "running", currentIndex: 0, stepsTotal: 2, results: [] }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));

    await waitFor(() => expect(routinesService.runRoutine).toHaveBeenCalledWith("r1", "ses_1"));
    expect(await screen.findByText("Thư giãn", { selector: "h2" })).toBeDefined();
    // Chưa có kết quả nào (results rỗng) -> cả hai bước "Chờ", 0/2.
    expect(screen.getByText("0/2 bước")).toBeDefined();
    expect(screen.getAllByText("Chờ")).toHaveLength(2);
    expect(screen.getByText("Đang chạy…")).toBeDefined();
  });

  it("chưa có phiên lái -> báo lỗi, KHÔNG gọi runRoutine", async () => {
    vi.mocked(sessionService.getCurrentDriverSession).mockReturnValue(undefined as never);
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));

    expect(await screen.findByText("Chưa có phiên lái — không thể chạy chuỗi lệnh.")).toBeDefined();
    expect(routinesService.runRoutine).not.toHaveBeenCalled();
  });

  it("lỗi ROUTINE_NEEDS_SETUP hiện message, không chuyển sang panel chạy", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
    vi.mocked(routinesService.runRoutine).mockRejectedValue(
      new ServiceError({ code: "ROUTINE_NEEDS_SETUP", message: "Chuỗi lệnh thiếu địa điểm.", retryable: false }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));

    expect(await screen.findByText("Chuỗi lệnh thiếu địa điểm.")).toBeDefined();
    expect(screen.getByText("Thư giãn")).toBeDefined();
    expect(screen.queryByText("Đang chạy…")).toBeNull();
  });

  it("WS live khớp executionId đè lên snapshot REST — hiện đúng tổng kết routine.finished", async () => {
    mockRoutineExecution = {
      executionId: "rex_1",
      routineId: "r1",
      routineName: "Thư giãn",
      routineVersion: 1,
      steps: [
        { index: 0, action: "interior_light", description: "interior_light" },
        { index: 1, action: "media_control", description: "media_control" },
      ],
      stepResults: {
        0: { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null },
        1: { index: 1, action: "media_control", status: "completed", description: "phát nhạc", errorCode: null },
      },
      startedAt: "t",
      terminal: { status: "completed", terminalReason: "completed", completedAt: "t" },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
    // Snapshot REST ban đầu (lúc 202 trả về) còn "running", 0 kết quả — WS phải đè lên, không phải ngược lại.
    vi.mocked(routinesService.runRoutine).mockResolvedValue(
      execution({ id: "rex_1", routineId: "r1", status: "running", currentIndex: 0, stepsTotal: 2, results: [] }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));

    expect(await screen.findByText("Chuỗi lệnh đã hoàn tất")).toBeDefined();
    expect(screen.getByText("2/2 bước")).toBeDefined();
    expect(screen.getByText("bật đèn trần")).toBeDefined();
    expect(screen.getByText("phát nhạc")).toBeDefined();
    expect(screen.getAllByText("Hoàn tất")).toHaveLength(2);
  });

  it("WS live của execution KHÁC (chưa tới lần mới) không ảnh hưởng panel đang xem", async () => {
    mockRoutineExecution = {
      executionId: "rex_cu",
      routineId: "r1",
      routineName: "Thư giãn",
      routineVersion: 1,
      steps: [],
      stepResults: {},
      startedAt: "t",
      terminal: { status: "failed", terminalReason: "lỗi cũ", completedAt: "t" },
    };
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
    vi.mocked(routinesService.runRoutine).mockResolvedValue(
      execution({ id: "rex_moi", routineId: "r1", status: "running", currentIndex: 0, stepsTotal: 2, results: [] }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));

    // Không được hiện tổng kết của execution cũ (rex_cu) cho lần chạy mới (rex_moi).
    expect(await screen.findByText("Đang chạy…")).toBeDefined();
    expect(screen.queryByText("Chuỗi lệnh thất bại")).toBeNull();
  });

  it("mất routine.finished qua WS -> panel poll REST getExecution và tự thoát 'Đang chạy…' khi REST báo terminal (P1 review PR #379)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
      vi.mocked(routinesService.runRoutine).mockResolvedValue(
        execution({ id: "rex_1", routineId: "r1", status: "running", currentIndex: 0, stepsTotal: 2, results: [] }),
      );
      // Không WS nào tới (mockRoutineExecution giữ null suốt bài) — mô phỏng đúng
      // ca PM nêu: kênh WS chập chờn/mất routine.finished.
      vi.mocked(routinesService.getExecution).mockResolvedValue(
        execution({
          id: "rex_1",
          routineId: "r1",
          status: "completed",
          currentIndex: 2,
          stepsTotal: 2,
          results: [
            { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null },
            { index: 1, action: "media_control", status: "completed", description: "phát nhạc", errorCode: null },
          ],
        }),
      );

      render(<RoutinesView />);
      fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));
      await screen.findByText("Đang chạy…");
      expect(routinesService.getExecution).not.toHaveBeenCalled();

      await vi.advanceTimersByTimeAsync(3000);

      expect(routinesService.getExecution).toHaveBeenCalledWith("rex_1");
      expect(await screen.findByText("Chuỗi lệnh đã hoàn tất")).toBeDefined();
      expect(screen.getByText("bật đèn trần")).toBeDefined();
      expect(screen.getByText("phát nhạc")).toBeDefined();

      // Đã biết terminal -> effect tự clearInterval bên trong callback, không còn poll tiếp.
      const callsAfterTerminal = vi.mocked(routinesService.getExecution).mock.calls.length;
      await vi.advanceTimersByTimeAsync(10000);
      expect(routinesService.getExecution).toHaveBeenCalledTimes(callsAfterTerminal);
    } finally {
      vi.useRealTimers();
    }
  });

  it("WS gửi routine.started (executionId khớp) nhưng mất routine.finished -> REST terminal vẫn phải thắng, không kẹt vì live.terminal=null (P1 review PR #379 lần 2)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
      vi.mocked(routinesService.runRoutine).mockResolvedValue(
        execution({ id: "rex_1", routineId: "r1", status: "running", currentIndex: 0, stepsTotal: 2, results: [] }),
      );
      vi.mocked(routinesService.getExecution).mockResolvedValue(
        execution({
          id: "rex_1",
          routineId: "r1",
          status: "completed",
          currentIndex: 2,
          stepsTotal: 2,
          results: [
            { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null },
            { index: 1, action: "media_control", status: "completed", description: "phát nhạc", errorCode: null },
          ],
        }),
      );

      render(<RoutinesView />);
      fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));
      await screen.findByText("Đang chạy…");

      // Kênh WS còn sống tới mức gửi được routine.started/routine.step cho ĐÚNG
      // execution đang xem (executionId khớp -> `matches` đúng ở RunningRoutinePanel)
      // nhưng rớt kết nối trước khi routine.finished tới — live.terminal mãi null.
      // Đây chính là ca bản vá lần 1 (P1 review PR #379) chưa xử lý: khi đó code cũ
      // luôn ưu tiên `live.terminal` một khi `matches` đúng, bỏ qua REST đã terminal.
      mockRoutineExecution = {
        executionId: "rex_1",
        routineId: "r1",
        routineName: "Thư giãn",
        routineVersion: 1,
        steps: [
          { index: 0, action: "interior_light", description: "interior_light" },
          { index: 1, action: "media_control", description: "media_control" },
        ],
        stepResults: {
          0: { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null },
        },
        startedAt: "t",
        terminal: null,
      };

      await vi.advanceTimersByTimeAsync(3000);

      expect(routinesService.getExecution).toHaveBeenCalledWith("rex_1");
      // REST đã biết terminal -> phải thắng dù WS (cùng executionId) vẫn "matches"
      // và chưa từng gửi routine.finished.
      expect(await screen.findByText("Chuỗi lệnh đã hoàn tất")).toBeDefined();
      expect(screen.getByText("bật đèn trần")).toBeDefined();
      expect(screen.getByText("phát nhạc")).toBeDefined();

      // REST đã terminal (đầy đủ 2/2) -> không còn cần WS đè lên nữa, cũng không poll tiếp.
      const callsAfterTerminal = vi.mocked(routinesService.getExecution).mock.calls.length;
      await vi.advanceTimersByTimeAsync(10000);
      expect(routinesService.getExecution).toHaveBeenCalledTimes(callsAfterTerminal);
    } finally {
      vi.useRealTimers();
    }
  });

  it("Đóng panel quay lại danh sách", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
    vi.mocked(routinesService.runRoutine).mockResolvedValue(execution({ id: "rex_1", routineId: "r1", results: [] }));

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));
    await screen.findByText("Thư giãn", { selector: "h2" });

    fireEvent.click(screen.getByText("Đóng"));

    expect(screen.queryByText("Thư giãn", { selector: "h2" })).toBeNull();
    expect(screen.getByText("Chuỗi lệnh")).toBeDefined();
  });
});

describe("RoutinesView — Dừng chuỗi lệnh (#298)", () => {
  async function renderRunning() {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([TWO_STEP_ROUTINE]);
    vi.mocked(routinesService.runRoutine).mockResolvedValue(
      execution({ id: "rex_1", routineId: "r1", status: "running", currentIndex: 0, stepsTotal: 2, results: [] }),
    );
    const view = render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Chạy chuỗi lệnh"));
    await screen.findByText("Đang chạy…");
    return view;
  }

  it("run đang active luôn thấy nút Dừng chuỗi lệnh, chưa bấm thì không khoá", async () => {
    await renderRunning();
    const stopButton = screen.getByText("Dừng chuỗi lệnh") as HTMLButtonElement;
    expect(stopButton.disabled).toBe(false);
  });

  it("bấm Dừng gọi cancelExecution đúng executionId, khoá nút và đổi chữ", async () => {
    vi.mocked(routinesService.cancelExecution).mockResolvedValue(execution({ id: "rex_1", status: "running" }));
    await renderRunning();

    fireEvent.click(screen.getByText("Dừng chuỗi lệnh"));

    await waitFor(() => expect(routinesService.cancelExecution).toHaveBeenCalledWith("rex_1"));
    const button = await screen.findByText("Đang dừng…");
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("double-submit: bấm liên tiếp trước khi resolve chỉ gọi cancelExecution đúng một lần", async () => {
    let resolveCancel!: (v: RoutineExecution) => void;
    vi.mocked(routinesService.cancelExecution).mockReturnValue(
      new Promise<RoutineExecution>((resolve) => {
        resolveCancel = resolve;
      }),
    );
    await renderRunning();

    const button = screen.getByText("Dừng chuỗi lệnh");
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);

    expect(routinesService.cancelExecution).toHaveBeenCalledTimes(1);
    resolveCancel(execution({ id: "rex_1", status: "running" }));
  });

  it("race: bấm lại sau khi request đầu ĐÃ resolve (còn 'requested', chưa terminal) vẫn không gọi lần hai", async () => {
    vi.mocked(routinesService.cancelExecution).mockResolvedValue(execution({ id: "rex_1", status: "running" }));
    await renderRunning();

    fireEvent.click(screen.getByText("Dừng chuỗi lệnh"));
    await screen.findByText("Đang dừng…");
    fireEvent.click(screen.getByText("Đang dừng…"));

    expect(routinesService.cancelExecution).toHaveBeenCalledTimes(1);
  });

  it("lỗi mạng/offline: hiện message và MỞ LẠI nút để thử lại", async () => {
    vi.mocked(routinesService.cancelExecution).mockRejectedValue(
      new ServiceError({ code: "NETWORK_ERROR", message: "Mất kết nối mạng.", retryable: true }),
    );
    await renderRunning();

    fireEvent.click(screen.getByText("Dừng chuỗi lệnh"));

    expect(await screen.findByText("Mất kết nối mạng.")).toBeDefined();
    const retryButton = screen.getByText("Dừng chuỗi lệnh") as HTMLButtonElement;
    expect(retryButton.disabled).toBe(false);
  });

  it("routine.finished tới (terminal) thì ẩn hẳn nút Dừng, không còn 'Đang chạy…'", async () => {
    vi.mocked(routinesService.cancelExecution).mockResolvedValue(execution({ id: "rex_1", status: "running" }));
    const { rerender } = await renderRunning();
    fireEvent.click(screen.getByText("Dừng chuỗi lệnh"));
    await screen.findByText("Đang dừng…");

    mockRoutineExecution = {
      executionId: "rex_1",
      routineId: "r1",
      routineName: "Thư giãn",
      routineVersion: 1,
      steps: [],
      stepResults: {},
      startedAt: "t",
      terminal: { status: "user_canceled", terminalReason: "user_canceled", completedAt: "t" },
    };
    // Mock module không tự phát tín hiệu re-render — buộc vẽ lại để đọc
    // `mockRoutineExecution` mới, đúng cách `useDriverShell()` thật sẽ trigger
    // re-render khi context value đổi (ở đây ta tự châm ngòi thay vì chờ).
    rerender(<RoutinesView />);

    await waitFor(() => expect(screen.getByText("Chuỗi lệnh đã dừng")).toBeDefined());
    expect(screen.queryByText("Dừng chuỗi lệnh")).toBeNull();
    expect(screen.queryByText(/Đang (chạy|dừng)/)).toBeNull();
  });

  it("không tuyên bố rollback: luôn hiện dòng cảnh báo bước đã chạy không bị hoàn tác", async () => {
    await renderRunning();
    expect(screen.getByText(/không bị hoàn tác/)).toBeDefined();
  });

  it("xoá Routine đang chạy (409 ROUTINE_RUNNING) đưa thẳng sang panel đang chạy của execution đó", async () => {
    vi.mocked(routinesService.listRoutines).mockResolvedValue([{ ...TWO_STEP_ROUTINE, isDefaultTemplate: false }]);
    vi.mocked(routinesService.deleteRoutine).mockRejectedValue(
      new ServiceError({
        code: "ROUTINE_RUNNING",
        message: "Routine đang chạy — hãy dừng lần chạy đó trước khi xoá",
        retryable: true,
        details: { execution_id: "rex_dang_chay" },
      }),
    );
    vi.mocked(routinesService.getExecution).mockResolvedValue(
      execution({ id: "rex_dang_chay", routineId: "r1", status: "running", results: [] }),
    );

    render(<RoutinesView />);
    fireEvent.click(await screen.findByText("Xoá"));
    fireEvent.click(screen.getByText("Xác nhận xoá"));

    await waitFor(() => expect(routinesService.getExecution).toHaveBeenCalledWith("rex_dang_chay"));
    expect(await screen.findByText("Thư giãn", { selector: "h2" })).toBeDefined();
    expect(screen.getByText("Dừng chuỗi lệnh")).toBeDefined();
  });
});
