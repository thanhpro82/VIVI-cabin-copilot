"use client";

import { useState } from "react";
import { sessionService, type AuthUser } from "@/lib/services/session";
import { ServiceError } from "@/lib/services/shared/errors";

interface DriverLoginCardProps {
  onSuccess: (user: AuthUser) => void;
}

export function DriverLoginCard({ onSuccess }: DriverLoginCardProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleStart() {
    setIsLoading(true);
    setError(null);
    try {
      const result = await sessionService.loginAsDriver();
      onSuccess(result.user);
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : "Không thể vào khoang lái. Thử lại.");
      setIsLoading(false);
    }
  }

  return (
    <div className="relative flex flex-col justify-between overflow-hidden rounded-[var(--r-lg)] border border-line bg-panel-solid p-8 sm:p-10">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-amber/10 blur-3xl"
      />
      <div>
        <span className="font-technical text-xs tracking-[0.2em] text-amber uppercase">
          Tài xế
        </span>
        <h2 className="mt-3 font-display text-3xl font-semibold text-ink">Vào lái ngay</h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-soft">
          Không cần gõ mật khẩu lúc lên xe — bấm một lần, hệ thống tự xác thực và mở khoang lái.
        </p>
      </div>

      <div className="mt-8">
        <button
          type="button"
          onClick={handleStart}
          disabled={isLoading}
          className="w-full rounded-[var(--r-sm)] bg-amber px-6 py-3.5 font-body text-sm font-semibold text-bg transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading ? "Đang khởi động…" : "Bắt đầu lái →"}
        </button>
        {error && (
          <p className="mt-3 font-technical text-xs text-accent" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
