"use client";

import { useEffect, useRef } from "react";
import { CloseIcon, MicIcon } from "./AppIcons";
import { CitationList } from "./CitationList";
import { useDriverShell } from "./DriverShellProvider";
import { CONTINUE_READING_COMMAND } from "@/lib/services/turn/types";
import type { AssistantState } from "@/lib/services/turn/types";
import { FOLLOW_UP_WINDOW_MS } from "@/lib/wake-word/WakeWordController";

/** Bán kính vòng đếm ngược (issue #343) — đổi ở đây thì đổi luôn chu vi bên
 * dưới; `globals.css`'s `.follow-up-ring-progress` keyframe hard-code cùng
 * chu vi này (~75.4) cho nhánh `to`, phải sửa theo nếu bán kính đổi. */
const FOLLOW_UP_RING_RADIUS = 12;
const FOLLOW_UP_RING_CIRCUMFERENCE = 2 * Math.PI * FOLLOW_UP_RING_RADIUS;

const STATE_LABEL: Record<AssistantState, string> = {
  transcribing: "Đang nghe",
  routing: "Đang xử lý",
  planning: "Đang lên kế hoạch",
  retrieving: "Đang tra cứu sổ tay",
  waiting_approval: "Chờ xác nhận",
  executing: "Đang thực hiện",
  composing: "Đang soạn câu trả lời",
};

type MicColor = "cyan" | "violet" | "amber" | "green";

/**
 * Trước đây mic luôn cyan khi không ghi (đơn điệu, không phân biệt được
 * "đang tra sổ tay" với "đang chờ xác nhận"...) — giờ mỗi nhóm trạng thái có
 * màu riêng, tái dùng đúng 4 token màu đã có (không thêm hex mới):
 * routing/planning/retrieving đều là "đang xử lý ngầm" nên gộp chung violet;
 * waiting_approval dùng amber (đã là màu "cần chú ý" trong toàn app);
 * executing dùng green (khớp màu "đang ghi"/hành động tích cực có sẵn).
 */
const STATE_COLOR: Record<AssistantState, MicColor> = {
  transcribing: "cyan",
  routing: "violet",
  planning: "violet",
  retrieving: "violet",
  waiting_approval: "amber",
  executing: "green",
  composing: "cyan",
};

/**
 * Dáng cao-thấp riêng cho từng thanh (issue #342) — cả 5 thanh cùng đọc một
 * con số RMS (`--mic-level`, viết qua ref bên dưới), nhân thêm hệ số này qua
 * `--bar-scale` để trông như một dải tần thay vì 5 khối cùng nhảy y hệt nhau.
 * Giữa cao nhất, hai đầu thấp dần — cùng dáng chuông đã quen mắt từ bản CSS
 * keyframe cũ.
 */
const BAR_SCALES = [0.5, 0.75, 1, 0.75, 0.5];

const COLOR_CLASSES: Record<MicColor, string> = {
  cyan: "border-cyan text-cyan",
  violet: "border-violet text-violet",
  amber: "border-amber text-amber",
  green: "border-green text-green",
};

/** Chỉ viền, không kèm text-* — dùng cho viền thẻ (opacity riêng, xem BORDER_CLASSES bên dưới trong JSX). */
const BORDER_CLASSES: Record<MicColor, string> = {
  cyan: "border-cyan",
  violet: "border-violet",
  amber: "border-amber",
  green: "border-green",
};

/** Màu thật (không phải class Tailwind) để build gradient nền thẻ bằng color-mix() — cùng biến token đã dùng ở COLOR_CLASSES/BORDER_CLASSES, chỉ khác dạng cần cho style inline. */
const GLOW_VAR: Record<MicColor, string> = {
  cyan: "var(--cyan)",
  violet: "var(--violet)",
  amber: "var(--amber)",
  green: "var(--green)",
};

/** Đang ghi luôn xanh lá (quy ước cũ, giữ nguyên) — lúc đó chưa có `assistantState` nào từ backend. Chưa có state (vừa mở overlay) mặc định cyan. */
export function micStateColor(recording: boolean, assistantState: AssistantState | null): MicColor {
  if (recording) return "green";
  return assistantState ? STATE_COLOR[assistantState] : "cyan";
}

