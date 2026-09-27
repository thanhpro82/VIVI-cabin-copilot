/**
 * `routine.started`/`routine.step`/`routine.finished` (#290/#292) ride CHUNG
 * `/ws/ivi` — `turn_id` của khung sự kiện mang `execution_id`
 * (`src/services/routine_execution.py::_phat`, xác nhận qua đọc source lẫn
 * gọi API thật `POST /routines/{id}/run` ngày 29/08: field `description`
 * trong `results[]`/`routine.step` là mô tả tiếng Việt thật ("bật đèn trần"),
 * không phải tên action lặp lại — chỉ `routine.started.steps[]` (`_tom_tat_
 * buoc`) mới lặp action làm description, vì lúc đó chưa có gì để mô tả.
 */
import { describe, expect, it } from "vitest";
import { mapServerEvent } from "./real";

describe("mapServerEvent — routine.started", () => {
  it("map đúng camelCase, executionId lấy từ turn_id", () => {
    const raw = {
      type: "routine.started",
      turn_id: "rex_838202cc4faefeff",
      payload: {
        execution_id: "rex_838202cc4faefeff",
        routine_id: "rtn_usr_driver_01_thu_gian",
        routine_name: "Thư giãn",
        routine_version: 1,
        steps: [
          { index: 0, action: "interior_light", description: "interior_light" },
          { index: 1, action: "media_control", description: "media_control" },
        ],
        started_at: "2026-08-29T09:05:50+00:00",
      },
    };

    expect(mapServerEvent(raw)).toEqual({
      type: "routine.started",
      executionId: "rex_838202cc4faefeff",
      routineId: "rtn_usr_driver_01_thu_gian",
      routineName: "Thư giãn",
      routineVersion: 1,
      steps: [
        { index: 0, action: "interior_light", description: "interior_light" },
        { index: 1, action: "media_control", description: "media_control" },
      ],
      startedAt: "2026-08-29T09:05:50+00:00",
    });
  });

  it("steps thiếu/không phải mảng -> [] (không throw)", () => {
    const raw = {
      type: "routine.started",
      turn_id: "rex_1",
      payload: {
        execution_id: "rex_1",
        routine_id: "rtn_1",
        routine_name: "X",
        routine_version: 1,
        steps: undefined,
        started_at: "t",
      },
    };
    const mapped = mapServerEvent(raw);
    expect(mapped?.type === "routine.started" && mapped.steps).toEqual([]);
  });
});

describe("mapServerEvent — routine.step", () => {
  it("bước hoàn tất — description thật từ backend, không phải tên action", () => {
    const raw = {
      type: "routine.step",
      turn_id: "rex_838202cc4faefeff",
      payload: {
        execution_id: "rex_838202cc4faefeff",
        index: 0,
        action: "interior_light",
        status: "completed",
        description: "bật đèn trần",
        error_code: null,
      },
    };

    expect(mapServerEvent(raw)).toEqual({
      type: "routine.step",
      executionId: "rex_838202cc4faefeff",
      index: 0,
      action: "interior_light",
      status: "completed",
      description: "bật đèn trần",
      errorCode: null,
      approvalId: undefined,
    });
  });

  it("waiting_approval mang thêm approval_id — approvalId chỉ có mặt ở đây", () => {
    const raw = {
      type: "routine.step",
      turn_id: "rex_2",
      payload: {
        execution_id: "rex_2",
        index: 1,
        action: "window_position",
        status: "waiting_approval",
        description: "hạ cửa sổ trước trái",
        error_code: null,
        approval_id: "apv_abc123",
      },
    };

    const mapped = mapServerEvent(raw);
    expect(mapped).toMatchObject({ type: "routine.step", status: "waiting_approval", approvalId: "apv_abc123" });
  });

  it("bước lỗi mang error_code", () => {
    const raw = {
      type: "routine.step",
      turn_id: "rex_3",
      payload: {
        execution_id: "rex_3",
        index: 0,
        action: "hvac_temperature",
        status: "failed",
        description: "chỉnh nhiệt độ",
        error_code: "mqtt_timeout",
      },
    };
    const mapped = mapServerEvent(raw);
    expect(mapped).toMatchObject({ status: "failed", errorCode: "mqtt_timeout" });
  });
});

describe("mapServerEvent — routine.finished", () => {
  it("map results[] đúng, đủ 4 trạng thái cuối có thể gặp, kèm audio tổng kết (#396)", () => {
    const raw = {
      type: "routine.finished",
      turn_id: "rex_838202cc4faefeff",
      payload: {
        execution_id: "rex_838202cc4faefeff",
        routine_id: "rtn_usr_driver_01_thu_gian",
        status: "completed",
        terminal_reason: "completed",
        results: [
          { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", error_code: null },
          { index: 1, action: "media_control", status: "completed", description: "phát nhạc", error_code: null },
        ],
        completed_at: "2026-08-29T09:05:50+00:00",
        audio_base64: "AAAA",
        mime_type: "audio/wav",
      },
    };

    expect(mapServerEvent(raw)).toEqual({
      type: "routine.finished",
      executionId: "rex_838202cc4faefeff",
      routineId: "rtn_usr_driver_01_thu_gian",
      status: "completed",
      terminalReason: "completed",
      results: [
        { index: 0, action: "interior_light", status: "completed", description: "bật đèn trần", errorCode: null },
        { index: 1, action: "media_control", status: "completed", description: "phát nhạc", errorCode: null },
      ],
      completedAt: "2026-08-29T09:05:50+00:00",
      audioBase64: "AAAA",
      mimeType: "audio/wav",
    });
  });

  it("thiếu audio_base64/mime_type (TTS lỗi, fail-open phía backend) thì map về null, không undefined", () => {
    const raw = {
      type: "routine.finished",
      turn_id: "rex_1",
      payload: {
        execution_id: "rex_1",
        routine_id: "rtn_1",
        status: "completed",
        terminal_reason: "completed",
        results: [],
        completed_at: "t",
      },
    };

    const mapped = mapServerEvent(raw);
    expect(mapped?.type === "routine.finished" && mapped.audioBase64).toBeNull();
    expect(mapped?.type === "routine.finished" && mapped.mimeType).toBeNull();
  });

  it("canceled_before_run: step chưa chạy vẫn có mặt trong results với error_code riêng", () => {
    const raw = {
      type: "routine.finished",
      turn_id: "rex_4",
      payload: {
        execution_id: "rex_4",
        routine_id: "rtn_1",
        status: "user_canceled",
        terminal_reason: "user_canceled",
        results: [
          { index: 0, action: "hvac_power", status: "completed", description: "bật điều hoà", error_code: null },
          { index: 1, action: "hvac_temperature", status: "canceled", description: "chưa chạy", error_code: "canceled_before_run" },
        ],
        completed_at: "t",
      },
    };
    const mapped = mapServerEvent(raw);
    expect(mapped?.type === "routine.finished" && mapped.results[1]).toEqual({
      index: 1,
      action: "hvac_temperature",
      status: "canceled",
      description: "chưa chạy",
      errorCode: "canceled_before_run",
    });
  });
});
