/**
 * Nối dây hai chiều của cửa sổ nghe tiếp — spec §3.1 và §3.5.
 *
 * Chiều xuống: `mo_mic_ngan` từ `assistant.response` cho FE biết có được mở mic ngắn
 * không. Chiều lên: `X-Capture-Mode` cho backend biết lượt này do mic **tự mở** bắt được,
 * để nó **im lặng** thay vì đọc câu từ chối vào giữa cuộc nói chuyện của người.
 *
 * Payload dưới đây chép **nguyên văn** hình dạng của `assistant_response_payload`
 * (`src/services/ivi_events.py`), không viết lại theo trí nhớ — cùng kỷ luật với
 * `real.citations.test.ts`: khớp một hình dạng tưởng tượng thì test xanh mà FE vẫn hỏng.
 */
import { describe, expect, it, vi } from "vitest";

import { mapServerEvent } from "./real";

// Cùng khuôn `vi.mock` với `real.simSpeed.test.ts` — `sendVoice` gọi `currentSessionId()`
// và nó NÉM khi chưa có session, nên không có phần này thì `fetch` không bao giờ chạy và
// test "không có header" xanh vì một lý do sai hẳn.
const STORED_SESSION = {
  accessToken: "tok-abc",
  tokenType: "Bearer",
  expiresAt: "2099-01-01T00:00:00Z",
  user: { userId: "usr_driver_01", role: "driver" as const, displayName: "Demo Driver" },
};
const DRIVER_SESSION = {
  sessionId: "ses_test_1",
  vehicleId: "vehicle-demo-01",
  status: "active",
  startedAt: "2026-01-01T00:00:00Z",
};

vi.mock("../session", () => ({
  sessionService: {
    getStoredSession: () => STORED_SESSION,
    getCurrentDriverSession: () => DRIVER_SESSION,
    createDriverSession: async () => DRIVER_SESSION,
  },
}));

const RAW = {
  type: "assistant.response",
  turn_id: "trn_abc123",
  payload: {
    display_text: "Đã thực hiện lệnh trên xe mô phỏng.",
    speak_text: "Đã thực hiện lệnh trên xe mô phỏng.",
    has_more_to_read: false,
    mo_mic_ngan: true,
    citations: [],
    outcomes: [],
  },
};

function doc(payload: Record<string, unknown>) {
  const su = mapServerEvent({ ...RAW, payload: { ...RAW.payload, ...payload } });
  if (su?.type !== "assistant.response") throw new Error(`không map ra assistant.response: ${su?.type}`);
  return su.result;
}

describe("mo_mic_ngan — chiều xuống", () => {
  it("đọc được khi backend gửi", () => {
    expect(doc({ mo_mic_ngan: true }).moMicNgan).toBe(true);
    expect(doc({ mo_mic_ngan: false }).moMicNgan).toBe(false);
  });

  it("thiếu field thì là false, không phải undefined", () => {
    const { mo_mic_ngan: _bo, ...khongCo } = RAW.payload;
    const su = mapServerEvent({ ...RAW, payload: khongCo });
    if (su?.type !== "assistant.response") throw new Error("không map ra assistant.response");
    expect(su.result.moMicNgan).toBe(false);
  });

  it("giá trị lạ cũng ra false — thiếu tín hiệu không được biến thành mic mở", () => {
    // Cùng quy ước với `has_more_to_read` (xem `real.citations.test.ts`), và ở đây nó
    // quan trọng hơn: một `"false"` chuỗi hay một `1` sẽ mở mic nếu ép kiểu lỏng, tức
    // mở đúng cái cửa mà cả spec này đang lo cách đóng.
    for (const la of ["true", 1, {}, [], null, "yes"]) {
      expect(doc({ mo_mic_ngan: la }).moMicNgan).toBe(false);
    }
  });

  it("không lẫn với has_more_to_read — hai cờ, hai nghĩa", () => {
    // Bất biến của #363: `has_more_to_read` là của nhánh sổ tay. Trộn hai đường lại thì
    // rào chắn `mau_slot` mất tác dụng trong im lặng.
    const ra = doc({ has_more_to_read: true, mo_mic_ngan: false });
    expect(ra.hasMoreToRead).toBe(true);
    expect(ra.moMicNgan).toBe(false);
  });
});

describe("X-Capture-Mode — chiều lên", () => {
  async function batHeader(goi: (t: import("./types").TurnService) => Promise<unknown>) {
    const fetchGia = vi.fn(
      async (_url: RequestInfo | URL, _init?: RequestInit) =>
        new Response(JSON.stringify({ data: { turn_id: "trn_x" } }), { status: 202 }),
    );
    vi.stubGlobal("fetch", fetchGia);
    const { realTurnService } = await import("./real");
    try {
      await goi(realTurnService);
    } catch (loi) {
      // Không nuốt im lặng: nếu `sendVoice` chết TRƯỚC khi gọi `fetch` thì assert bên
      // dưới sẽ xanh vì header rỗng — tức test xanh vì một lý do sai hẳn.
      throw loi;
    }
    vi.unstubAllGlobals();
    const goiVoice = fetchGia.mock.calls.find(([url]) => String(url).includes("/turns/voice"));
    return new Headers(goiVoice?.[1]?.headers as HeadersInit);
  }

  const wav = new Blob([new Uint8Array(44)], { type: "audio/wav" });

  it("mặc định khai manual — client cũ không đổi hành vi", async () => {
    const h = await batHeader((t) => t.sendVoice(wav));
    expect(h.get("X-Capture-Mode")).toBe("manual");
  });

  it("khai auto khi cửa sổ nghe tiếp tự bắt được", async () => {
    const h = await batHeader((t) => t.sendVoice(wav, { auto: true }));
    expect(h.get("X-Capture-Mode")).toBe("auto");
  });

  it("auto:false vẫn là manual, không phải vắng header", async () => {
    const h = await batHeader((t) => t.sendVoice(wav, { auto: false }));
    expect(h.get("X-Capture-Mode")).toBe("manual");
  });
});
