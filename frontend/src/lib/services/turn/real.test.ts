import { describe, expect, it } from "vitest";
import { mapServerEvent } from "./real";

describe("mapServerEvent — ui.policy", () => {
  it("map đúng payload lồng (docs/api_spec.md:584) sang UiPolicy camelCase", () => {
    const raw = {
      type: "ui.policy",
      event_id: "evt_1",
      sequence: 1,
      session_id: "ses_1",
      turn_id: null,
      emitted_at: "2026-08-12T10:00:12Z",
      schema_version: "1.0",
      payload: {
        active: true,
        speed_kph: 42,
        ui_policy: {
          allow_text_input: false,
          lock_small_controls: true,
          enlarge_mic_button: true,
          max_visible_actions: 3,
          prefer_voice_confirmation: true,
          allow_detailed_document_browsing: false,
        },
      },
    };

    const mapped = mapServerEvent(raw as never);

    expect(mapped).toEqual({
      type: "ui.policy",
      uiPolicy: {
        allowTextInput: false,
        lockSmallControls: true,
        enlargeMicButton: true,
        maxVisibleActions: 3,
        preferVoiceConfirmation: true,
        allowDetailedDocumentBrowsing: false,
        controlsLocked: false,
      },
    });
  });

  it("không mang active/speed_kph sang DriverEvent — speed tươi phải đọc qua getVehicleState()", () => {
    const raw = {
      type: "ui.policy",
      payload: {
        active: true,
        speed_kph: 99,
        ui_policy: {
          allow_text_input: true,
          lock_small_controls: false,
          enlarge_mic_button: false,
          max_visible_actions: 3,
          prefer_voice_confirmation: false,
          allow_detailed_document_browsing: true,
        },
      },
    };

    const mapped = mapServerEvent(raw as never);
    if (mapped?.type !== "ui.policy") throw new Error("kỳ vọng type ui.policy");

    expect(mapped).not.toHaveProperty("active");
    expect(mapped).not.toHaveProperty("speedKph");
    expect(mapped).not.toHaveProperty("speed_kph");
  });
});
