import type {
  EngineerEvent,
  EngineerLogEntry,
  EngineerService,
  EvalSnapshot,
  EvalSuite,
  HealthStatus,
  MetricsSummary,
  VehicleProfile,
} from "./types";

const MOCK_LATENCY_MS = 400;
const TICK_MS = 6000;

function delay(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildMetrics(): MetricsSummary {
  const now = new Date();
  const from = new Date(now.getTime() - 60 * 60 * 1000).toISOString();
  return {
    window: { from, to: now.toISOString() },
    turns: { accepted: 42, completed: 38, failed: 2, canceled: 2 },
    stageLatencyMs: {
      // Phân rã theo AssistantState (turn/types.ts) — BE thật sẽ trả đúng các
      // chặng này qua GET /metrics/summary khi đo chi tiết xong; FE không cần
      // sửa gì thêm, chỉ Object.entries() nên tự hiện đủ khi có field thật.
      transcribing: { count: 38, p50: 180, p95: 320 },
      routing: { count: 38, p50: 90, p95: 150 },
      planning: { count: 38, p50: 250, p95: 430 },
      retrieving: { count: 12, p50: 650, p95: 1320 },
      executing: { count: 15, p50: 150, p95: 280 },
      composing: { count: 38, p50: 100, p95: 180 },
      end_to_end: { count: 38, p50: 1420, p95: 2680 },
    },
    mqtt: { publishAttempts: 20, published: 19, errors: 1, errorRate: 0.05 },
    rag: { answered: 12, grounded: 11, abstained: 2, groundedRate: 0.92, abstentionRate: 0.14 },
    safety: { validationDenied: 1, blockedS3: 1, approvalsRequired: 5, approved: 4, rejected: 1, expired: 0 },
    actionAudit: { attempted: 15, completed: 14, failed: 1, timeout: 0 },
  };
}

function buildHealth(): HealthStatus {
  const components = [
    "backend",
    "llm",
    "mqtt",
    "vehicle_simulator",
    "stt",
    "tts",
    "rag_index",
    "sqlite",
  ] as const;
  return {
    status: "ready",
    checkedAt: new Date().toISOString(),
    components: Object.fromEntries(
      components.map((c) => [c, { status: "ready" as const, latencyMs: Math.round(Math.random() * 10) + 1 }]),
    ),
  };
}

// `answerText: null` ở hai dòng cuối là có chủ đích: lượt hỏng hoặc bị huỷ không
// có câu trả lời, và mock phải dựng được đúng ca đó để LogsTable bị soi ở cả hai
// nhánh mà không cần backend.
const SAMPLE_LOGS: Omit<EngineerLogEntry, "time" | "traceId" | "turnId">[] = [
  { routeSource: "deterministic", safeSummary: "Điều chỉnh điều hoà", answerText: "Đã đặt điều hòa ở 22 độ.", vehicleId: "vehicle-demo-01", approvalStatus: null, status: "completed", latencyMs: 2121 },
  { routeSource: "rag", safeSummary: "Tra cứu sổ tay xe", answerText: "Theo sổ tay: áp suất lốp trục trước là 250 kPa, tức 36 PSI, đo khi lốp nguội.", vehicleId: "vehicle-demo-01", approvalStatus: null, status: "completed", latencyMs: 2604 },
  { routeSource: "deterministic", safeSummary: "Mở cửa sổ (cần xác nhận)", answerText: "Đã hạ kính lái xuống 50%.", vehicleId: "vehicle-demo-01", approvalStatus: "approved", status: "completed", latencyMs: 4880 },
  { routeSource: null, safeSummary: "Không nhận diện được ý định", answerText: null, vehicleId: "vehicle-demo-01", approvalStatus: null, status: "failed", latencyMs: 1190 },
  { routeSource: "deterministic", safeSummary: "Mở khoá cửa (cần xác nhận)", answerText: null, vehicleId: "vehicle-demo-01", approvalStatus: "expired", status: "canceled", latencyMs: 5340 },
];

let genIdx = 0;
function genId(prefix: string) {
  genIdx += 1;
  return `${prefix}_${Date.now()}_${genIdx}`;
}

const subscribers = new Set<(event: EngineerEvent) => void>();
let intervalId: ReturnType<typeof setInterval> | null = null;

function ensureTicker() {
  if (intervalId) return;
  intervalId = setInterval(() => {
    if (subscribers.size === 0) return;
    const sample = SAMPLE_LOGS[Math.floor(Math.random() * SAMPLE_LOGS.length)];
    const entry: EngineerLogEntry = {
      ...sample,
      traceId: genId("tr"),
      turnId: genId("turn"),
      time: new Date().toLocaleTimeString("vi-VN", { hour12: false }),
    };
    subscribers.forEach((cb) => cb({ type: "trace", entry }));
  }, TICK_MS);
}

/**
 * Trạng thái ban đầu là **chưa cấu hình**, không phải một cấu hình đẹp sẵn.
 * Ca "thiếu profile → backend fail-closed" là ca cần nhìn thấy nhất ở màn engineer,
 * mà seed sẵn eco/sdi thì không ai gặp nó trong lúc chạy mock.
 */
let mockProfile: VehicleProfile = {
  vehicleId: "vehicle-demo-01",
  trim: null,
  battery: null,
  isComplete: false,
  updatedAt: null,
};

export const mockEngineerService: EngineerService = {
  async getMetricsSummary() {
    await delay(MOCK_LATENCY_MS);
    return buildMetrics();
  },

  async getEvalSnapshot(suite: EvalSuite): Promise<EvalSnapshot | null> {
    await delay(MOCK_LATENCY_MS);
    // `agent-intent` tra null CO CHU DINH, khong phai chua lam: run that cua no
    // cho intent_accuracy = 1.0000 tren bo agent/v3 — mot tripwire hoi quy do
    // chinh tac gia router soan. Xem spec 2026-08-28 §3.2.
    if (suite !== "rag") return null;
    // So lay tu run that eval/results/rag/20260827T172523Z, de mock khong ve ra
    // mot the gioi dep hon the gioi that.
    return {
      suite: "rag",
      runId: "20260827T172523Z",
      metrics: { grounded_rate: 1.0, hallucination_rate: 0.05, citation_validity: 1.0 },
      gradedBy: "dap_an_khoa",
      dataset: "eval/datasets/manual/v1/cases.jsonl",
      note: null,
    };
  },

  async getHealth() {
    await delay(MOCK_LATENCY_MS);
    return buildHealth();
  },

  async getVehicleProfile() {
    await delay(MOCK_LATENCY_MS);
    return mockProfile;
  },

  async setVehicleProfile(update) {
    await delay(MOCK_LATENCY_MS);
    // `isComplete` do "backend" tính — ở đây mock ĐANG đóng vai backend, nên phép
    // tính này nằm đúng chỗ. Component vẫn chỉ được đọc field, không tự suy lại.
    mockProfile = {
      ...mockProfile,
      trim: update.trim,
      battery: update.battery,
      isComplete: update.trim !== null && update.battery !== null,
      updatedAt: new Date().toISOString(),
    };
    return mockProfile;
  },

  subscribe(onEvent) {
    subscribers.add(onEvent);
    ensureTicker();
    return () => {
      subscribers.delete(onEvent);
      if (subscribers.size === 0 && intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    };
  },
};
