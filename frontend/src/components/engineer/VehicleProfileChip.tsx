"use client";

import { useEffect, useRef, useState } from "react";
import type { VehicleBattery, VehicleTrim } from "@/lib/services/engineer";
import { useVehicleProfile } from "./useVehicleProfile";

/**
 * Danh tính xe demo: một chip **thường trực** trên header, bấm vào mới bung form sửa.
 *
 * ## Vì sao là chip trên header chứ không phải một tab
 *
 * Công cụ chẩn đoán thật (BMW ISTA, VW ODIS, Volvo VIDA) đều neo cả phiên làm việc
 * vào nhận dạng xe: đọc VIN trước, rồi mới cho chẩn đoán. Tesla Service Mode đi xa
 * hơn — khi xe ở chế độ ấy, **toàn màn hình đổi viền đỏ**, vì đó là trạng thái làm
 * đổi cách diễn giải mọi thứ bên dưới.
 *
 * Ở đây cũng vậy: chưa khai báo cấu hình thì **mọi câu trả lời áp suất lốp trong
 * bảng nhật ký bên dưới đều là câu fail-closed**. Đó là ngữ cảnh để đọc phần còn
 * lại của màn hình, không phải một cài đặt. Giấu sau một tab là giấu đúng cái trạng
 * thái cần thấy — kịch bản hỏng là engineer quên khai báo rồi ngồi thắc mắc sao trợ
 * lý trả lời chung chung.
 *
 * Nên: nhãn luôn hiện (và chuyển amber khi thiếu), còn phần *sửa* thì gập lại để
 * không chiếm chỗ của biểu đồ và nhật ký.
 */

/** Tên dòng xe là hằng số cấp sản phẩm (cả RAG index là sổ tay VF9), không suy từ profile. */
const MODEL_LABEL = "VF9";

const TRIM_OPTIONS: { value: VehicleTrim; label: string }[] = [
  { value: "eco", label: "ECO" },
  { value: "plus", label: "PLUS" },
];

const BATTERY_OPTIONS: { value: VehicleBattery; label: string }[] = [
  { value: "sdi", label: "SDI" },
  { value: "catl", label: "CATL" },
];

/** `""` trong `<select>` <-> `null` trên wire. Không có giá trị thứ ba. */
const UNSET = "";

function ChoiceRow<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T | null;
  options: { value: T; label: string }[];
  onChange: (v: T | null) => void;
  disabled: boolean;
}) {
  return (
    <label className="flex items-center justify-between gap-3 font-technical text-[11px] text-ink-soft">
      {label}
      <select
        aria-label={label}
        value={value ?? UNSET}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === UNSET ? null : (e.target.value as T))}
        className="rounded-full border border-line bg-panel-solid px-3 py-1.5 text-ink focus:outline-none disabled:opacity-50"
        style={{ colorScheme: "dark" }}
      >
        <option value={UNSET} className="bg-panel-solid text-ink">
          — chưa chọn —
        </option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value} className="bg-panel-solid text-ink">
            {opt.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export function VehicleProfileChip() {
  const { profile, trim, battery, setTrim, setBattery, busy, error, dirty, configured, save } = useVehicleProfile();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    // `mousedown` chứ không `click`: bấm vào một nút khác trên header phải đóng
    // popover *trước* khi nút đó chạy, nếu không cú bấm đầu tiên chỉ để đóng.
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const chipLabel =
    profile === null
      ? error
        ? "chưa đọc được cấu hình"
        : "đang đọc…"
      : configured
        ? `${trimLabel(profile.trim)} · ${batteryLabel(profile.battery)}`
        : "chưa khai báo cấu hình";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Cấu hình xe demo — phiên bản và loại pin"
        className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-technical text-[10px] tracking-wide transition-colors ${
          configured
            ? "border-line text-ink-soft hover:border-cyan hover:text-cyan"
            : "border-amber/40 text-amber hover:border-amber"
        }`}
      >
        <span className="h-1.5 w-1.5 rounded-full bg-current" />
        {MODEL_LABEL} · {chipLabel}
        <span className="text-ink-dim">▾</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Cấu hình xe demo"
          // `bg-bg2` đặc chứ không `bg-panel-solid` trong suốt: popover nổi lên trên
          // bảng nhật ký, nền mờ sẽ để chữ bên dưới xuyên qua.
          className="absolute top-full left-0 z-20 mt-2 flex w-72 flex-col gap-3 rounded-(--r-md) border border-line bg-bg2 p-4"
        >
          <div className="flex items-center justify-between">
            <p className="font-technical text-[10px] tracking-widest text-ink-dim uppercase">Cấu hình xe demo</p>
            <span className={`font-technical text-[10px] ${configured ? "text-green" : "text-amber"}`}>
              {profile === null ? "—" : configured ? "Đã cấu hình" : "Chưa cấu hình"}
            </span>
          </div>

          <ChoiceRow label="Phiên bản" value={trim} options={TRIM_OPTIONS} onChange={setTrim} disabled={busy} />
          <ChoiceRow label="Loại pin" value={battery} options={BATTERY_OPTIONS} onChange={setBattery} disabled={busy} />

          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy || !dirty}
              onClick={() => void save(trim, battery)}
              className="rounded-full border border-line bg-panel-solid px-3 py-1.5 font-technical text-[11px] text-ink-soft transition-colors hover:border-cyan hover:text-cyan disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-soft"
            >
              {busy ? "Đang lưu…" : "Lưu cấu hình"}
            </button>
            <button
              type="button"
              disabled={busy || profile === null || (profile.trim === null && profile.battery === null)}
              onClick={() => void save(null, null)}
              className="rounded-full border border-line bg-panel-solid px-3 py-1.5 font-technical text-[11px] text-ink-dim transition-colors hover:border-amber hover:text-amber disabled:opacity-40 disabled:hover:border-line disabled:hover:text-ink-dim"
            >
              Xoá cấu hình
            </button>
          </div>

          {error ? <p className="font-technical text-[10.5px] text-amber">{error}</p> : null}

          <p className="font-technical text-[10.5px] leading-relaxed text-ink-dim">
            {configured
              ? "Lượt hỏi tiếp theo tra áp suất lốp theo cấu hình này."
              : "Chưa đủ cấu hình: hệ thống trả lời áp suất lốp bằng câu chỉ nguồn, không đoán số. Màn hình này không tự điền giá trị mặc định."}
          </p>

          {profile ? (
            <p className="font-technical text-[10px] text-ink-dim">
              {profile.vehicleId}
              {profile.updatedAt ? ` · cập nhật ${profile.updatedAt}` : ""}
            </p>
          ) : null}
        </div>
      )}
    </div>
  );
}

function trimLabel(value: VehicleTrim | null): string {
  return value === null ? "—" : value.toUpperCase();
}

function batteryLabel(value: VehicleBattery | null): string {
  return value === null ? "—" : value.toUpperCase();
}
