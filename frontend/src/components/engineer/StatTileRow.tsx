"use client";

import type { ReactNode } from "react";
import { useEngineerShell } from "./EngineerShellProvider";

interface Tile {
  label: string;
  value: string;
  detail: string;
  pass: boolean | null;
}

function Tile({ label, value, detail, pass }: Tile) {
  return (
    <div className="flex-1 rounded-(--r-md) border border-line bg-panel-solid p-4">
      <p className="font-technical text-[10px] tracking-widest text-ink-dim uppercase">{label}</p>
      <p className="mt-1.5 font-technical text-[28px] font-semibold text-ink">{value}</p>
      <p className={`mt-1 text-[11px] ${pass === null ? "text-ink-soft" : pass ? "text-green" : "text-accent"}`}>
        {pass === null ? "—" : pass ? "▲ " : "▼ "}
        {detail}
      </p>
    </div>
  );
}

function Group({ label, sub, children }: { label: string; sub?: string; children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col gap-2">
      <p className="font-technical text-[10px] tracking-widest text-ink-dim uppercase">
        {label}
        {sub && <span className="ml-1.5 normal-case text-ink-dim/70">· {sub}</span>}
      </p>
      <div className="flex flex-1 gap-3">{children}</div>
    </div>
  );
}

/** `—` cho mọi thứ không phải số. "Chưa đo" phải trông khác "đo được 0". */
function pct(v: number | string | null | undefined): string {
  return typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "—";
}

/** `null` khi không có số — ô hiện `—` thay vì một màu đúng/sai dựng trên hư không. */
function dat(v: number | string | null | undefined, kiem: (n: number) => boolean): boolean | null {
  return typeof v === "number" ? kiem(v) : null;
}

/**
 * Một hàng ngang, hai khối tách biệt rõ nhãn — Live và Đánh giá offline **không**
 * gộp chung (docs/ARCHITECTURE.md mục 6.2). Lý do không phải bố cục mà là ngữ
 * nghĩa: khối Live fold traffic vừa xảy ra trên chính máy này, khối kia phát lại
 * một phép đo đã đóng gói trên bộ đề có đáp án khoá. Hai loại số không cộng được.
 *
 * KHÔNG CÓ Ô "ĐỘ CHÍNH XÁC Ý ĐỊNH" — cố ý, xem spec 2026-08-28 §3.2. Số thật của
 * nó là `intent_accuracy = 1.0000` trên bộ `agent/v3`, mà manifest của chính run
 * đó ghi "Router luật, không gọi model. Không phải bằng chứng chất lượng SLM" và
 * CLAUDE.md xếp bộ đó là tripwire hồi quy do chính tác giả router soạn. Đưa 100%
 * lên dashboard còn dễ bị trích dẫn sai hơn con số mock 92,4% mà nó thay thế, vì
 * nó có vẻ có nguồn.
 */
export function StatTileRow() {
  const { metrics, evalSnapshot } = useEngineerShell();

  const coTrichDan = metrics?.rag.groundedRate ?? null;
  const p50 = metrics?.stageLatencyMs.end_to_end?.p50 ?? null;

  const m = evalSnapshot?.metrics ?? {};
  const sub = evalSnapshot ? `${evalSnapshot.runId} · ${evalSnapshot.gradedBy ?? "—"}` : "chưa có run";

  return (
    <div className="flex gap-4">
      <Group label="Live">
        <Tile
          // Phép đo là `citation_count > 0` (src/services/metrics.py:191) — nó nói
          // "có trích dẫn", KHÔNG nói "trích đúng". Nhãn phải nói đúng chừng ấy;
          // câu hỏi "trích đúng không" thuộc khối bên phải.
          label="Tỷ lệ lượt có trích dẫn"
          value={pct(coTrichDan)}
          detail="ngưỡng >90%"
          pass={dat(coTrichDan, (v) => v > 0.9)}
        />
        <Tile
          label="Độ trễ trung bình (p50)"
          value={p50 != null ? `${p50}ms` : "—"}
          detail="ngưỡng <3000ms"
          pass={p50 != null ? p50 < 3000 : null}
        />
      </Group>
      <div className="w-px shrink-0 bg-line" />
      <Group label="Đánh giá offline" sub={sub}>
        <Tile
          label="Tỷ lệ bịa"
          value={pct(m.hallucination_rate)}
          detail="ngưỡng <10%"
          pass={dat(m.hallucination_rate, (v) => v < 0.1)}
        />
        <Tile
          label="Tỷ lệ có căn cứ"
          value={pct(m.grounded_rate)}
          detail="ngưỡng >90%"
          pass={dat(m.grounded_rate, (v) => v > 0.9)}
        />
        <Tile
          label="Trích dẫn hợp lệ"
          value={pct(m.citation_validity)}
          detail="ngưỡng 100%"
          pass={dat(m.citation_validity, (v) => v >= 1)}
        />
      </Group>
    </div>
  );
}
