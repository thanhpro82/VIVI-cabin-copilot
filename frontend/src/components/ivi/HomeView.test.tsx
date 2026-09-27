// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomeView } from "./HomeView";

/**
 * Issue #341: glow `.mic-breathe` phía sau nút mic hero từng render vô điều
 * kiện trong khi dòng chữ mời gọi bằng giọng ngay bên cạnh thì có điều kiện
 * (`wakeWordAvailable && wakeWordEnabled`) — glow "thở" ngay cả khi không có
 * gì đang nghe thật. Test này khoá cả hai nhánh cùng lúc.
 */
const shell = { wakeWordAvailable: true, wakeWordEnabled: true };

function micGlow(container: HTMLElement): HTMLElement | null {
  return container.querySelector<HTMLElement>("div[aria-hidden].mic-breathe");
}

vi.mock("./DriverShellProvider", () => ({
  useDriverShell: () => ({
    vehicleState: { hvac: { power: true }, media: { status: "idle" } },
    uiPolicy: { enlargeMicButton: false },
    openVoice: vi.fn(),
    setActiveView: vi.fn(),
    voiceOpen: false,
    wakeWordAvailable: shell.wakeWordAvailable,
    wakeWordEnabled: shell.wakeWordEnabled,
  }),
}));

describe("HomeView — glow mic chỉ thở khi wake word thật đang chạy (issue #341)", () => {
  beforeEach(() => {
    shell.wakeWordAvailable = true;
    shell.wakeWordEnabled = true;
  });

  afterEach(cleanup);

  it("dạy tài xế dùng từ Chuỗi lệnh", () => {
    render(<HomeView />);

    expect(screen.getByRole("button", { name: /Chuỗi lệnh/ })).toBeDefined();
    expect(screen.queryByText("Routines")).toBeNull();
  });

  it("cả hai bật ⇒ glow thở như cũ", () => {
    const { container } = render(<HomeView />);
    expect(micGlow(container)).not.toBeNull();
  });

  it("wakeWordAvailable === false ⇒ không có glow đang thở", () => {
    shell.wakeWordAvailable = false;
    const { container } = render(<HomeView />);
    expect(micGlow(container)).toBeNull();
  });

  it("wakeWordEnabled === false ⇒ không có glow đang thở", () => {
    shell.wakeWordEnabled = false;
    const { container } = render(<HomeView />);
    expect(micGlow(container)).toBeNull();
  });
});
