"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SIM_HARNESS_ABSENT_CODE, turnService } from "@/lib/services/turn";
import { ServiceError } from "@/lib/services/shared/errors";
import { useDriverShell } from "./DriverShellProvider";

/**
 * Bàn đạo diễn kịch bản demo — đặt tốc độ **xe ảo** để xem hành vi S2/S3
 * (ADR-006) đổi thế nào giữa lúc xe đứng yên và đang chạy.
 *
 * Từ issue #183 (ADR-024) thanh trượt chạy ở CẢ hai chế độ: real mode gọi
 * `POST /api/v1/sim/motion` trên kênh harness `v1/sim`, mock gọi thẳng vào
 * state trong bộ nhớ. Nhánh "chỉ-xem kèm hướng dẫn gõ console" cũ **không biến
 * mất** — nó lùi về đúng chỗ nó vẫn đúng: khi backend không bật kênh này
 * (`SIM_CONTROL_ENABLED=false`, mặc định) thì console lại là đường duy nhất.
 *
 * Đây KHÔNG phải giao diện điều khiển xe: tốc độ không đi qua router/policy/HITL
 * và không sinh ra lượt nào. ADR-013 còn nguyên — backend chỉ publish một
 * message, chính xe ảo mới đặt tốc độ của nó rồi phát lại `state/*`.
 */

/**
 * Chỉ gửi lần kéo cuối trong mỗi khoảng này. Một cú kéo thanh trượt sinh hàng
 * chục sự kiện `change`; gửi hết là hàng chục request HTTP và hàng chục message
 * MQTT cho một thao tác của người dùng. 120 ms đủ ngắn để không thấy trễ, đủ
 * dài để gộp gần hết một cú kéo.
 */
const SEND_DEBOUNCE_MS = 120;

/** Trần thanh trượt. Thấp hơn `SIM_SPEED_MAX_KPH` (200) của backend một cách cố
 * ý: mọi ngưỡng an toàn của P0 nằm ở ranh giới 0 / khác 0, nên dải rộng chỉ làm
 * khó việc chỉnh, không mở thêm kịch bản nào. */
const SLIDER_MAX_KPH = 100;

type HarnessState = "unknown" | "ready" | "absent";

