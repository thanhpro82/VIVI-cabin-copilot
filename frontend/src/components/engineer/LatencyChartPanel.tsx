"use client";

import { useEngineerShell } from "./EngineerShellProvider";

/** Biểu đồ thanh ngang p50/p95 theo từng stage thật (stageLatencyMs) — 1 trục, 2 chuỗi cố định thứ tự (p50/p95), không dual-axis. Dùng div/flexbox thay SVG viewBox — tránh méo hình khi container không cùng tỉ lệ. */
export function LatencyChartPanel() {
  const { metrics } = useEngineerShell();
  // "end_to_end" là tổng cả pipeline, không phải 1 chặng riêng — tách hiện ở
  // StatTileRow, không lặp lại ở đây để tránh trông như 1 chặng dài bất thường.
  const stages = metrics
    ? Object.entries(metrics.stageLatencyMs).filter(([name]) => name !== "end_to_end")
    : [];

  if (stages.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center rounded-(--r-md) border border-dashed border-line text-sm text-ink-dim">
        Chưa có dữ liệu độ trễ
      </div>
    );
  }

  const maxMs = Math.max(...stages.map(([, s]) => s.p95 ?? s.p50 ?? 0), 1);

  return (
    <div className="flex flex-1 flex-col gap-4 rounded-(--r-md) border border-line bg-panel-solid p-4">
      <div className="flex items-center justify-between">
        <p className="font-technical text-[10px] tracking-widest text-ink-dim uppercase">
          Độ trễ theo chặng
        </p>
        <div className="flex items-center gap-3 font-technical text-[10px] text-ink-soft">
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-cyan" /> p50
          </span>
          <span className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-amber" /> p95
          </span>
        </div>
      </div>
      <div className="flex flex-col gap-3.5">
        {stages.map(([name, stat]) => {
          const p50Percent = stat.p50 != null ? Math.max((stat.p50 / maxMs) * 100, 2) : 0;
          const p95Percent = stat.p95 != null ? Math.max((stat.p95 / maxMs) * 100, 2) : 0;
          return (
            <div key={name} className="flex flex-col gap-1">
              <div className="flex items-center justify-between font-technical text-[10.5px]">
                <span className="text-ink-soft">{name}</span>
                <span className="text-ink-dim">
                  {stat.p50 ?? "—"}ms / {stat.p95 ?? "—"}ms
                </span>
              </div>
              <div className="flex flex-col gap-1">
                <div className="h-2 w-full rounded-full bg-line">
                  <div
                    className="h-full rounded-full bg-amber"
                    style={{ width: `${p95Percent}%` }}
                  />
                </div>
                <div className="h-2 w-full rounded-full bg-line">
                  <div
                    className="h-full rounded-full bg-cyan"
                    style={{ width: `${p50Percent}%` }}
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
