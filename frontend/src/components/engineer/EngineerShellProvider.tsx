"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { engineerService } from "@/lib/services/engineer";
import type { EngineerLogEntry, EvalSnapshot, HealthStatus, MetricsSummary } from "@/lib/services/engineer/types";

const LOG_BUFFER_CAP = 200;
export const FILTER_ALL = "all";

interface EngineerShellValue {
  metrics: MetricsSummary | null;
  /**
   * Ảnh chụp run eval mới nhất. `null` = chưa có run nào đọc được — trạng thái
   * bình thường, không phải lỗi, và UI phải hiện `—` chứ không hiện số cũ.
   */
  evalSnapshot: EvalSnapshot | null;
  health: HealthStatus | null;
  /** Lỗi terminal từ `/ws/engineer` — trước đây bị `default: break` nuốt hoàn toàn. */
  streamError: string | null;
  logs: EngineerLogEntry[];
  filteredLogs: EngineerLogEntry[];
  routeFilter: string;
  setRouteFilter: (v: string) => void;
  statusFilter: string;
  setStatusFilter: (v: string) => void;
  routeOptions: string[];
  statusOptions: string[];
  exportCsv: () => void;
}

const EngineerShellContext = createContext<EngineerShellValue | null>(null);

export function useEngineerShell(): EngineerShellValue {
  const ctx = useContext(EngineerShellContext);
  if (!ctx) throw new Error("useEngineerShell phải dùng trong EngineerShellProvider");
  return ctx;
}

function downloadCsv(filename: string, rows: string[][]) {
  const content = rows
    .map((row) => row.map((cell) => `"${cell.replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Orchestrator state cho /engineer — 1 lần subscribe engineerService, ring
 * buffer log ~200 dòng gần nhất (docs/ARCHITECTURE.md mục 6.1). KHÔNG phải
 * historical log viewer — chỉ log từ khi mở phiên làm việc.
 */
export function EngineerShellProvider({ children }: { children: ReactNode }) {
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [evalSnapshot, setEvalSnapshot] = useState<EvalSnapshot | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [logs, setLogs] = useState<EngineerLogEntry[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [routeFilter, setRouteFilter] = useState(FILTER_ALL);
  const [statusFilter, setStatusFilter] = useState(FILTER_ALL);

  useEffect(() => {
    // getMetricsSummary/getHealth có thể 404/503 khi BE thiếu route hoặc
    // dependency chưa sẵn sàng — không throw ra ngoài effect, giữ metrics/health
    // ở null để UI tự hiện placeholder thay vì unhandled rejection.
    engineerService.getMetricsSummary().then(setMetrics).catch(() => setMetrics(null));
    engineerService.getHealth().then(setHealth).catch(() => setHealth(null));
    // Nạp MỘT lần khi mở màn hình, không poll: snapshot chỉ đổi khi có người chạy
    // eval — khác hẳn `metrics`, vốn đổi theo từng lượt. Poll ở đây là gọi vô ích.
    engineerService.getEvalSnapshot("rag").then(setEvalSnapshot).catch(() => setEvalSnapshot(null));

    const unsubscribe = engineerService.subscribe((event) => {
      switch (event.type) {
        case "trace":
          setLogs((prev) => [event.entry, ...prev].slice(0, LOG_BUFFER_CAP));
          break;
        case "metrics":
          setMetrics(event.summary);
          break;
        case "health":
          setHealth(event.health);
          break;
        case "error":
          // Trước đây rơi vào `default: break` — socket bị đóng vì token/quyền mà
          // dashboard chỉ đơn giản ngừng cập nhật, không dấu hiệu nào. Lỗi xác
          // thực còn được `engineer/real.ts` báo riêng để đá về /login; dòng này
          // lo phần còn lại (và phần hiển thị cho chính ca đó nếu điều hướng chậm).
          setStreamError(event.message);
          break;
        default:
          break;
      }
    });

    return unsubscribe;
  }, []);

  const routeOptions = useMemo(
    () => Array.from(new Set(logs.map((l) => l.routeSource ?? "unknown"))).sort(),
    [logs],
  );
  const statusOptions = useMemo(
    () => Array.from(new Set(logs.map((l) => l.status))).sort(),
    [logs],
  );

  const filteredLogs = useMemo(() => {
    return logs.filter((l) => {
      const okRoute = routeFilter === FILTER_ALL || (l.routeSource ?? "unknown") === routeFilter;
      const okStatus = statusFilter === FILTER_ALL || l.status === statusFilter;
      return okRoute && okStatus;
    });
  }, [logs, routeFilter, statusFilter]);

  const exportCsv = useCallback(() => {
    // Xe và câu trả lời có mặt trong CSV kể cả khi bảng không hiện chúng thành
    // cột riêng: soi chất lượng trả lời hàng loạt là việc làm trên file, không
    // phải việc rê chuột qua từng tooltip.
    const header = [
      "Thời gian",
      "Trace ID",
      "Xe",
      "Tóm tắt",
      "Trả lời",
      "Nguồn",
      "Xác nhận",
      "Trạng thái",
      "Độ trễ (ms)",
    ];
    const rows = filteredLogs.map((l) => [
      l.time,
      l.traceId,
      l.vehicleId ?? "",
      l.safeSummary,
      l.answerText ?? "",
      l.routeSource ?? "",
      l.approvalStatus ?? "",
      l.status,
      l.latencyMs != null ? String(l.latencyMs) : "",
    ]);
    downloadCsv(`vivi_nhat_ky_${Date.now()}.csv`, [header, ...rows]);
  }, [filteredLogs]);

  return (
    <EngineerShellContext.Provider
      value={{
        metrics,
        evalSnapshot,
        health,
        streamError,
        logs,
        filteredLogs,
        routeFilter,
        setRouteFilter,
        statusFilter,
        setStatusFilter,
        routeOptions,
        statusOptions,
        exportCsv,
      }}
    >
      {children}
    </EngineerShellContext.Provider>
  );
}
