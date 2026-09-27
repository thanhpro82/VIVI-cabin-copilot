"use client";

import { EngineerShellProvider } from "./EngineerShellProvider";
import { EngineerHeader } from "./EngineerHeader";
import { AlertBanner } from "./AlertBanner";
import { StatTileRow } from "./StatTileRow";
import { LatencyChartPanel } from "./LatencyChartPanel";
import { LogsFilterBar } from "./LogsFilterBar";
import { LogsTable } from "./LogsTable";

/** Dashboard Kỹ sư — theo docs/ARCHITECTURE.md mục 6. */
export function EngineerDashboard() {
  return (
    <EngineerShellProvider>
      <div
        className="flex h-screen flex-col"
        style={{
          background:
            "radial-gradient(ellipse 900px 600px at 85% 0%, rgba(56,189,248,.045), transparent 60%), var(--bg)",
        }}
      >
        <EngineerHeader />
        <div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
          <AlertBanner />
          <StatTileRow />
          <div className="flex min-h-0 flex-1 gap-3">
            <div className="flex w-1/4 min-w-80 shrink-0 flex-col">
              <LatencyChartPanel />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-3">
              <LogsFilterBar />
              <LogsTable />
            </div>
          </div>
        </div>
      </div>
    </EngineerShellProvider>
  );
}
