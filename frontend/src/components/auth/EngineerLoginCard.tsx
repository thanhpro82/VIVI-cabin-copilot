"use client";

import { useId, useState, type FormEvent } from "react";
import { sessionService, type AuthUser } from "@/lib/services/session";
import { ServiceError } from "@/lib/services/shared/errors";

interface EngineerLoginCardProps {
  onSuccess: (user: AuthUser) => void;
}

export function EngineerLoginCard({ onSuccess }: EngineerLoginCardProps) {
  const emailId = useId();
  const passwordId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const result = await sessionService.login(email, password);
      onSuccess(result.user);
    } catch (err) {
      setError(err instanceof ServiceError ? err.message : "Đăng nhập thất bại. Thử lại.");
      setIsLoading(false);
    }
  }

  return (
    <div className="relative flex flex-col justify-between overflow-hidden rounded-[var(--r-lg)] border border-line bg-panel-solid p-8 sm:p-10">
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-cyan/10 blur-3xl"
      />
      <div>
        <span className="font-technical text-xs tracking-[0.2em] text-cyan uppercase">
          Kỹ sư hệ thống
        </span>
        <h2 className="mt-3 font-display text-3xl font-semibold text-ink">Đăng nhập nội bộ</h2>
        <p className="mt-3 text-sm leading-relaxed text-ink-soft">
          Bảng điều khiển vận hành &amp; nhật ký hệ thống — cần xác thực đầy đủ trước khi vào.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="mt-8 space-y-4">
        <div>
          <label
            htmlFor={emailId}
            className="font-technical text-xs tracking-[0.15em] text-ink-dim uppercase"
          >
            Email
          </label>
          <input
            id={emailId}
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="mt-2 w-full rounded-[var(--r-sm)] border border-line bg-[var(--panel)] px-4 py-2.5 font-body text-sm text-ink outline-none placeholder:text-ink-dim focus-visible:border-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan"
            placeholder="ban@vivi.dev"
          />
        </div>

        <div>
          <label
            htmlFor={passwordId}
            className="font-technical text-xs tracking-[0.15em] text-ink-dim uppercase"
          >
            Mật khẩu
          </label>
          <input
            id={passwordId}
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="mt-2 w-full rounded-[var(--r-sm)] border border-line bg-[var(--panel)] px-4 py-2.5 font-body text-sm text-ink outline-none placeholder:text-ink-dim focus-visible:border-cyan focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan"
            placeholder="••••••••"
          />
        </div>

        <button
          type="submit"
          disabled={isLoading}
          className="w-full rounded-[var(--r-sm)] bg-cyan px-6 py-3.5 font-body text-sm font-semibold text-bg transition-opacity hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan disabled:cursor-not-allowed disabled:opacity-60"
        >
          {isLoading ? "Đang xác thực…" : "Đăng nhập →"}
        </button>
        {error && (
          <p className="font-technical text-xs text-accent" role="alert">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}
