// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertBanner } from "./AlertBanner";
import * as shell from "./EngineerShellProvider";
import type { EvalSnapshot } from "@/lib/services/engineer";

afterEach(cleanup);

function stub(evalSnapshot: EvalSnapshot | null) {
  vi.spyOn(shell, "useEngineerShell").mockReturnValue({
    metrics: null,
    health: null,
    streamError: null,
    evalSnapshot,
  } as never);
}

const BASE: EvalSnapshot = {
  suite: "rag",
  runId: "r1",
  metrics: {},
  gradedBy: "dap_an_khoa",
  dataset: null,
  note: null,
};

describe("AlertBanner — cảnh báo tỷ lệ bịa", () => {
  it("khong co snapshot thi khong canh bao — khong the bao dong ve so chua co", () => {
    stub(null);
    const { container } = render(<AlertBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("ty le bia duoi nguong thi im lang", () => {
    stub({ ...BASE, metrics: { hallucination_rate: 0.05 } });
    const { container } = render(<AlertBanner />);
    expect(container.firstChild).toBeNull();
  });

  it("ty le bia vuot nguong thi canh bao kem run id", () => {
    stub({ ...BASE, runId: "20260814T005140Z", metrics: { hallucination_rate: 0.18 } });
    render(<AlertBanner />);
    expect(screen.getByText(/18\.0%/)).toBeTruthy();
    expect(screen.getByText(/20260814T005140Z/)).toBeTruthy();
  });
});
