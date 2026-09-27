"use client";

import { FILTER_ALL, useEngineerShell } from "./EngineerShellProvider";

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 rounded-full border border-line bg-panel-solid px-3 py-1.5 font-technical text-[11px] text-ink-soft">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-panel-solid text-ink focus:outline-none"
        style={{ colorScheme: "dark" }}
      >
        <option value={FILTER_ALL} className="bg-panel-solid text-ink">
          Tất cả
        </option>
        {options.map((opt) => (
          <option key={opt} value={opt} className="bg-panel-solid text-ink">
            {opt}
          </option>
        ))}
      </select>
    </label>
  );
}

export function LogsFilterBar() {
  const { routeFilter, setRouteFilter, routeOptions, statusFilter, setStatusFilter, statusOptions, exportCsv } =
    useEngineerShell();

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Select label="Nguồn" value={routeFilter} options={routeOptions} onChange={setRouteFilter} />
      <Select label="Trạng thái" value={statusFilter} options={statusOptions} onChange={setStatusFilter} />
      <span className="flex-1" />
      <button
        type="button"
        onClick={exportCsv}
        className="rounded-full border border-line bg-panel-solid px-3 py-1.5 font-technical text-[11px] text-ink-soft transition-colors hover:border-cyan hover:text-cyan"
      >
        ⭳ Xuất nhật ký CSV
      </button>
    </div>
  );
}
