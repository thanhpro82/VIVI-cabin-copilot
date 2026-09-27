// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { VehicleProfileChip } from "./VehicleProfileChip";
import type { VehicleProfile, VehicleProfileUpdate } from "@/lib/services/engineer";

const UNSET: VehicleProfile = {
  vehicleId: "vehicle-demo-01",
  trim: null,
  battery: null,
  isComplete: false,
  updatedAt: null,
};

const getVehicleProfile = vi.fn<() => Promise<VehicleProfile>>();
const setVehicleProfile = vi.fn<(u: VehicleProfileUpdate) => Promise<VehicleProfile>>();

// Component chỉ được chạm service qua index.ts (CLAUDE.md: không import mock/real
// trực tiếp), nên mock đúng cửa đó.
vi.mock("@/lib/services/engineer", () => ({
  engineerService: {
    getVehicleProfile: () => getVehicleProfile(),
    setVehicleProfile: (u: VehicleProfileUpdate) => setVehicleProfile(u),
  },
}));

beforeEach(() => {
  getVehicleProfile.mockReset().mockResolvedValue(UNSET);
  setVehicleProfile.mockReset().mockImplementation(async (u) => ({
    ...UNSET,
    trim: u.trim,
    battery: u.battery,
    isComplete: u.trim !== null && u.battery !== null,
    updatedAt: "2026-08-16T04:12:00+00:00",
  }));
});

afterEach(cleanup);

function chip() {
  return screen.getByRole("button", { name: /VF9/ });
}
async function openPopover() {
  await waitFor(() => expect(chip()).toBeDefined());
  fireEvent.click(chip());
  await waitFor(() => expect(screen.getByRole("dialog")).toBeDefined());
}
function trimSelect() {
  return screen.getByLabelText("Phiên bản") as HTMLSelectElement;
}
function batterySelect() {
  return screen.getByLabelText("Loại pin") as HTMLSelectElement;
}