export function SpeedDebugDrawer() {
  const { vehicleState, refreshVehicleState } = useDriverShell();
  const [open, setOpen] = useState(false);
  const [harness, setHarness] = useState<HarnessState>("unknown");
  const [error, setError] = useState<string | null>(null);
  /**
   * Giá trị người dùng vừa kéo, giữ tách khỏi `vehicleState`. Bắt buộc ở real
   * mode: route trả 202 rồi xe mới đổi state qua MQTT, nên trong ~1 giây tới
   * `vehicleState.motion.speedKph` vẫn là số cũ. Bind thẳng `value` vào state
   * xe sẽ khiến thanh trượt bật ngược về chỗ cũ ngay giữa lúc đang kéo.
   */
  const [draft, setDraft] = useState<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const speed = vehicleState?.motion.speedKph ?? 0;
  const gear = vehicleState?.motion.gear ?? "P";

  /**
   * Nhả `draft` khi xe đã thật sự tới nơi — từ đó trở đi thanh trượt lại bám
   * state thật, nên tốc độ do NGƯỜI KHÁC đặt (xe ảo dùng chung) cũng hiện ra.
   *
   * Chỉnh state ngay trong lúc render, không phải trong `useEffect`: React chạy
   * lại component trước khi vẽ nên không có khung hình trung gian nào bị nháy,
   * còn bản `useEffect` thì vẽ một khung sai rồi mới sửa. Đây là mẫu "adjusting
   * state when a prop changes" của React, và cũng là lý do phải nhớ
   * `lastSeenSpeed`: điều kiện phải là "state xe VỪA đổi", không phải "state xe
   * đang bằng draft" — nếu không thì `setDraft(null)` chạy lại ở mọi lần render
   * và thành vòng lặp.
   */
  const [lastSeenSpeed, setLastSeenSpeed] = useState(speed);
  if (speed !== lastSeenSpeed) {
    setLastSeenSpeed(speed);
    if (draft !== null && speed === draft) setDraft(null);
  }

  // Poll trong lúc mở. Cần cả ở real mode lẫn mock: ở real mode state đổi bất
  // đồng bộ qua MQTT sau khi route trả 202, và WS không đẩy sự kiện `motion`.
  useEffect(() => {
    if (!open) return;
    const timer = setInterval(refreshVehicleState, 1000);
    return () => clearInterval(timer);
  }, [open, refreshVehicleState]);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const send = useCallback(
    (value: number) => {
      // `gear` cố ý bỏ trống: xe ảo tự chọn D khi > 0 và P khi = 0, đúng như
      // `speed 45` gõ vào console. Ép gear ở đây sẽ tạo ra một đường thứ hai
      // cho cùng một quy ước, và hai đường thì sẽ có lúc lệch nhau.
      turnService
        .setSimSpeed(value)
        .then(() => {
          setHarness("ready");
          setError(null);
        })
        .catch((err: unknown) => {
          setDraft(null);
          if (err instanceof ServiceError && err.code === SIM_HARNESS_ABSENT_CODE) {
            // Ca BÌNH THƯỜNG, không phải lỗi: cờ `SIM_CONTROL_ENABLED` mặc định
            // tắt, và backend chưa có PR #206 cũng rơi vào đây. Đổi hẳn sang
            // nhánh hướng dẫn console thay vì hiện toast đỏ.
            setHarness("absent");
            setError(null);
            return;
          }
          setError(err instanceof ServiceError ? err.message : "Không đặt được tốc độ xe ảo.");
        });
    },
    [],
  );

  function handleChange(value: number) {
    setDraft(value);
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => send(value), SEND_DEBOUNCE_MS);
  }

  const sliderValue = draft ?? speed;

  return (
    <div className="absolute top-17 right-4 z-30">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        title="Bảng test tốc độ xe ảo"
        className="flex h-9.5 w-9.5 items-center justify-center rounded-xl border border-line bg-(--panel) text-ink-soft hover:text-ink"
      >
        ⚙
      </button>
      {open && (
        <div className="mt-2 w-72 rounded-(--r-md) border border-line bg-panel-solid p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-technical text-[10px] tracking-widest text-ink-dim uppercase">
              Tốc độ mô phỏng
            </p>
            <span className="font-technical text-xs text-ink">
              {speed} km/h · {gear}
            </span>
          </div>
          {harness === "absent" ? (
            <>
              <p className="text-[10.5px] leading-relaxed text-ink-dim">
                Backend này không bật kênh harness (<code className="text-cyan">SIM_CONTROL_ENABLED</code>),
                nên không có API nào đặt được tốc độ. Gõ trực tiếp vào console
                <code className="mx-1 rounded bg-(--panel) px-1 py-0.5 text-cyan">
                  python -m src.vehicle_sim
                </code>
                :
              </p>
              <ul className="mt-2 space-y-1 font-technical text-[10.5px] text-ink">
                <li>
                  <code className="rounded bg-(--panel) px-1 py-0.5 text-cyan">speed 45</code> — đặt tốc độ, tự
                  chuyển gear D
                </li>
                <li>
                  <code className="rounded bg-(--panel) px-1 py-0.5 text-cyan">gear D</code> — đổi số tay
                </li>
                <li>
                  <code className="rounded bg-(--panel) px-1 py-0.5 text-cyan">stop</code> — về 0 km/h, gear P
                </li>
              </ul>
              <p className="mt-2 text-[10.5px] leading-relaxed text-ink-dim">
                Bảng này tự đọc lại {`GET /vehicle/state`} mỗi giây trong lúc mở để thấy
                thay đổi từ console.
              </p>
            </>
          ) : (
            <>
              <input
                type="range"
                aria-label="Tốc độ xe ảo"
                min={0}
                max={SLIDER_MAX_KPH}
                value={sliderValue}
                onChange={(e) => handleChange(Number(e.target.value))}
                className="w-full accent-cyan"
              />
              <p className="mt-2 text-[10.5px] leading-relaxed text-ink-dim">
                &gt; 0 km/h: mở khoá/khoá cửa bị chặn cứng (S3). Cửa sổ vẫn cần xác nhận (S2) dù ở tốc độ nào.
              </p>
              {/* Yêu cầu của issue #183: nói thẳng trên bảng. Không có multi-tenant
                  ở P0 — một xe ảo, state toàn cục, ai cũng kéo được. */}
              <p className="mt-2 text-[10.5px] leading-relaxed text-amber">
                Xe ảo dùng chung: người khác cũng đổi được tốc độ này giữa lượt của bạn.
              </p>
              {error && (
                <p role="alert" className="mt-2 text-[10.5px] leading-relaxed text-pink">
                  {error}
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
