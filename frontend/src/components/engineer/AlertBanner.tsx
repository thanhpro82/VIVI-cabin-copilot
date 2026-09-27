"use client";

import { useEngineerShell } from "./EngineerShellProvider";

/** Ngưỡng theo PRD — xem docs/ARCHITECTURE.md mục 6.2. */
const THRESHOLD = {
  groundedRateMin: 0.9, // N5
  latencyP50MaxMs: 3000, // N1
  hallucinationRateMax: 0.1, // N6
};

export function AlertBanner() {
  const { metrics, health, streamError, evalSnapshot } = useEngineerShell();

  const alerts: string[] = [];

  // Đứng đầu danh sách: một stream đã chết làm mọi số bên dưới thành số cũ, nên
  // nó quan trọng hơn bất kỳ ngưỡng nào đang bị vượt.
  if (streamError) alerts.push(`Luồng dữ liệu kỹ sư đã dừng: ${streamError}`);

  if (metrics) {
    if (metrics.rag.groundedRate != null && metrics.rag.groundedRate < THRESHOLD.groundedRateMin) {
      alerts.push(
        `Grounded Rate ${(metrics.rag.groundedRate * 100).toFixed(1)}% dưới ngưỡng ${THRESHOLD.groundedRateMin * 100}%`,
      );
    }
    const p50 = metrics.stageLatencyMs.end_to_end?.p50;
    if (p50 != null && p50 > THRESHOLD.latencyP50MaxMs) {
      alerts.push(`Độ trễ p50 ${p50}ms vượt ngưỡng ${THRESHOLD.latencyP50MaxMs}ms`);
    }
  }

  // Không có snapshot, hoặc run cũ không đo chỉ số này, thì **không cảnh báo**:
  // báo động về một con số chưa có là dựng ra một sự cố không tồn tại. Run id đi
  // kèm để người đọc biết cảnh báo này nói về lần chấm nào — nó có thể đã cũ.
  const tyLeBia = evalSnapshot?.metrics.hallucination_rate;
  if (typeof tyLeBia === "number" && tyLeBia > THRESHOLD.hallucinationRateMax) {
    alerts.push(
      `Tỷ lệ bịa (offline, run ${evalSnapshot!.runId}) ${(tyLeBia * 100).toFixed(1)}%` +
        ` vượt ngưỡng ${THRESHOLD.hallucinationRateMax * 100}%`,
    );
  }

  if (health) {
    const degraded = Object.entries(health.components).filter(([, c]) => c.status !== "ready");
    if (degraded.length > 0) {
      alerts.push(`${degraded.length} thành phần không sẵn sàng: ${degraded.map(([k]) => k).join(", ")}`);
    }
  }

  if (alerts.length === 0) return null;

  return (
    <div className="flex items-center gap-2.5 rounded-(--r-md) border border-accent bg-accent/8 px-4 py-3 text-[12.5px] text-accent">
      <span>●</span>
      <span>
        <b>{alerts.length} cảnh báo</b> — {alerts[0]}
        {alerts.length > 1 ? ` (+${alerts.length - 1} khác)` : ""}
      </span>
    </div>
  );
}