describe("VehicleProfileChip — nhãn thường trực", () => {
  /**
   * Lý do cả thiết kế này tồn tại: chưa khai báo cấu hình thì **mọi câu trả lời áp
   * suất lốp trong nhật ký bên dưới đều là câu fail-closed**. Trạng thái đó phải
   * đọc được mà không cần bấm vào đâu — giấu sau một tab là giấu đúng cái cần thấy.
   */
  it("chưa cấu hình: nói thẳng trên header, không cần mở popover", async () => {
    render(<VehicleProfileChip />);

    await waitFor(() => expect(chip().textContent).toMatch(/chưa khai báo cấu hình/));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("đã cấu hình: hiện đúng cặp trim · pin", async () => {
    getVehicleProfile.mockResolvedValue({ ...UNSET, trim: "plus", battery: "catl", isComplete: true });
    render(<VehicleProfileChip />);

    await waitFor(() => expect(chip().textContent).toMatch(/PLUS · CATL/));
  });

  /**
   * `is_complete` là quyết định của backend. Nửa cặp vẫn là "chưa khai báo" — nhãn
   * không được tự suy ra một trạng thái dễ nhìn hơn sự thật.
   */
  it("nửa cặp vẫn là chưa khai báo, không hiện PLUS · —", async () => {
    getVehicleProfile.mockResolvedValue({ ...UNSET, trim: "plus", battery: null, isComplete: false });
    render(<VehicleProfileChip />);

    await waitFor(() => expect(chip().textContent).toMatch(/chưa khai báo cấu hình/));
  });

  it("đọc hỏng thì nói là chưa đọc được, không im lặng thành chưa cấu hình", async () => {
    getVehicleProfile.mockRejectedValue(new Error("Không đọc được cấu hình xe."));
    render(<VehicleProfileChip />);

    await waitFor(() => expect(chip().textContent).toMatch(/chưa đọc được cấu hình/));
  });
});

describe("VehicleProfileChip — popover sửa cấu hình", () => {
  it("bấm chip mở popover, Escape đóng lại", async () => {
    render(<VehicleProfileChip />);
    await openPopover();

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("bấm ra ngoài thì đóng", async () => {
    render(<VehicleProfileChip />);
    await openPopover();

    fireEvent.mouseDown(document.body);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  /**
   * Form KHÔNG được tự chọn sẵn ECO/SDI. Một form điền sẵn khiến engineer tin xe đã
   * khai báo trong khi backend vẫn đang fail-closed.
   */
  it("chưa cấu hình: cả hai lựa chọn để trống và nút lưu bị khoá", async () => {
    render(<VehicleProfileChip />);
    await openPopover();

    expect(trimSelect().value).toBe("");
    expect(batterySelect().value).toBe("");
    expect(screen.getByText(/không đoán số/)).toBeDefined();

    const save = screen.getByRole("button", { name: "Lưu cấu hình" });
    expect(save).toHaveProperty("disabled", true);
    fireEvent.click(save);
    expect(setVehicleProfile).not.toHaveBeenCalled();
  });

  it("chọn ECO + SDI rồi lưu thì gửi đúng payload và nhãn chip đổi theo", async () => {
    render(<VehicleProfileChip />);
    await openPopover();

    fireEvent.change(trimSelect(), { target: { value: "eco" } });
    fireEvent.change(batterySelect(), { target: { value: "sdi" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu cấu hình" }));

    await waitFor(() => expect(setVehicleProfile).toHaveBeenCalledWith({ trim: "eco", battery: "sdi" }));
    await waitFor(() => expect(chip().textContent).toMatch(/ECO · SDI/));
  });

  it("đổi sang PLUS + CATL gửi lại cặp mới, không giữ giá trị cũ", async () => {
    getVehicleProfile.mockResolvedValue({ ...UNSET, trim: "eco", battery: "sdi", isComplete: true });
    render(<VehicleProfileChip />);
    await openPopover();
    expect(trimSelect().value).toBe("eco");

    fireEvent.change(trimSelect(), { target: { value: "plus" } });
    fireEvent.change(batterySelect(), { target: { value: "catl" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu cấu hình" }));

    await waitFor(() => expect(setVehicleProfile).toHaveBeenCalledWith({ trim: "plus", battery: "catl" }));
  });

  /**
   * Nửa cặp phải đi được tới Backend đúng như engineer chọn. FE không "giúp" bằng
   * cách chặn hay tự điền nốt — `is_complete` là việc của Backend, và ca nửa cặp
   * chính là ca phải thấy kết quả fail-closed.
   */
  it("chọn nửa cặp vẫn gửi được, nửa còn lại là null", async () => {
    render(<VehicleProfileChip />);
    await openPopover();

    fireEvent.change(trimSelect(), { target: { value: "plus" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu cấu hình" }));

    await waitFor(() => expect(setVehicleProfile).toHaveBeenCalledWith({ trim: "plus", battery: null }));
    await waitFor(() => expect(chip().textContent).toMatch(/chưa khai báo cấu hình/));
  });

  it("xoá cấu hình gửi null cho cả hai và chip quay về chưa khai báo", async () => {
    getVehicleProfile.mockResolvedValue({ ...UNSET, trim: "eco", battery: "sdi", isComplete: true });
    render(<VehicleProfileChip />);
    await openPopover();

    fireEvent.click(screen.getByRole("button", { name: "Xoá cấu hình" }));

    await waitFor(() => expect(setVehicleProfile).toHaveBeenCalledWith({ trim: null, battery: null }));
    await waitFor(() => expect(chip().textContent).toMatch(/chưa khai báo cấu hình/));
  });

  /**
   * Ghi là engineer-only (`require_engineer`). Khi Backend từ chối, popover phải nói
   * ra chứ không im lặng giữ nguyên lựa chọn trên form — engineer sẽ tưởng đã lưu
   * rồi đổ lỗi cho câu trả lời áp suất ở lượt sau.
   */
  it("Backend từ chối thì hiện lỗi và chip không tự nhận là đã cấu hình", async () => {
    setVehicleProfile.mockRejectedValue(new Error("Chỉ engineer được đổi cấu hình xe."));
    render(<VehicleProfileChip />);
    await openPopover();

    fireEvent.change(trimSelect(), { target: { value: "eco" } });
    fireEvent.change(batterySelect(), { target: { value: "sdi" } });
    fireEvent.click(screen.getByRole("button", { name: "Lưu cấu hình" }));

    await waitFor(() => expect(screen.getByText(/Chỉ engineer được đổi cấu hình xe/)).toBeDefined());
    expect(chip().textContent).toMatch(/chưa khai báo cấu hình/);
  });
});