/**
 * Voice overlay — thẻ nổi neo góc trên (dưới StatusBar), theo mẫu trợ lý ảo
 * VinFast/VinBigdata (câu hỏi trên, câu trả lời dưới, wordmark góc dưới-phải)
 * — KHÔNG còn là modal chặn toàn màn hình như bản trước: map/Dock/StatusBar
 * phía sau vẫn hiện rõ, không dim/blur. Lớp `inset-0 z-30` trong suốt vẫn bắt
 * "chạm ra ngoài để đóng" y hệt bản trước, chỉ bỏ phần hình ảnh (màu/blur)
 * của nó; nút X trong thẻ là lối đóng tường minh bổ sung vì giờ không còn
 * dấu hiệu thị giác nào cho biết ngoài thẻ cũng bắt được click.
 *
 * 2 pha giữ nguyên như bản trước: đang GHI (mic thật, chạm để dừng) rồi state
 * machine thuần theo DriverEvent (assistant.status, transcript.partial/final,
 * assistant.response) sau khi đã gửi.
 */
export function VoiceOverlay() {
  const {
    voiceOpen,
    assistantState,
    transcript,
    lastTurn,
    recording,
    stopVoice,
    closeVoice,
    uiPolicy,
    speaking,
    stopSpeaking,
    send,
    followUpWindowActive,
    subscribeMicLevel,
  } = useDriverShell();

  const barsContainerRef = useRef<HTMLDivElement | null>(null);

  // Ghi thẳng vào CSS custom property qua ref, KHÔNG qua setState (issue #342):
  // mức mới tới nhiều lần/giây (throttle ~20Hz ở DriverShellProvider), setState
  // ở tần suất đó sẽ render lại cả overlay mỗi lần.
  useEffect(() => {
    if (!recording) return;
    return subscribeMicLevel((level) => {
      barsContainerRef.current?.style.setProperty("--mic-level", level.toFixed(3));
    });
  }, [recording, subscribeMicLevel]);

  if (!voiceOpen) return null;

  const label = recording ? "Đang nghe — chạm để dừng" : assistantState ? STATE_LABEL[assistantState] : "Đang nghe";
  const color = micStateColor(recording, assistantState);
  // lastTurn.user chỉ có giá trị thật khi lượt bắt đầu bằng send() (gõ chữ);
  // lượt bắt đầu bằng giọng nói không đặt user (xem revealPendingResponse
  // trong DriverShellProvider.tsx) nên phải rơi về `transcript` — 1 trong 2
  // luôn đúng cho "câu hỏi" cần hiện phía trên câu trả lời.
  const question = lastTurn?.user || transcript;

  return (
    <>
      <div onClick={closeVoice} className="absolute inset-0 z-30" aria-hidden />

      <div className="absolute left-1/2 top-19 z-40 w-full max-w-xl -translate-x-1/2 px-4">
        <div
          onClick={(e) => e.stopPropagation()}
          className={`relative overflow-hidden rounded-(--r-lg) border ${BORDER_CLASSES[color]}/35 bg-panel-solid p-5 shadow-2xl backdrop-blur-xl`}
          style={{
            backgroundImage: `radial-gradient(ellipse 280px 180px at 100% 0%, color-mix(in srgb, ${GLOW_VAR[color]} 22%, transparent), transparent 70%)`,
          }}
        >
          <button
            type="button"
            onClick={closeVoice}
            title="Đóng"
            className="absolute right-3 top-3 flex h-7 w-7 items-center justify-center rounded-full text-ink-dim transition-colors hover:text-ink"
          >
            <CloseIcon size={16} />
          </button>

          {recording ? (
            <div className="flex items-center gap-3.5 pr-8">
              <button
                key="recording"
                type="button"
                onClick={stopVoice}
                title="Chạm để dừng ghi và gửi"
                className={`voice-state-pulse flex h-12 w-12 shrink-0 cursor-pointer items-center justify-center rounded-full border-[2.5px] ${COLOR_CLASSES[color]}`}
              >
                <MicIcon size={20} />
              </button>
              <div className="min-w-0 flex-1">
                <p className={`font-technical text-[11px] uppercase tracking-widest ${COLOR_CLASSES[color]}`}>
                  {label}
                </p>
                <div
                  ref={barsContainerRef}
                  data-testid="voice-wave-bars"
                  className="mt-1.5 flex h-5 items-end gap-1"
                >
                  {BAR_SCALES.map((scale, i) => (
                    <span
                      key={i}
                      className="voice-wave-bar w-1.5 rounded-sm bg-green"
                      style={{ ["--bar-scale" as string]: scale }}
                    />
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="pr-8">
              {question && (
                <p className="font-technical text-[11px] uppercase tracking-widest text-ink-soft">{question}</p>
              )}
              {lastTurn?.vivi ? (
                <>
                  <p className="mt-2 font-display text-lg leading-relaxed text-ink">{lastTurn.vivi}</p>
                  {lastTurn.hasMoreToRead && (
                    // Lời mời "bạn có muốn nghe tiếp không?" chỉ nằm trong kênh
                    // NÓI — người nhìn màn hình không thấy dấu hiệu nào là còn
                    // nữa, và không có gì để bấm (issue #116). Nút này là dấu
                    // hiệu đó.
                    //
                    // Nó gửi đúng câu người dùng phải nói nếu không bấm, chứ
                    // không gọi một API riêng: cùng một intent `manual_continue`
                    // ở backend, nên nút và giọng nói không thể lệch nhau.
                    <div className="mt-2.5 mr-2 flex items-center gap-2">
                      {followUpWindowActive && (
                        // Cửa sổ nghe tiếp không cần "Hey Vi Vi" đang mở (issue
                        // #343) — vòng tròn rút dần nói được cả "còn nghe" lẫn
                        // "còn bao lâu", thứ một glow lặp vô hạn không nói được.
                        <span
                          aria-hidden
                          title="Đang chờ bạn nói tiếp — không cần gọi tên"
                          className={`relative inline-flex h-6 w-6 shrink-0 items-center justify-center ${COLOR_CLASSES[color]}`}
                        >
                          <svg className="h-6 w-6 -rotate-90" viewBox="0 0 28 28">
                            <circle
                              cx="14"
                              cy="14"
                              r={FOLLOW_UP_RING_RADIUS}
                              fill="none"
                              stroke="currentColor"
                              strokeOpacity="0.25"
                              strokeWidth="2.5"
                            />
                            <circle
                              className="follow-up-ring-progress"
                              cx="14"
                              cy="14"
                              r={FOLLOW_UP_RING_RADIUS}
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2.5"
                              strokeDasharray={FOLLOW_UP_RING_CIRCUMFERENCE}
                              style={{ animationDuration: `${FOLLOW_UP_WINDOW_MS}ms` }}
                            />
                          </svg>
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => send(CONTINUE_READING_COMMAND)}
                        className={`rounded-(--r-sm) border px-3 py-1.5 font-display text-[12px] font-semibold transition-colors ${COLOR_CLASSES[color]} hover:opacity-80`}
                      >
                        Nghe tiếp →
                      </button>
                    </div>
                  )}
                  {speaking && (
                    // Đường ngắt lời TƯỜNG MINH (issue #106). Đóng thẻ cũng tắt
                    // tiếng, nhưng lúc đó mất luôn phần chữ — nút này để im
                    // tiếng mà vẫn đọc tiếp được câu trả lời, thứ tài xế cần khi
                    // câu sổ tay dài (đo được 65,6 giây).
                    <button
                      type="button"
                      onClick={stopSpeaking}
                      className={`mt-2.5 flex items-center gap-1.5 rounded-(--r-sm) border px-3 py-1.5 font-technical text-[11px] tracking-wide uppercase transition-colors ${COLOR_CLASSES[color]} hover:opacity-80`}
                    >
                      <span aria-hidden>■</span> Dừng đọc
                    </button>
                  )}
                  <CitationList
                    citations={lastTurn.citations}
                    allowDetailed={uiPolicy.allowDetailedDocumentBrowsing}
                    maxVisible={uiPolicy.maxVisibleActions}
                  />
                </>
              ) : (
                <p
                  className={`mt-2 flex items-center gap-2 font-technical text-[11px] uppercase tracking-widest ${COLOR_CLASSES[color]}`}
                >
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                  {label}
                </p>
              )}
              <p className={`mt-3 text-right font-display text-xs font-semibold ${COLOR_CLASSES[color]}`}>VIVI</p>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
