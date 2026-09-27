// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatTileRow } from "./StatTileRow";
import * as shell from "./EngineerShellProvider";
import type { EvalSnapshot } from "@/lib/services/engineer";

afterEach(cleanup);

function stub(evalSnapshot: EvalSnapshot | null) {
  vi.spyOn(shell, "useEngineerShell").mockReturnValue({
    metrics: null,
    evalSnapshot,
  } as never);
}

const RUN_DAY_DU: EvalSnapshot = {
  suite: "rag",
  runId: "20260827T172523Z",
  metrics: { grounded_rate: 1.0, hallucination_rate: 0.05, citation_validity: 1.0 },
  gradedBy: "dap_an_khoa",
  dataset: null,
  note: null,
};

describe("StatTileRow", () => {
  it("khong co snapshot thi hien dau gach, khong hien so mock cu", () => {
    stub(null);
    render(<StatTileRow />);

    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
    // 92,4% va 7,5% la hai so hard-code cua offlineEval.ts — chung khong duoc
    // song sot o bat ky nhanh nao.
    expect(screen.queryByText(/92[.,]4/)).toBeNull();
    expect(screen.queryByText(/7[.,]5%/)).toBeNull();
  });

  it("co snapshot thi hien so kem run id va nguon cham", () => {
    stub(RUN_DAY_DU);
    render(<StatTileRow />);

    expect(screen.getByText("5.0%")).toBeTruthy();
    expect(screen.getByText(/20260827T172523Z/)).toBeTruthy();
    expect(screen.getByText(/dap_an_khoa/)).toBeTruthy();
  });

  it("metric thieu trong run cu van hien dau gach chu khong hien 0%", () => {
    stub({ ...RUN_DAY_DU, runId: "20260814T005140Z", metrics: { hallucination_rate: 0.05 } });
    render(<StatTileRow />);

    // O co so thi hien so; hai o thieu metric thi hien dau gach — khong phai 0%.
    expect(screen.getByText("5.0%")).toBeTruthy();
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("0.0%")).toBeNull();
  });

  it("run khong co manifest thi nguon cham hien dau gach, khong doan", () => {
    stub({ ...RUN_DAY_DU, gradedBy: null });
    render(<StatTileRow />);

    expect(screen.getByText(/20260827T172523Z · —/)).toBeTruthy();
  });
});
