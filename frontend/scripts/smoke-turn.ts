/**
 * Script chạy thử nhanh mockTurnService — xem luồng sự kiện thật bằng mắt.
 * Chạy: npm run smoke:turn
 * Không phải test tự động (xem mock.test.ts cho việc đó) — chỉ để quan sát
 * nhanh khi sửa logic mock, khỏi phải dựng UI mới thấy được.
 */
import { __setMockSpeedKph, mockTurnService } from "../src/lib/services/turn/mock";
import type { DriverEvent } from "../src/lib/services/turn/types";

function log(label: string, event: DriverEvent) {
  console.log(`[${label}]`, JSON.stringify(event));
}

function wait(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function main() {
  const unsubscribe = mockTurnService.subscribe((event) => log("event", event));

  console.log("\n=== Kịch bản 1: control_ac (S1 — thực thi ngay, không cần duyệt) ===");
  await mockTurnService.sendText("bật điều hòa 22 độ");
  await wait(1500);
  console.log("vehicleState.hvac =", (await mockTurnService.getVehicleState()).hvac);

  console.log("\n=== Kịch bản 2: control_window (S2 — luôn cần duyệt, kể cả xe đứng yên) ===");
  let pendingApprovalId = "";
  const unsubscribeApproval = mockTurnService.subscribe((event) => {
    if (event.type === "approval.required") pendingApprovalId = event.approvalId;
  });
  await mockTurnService.sendText("mở cửa sổ");
  await wait(1500);
  console.log("→ đang chờ duyệt, approvalId =", pendingApprovalId);
  await mockTurnService.decideApproval(pendingApprovalId, "approve", (await mockTurnService.getVehicleState()).stateVersion);
  await wait(600);
  console.log("vehicleState.windows =", (await mockTurnService.getVehicleState()).windows);
  unsubscribeApproval();

  console.log("\n=== Kịch bản 3: câu không nhận diện được ===");
  await mockTurnService.sendText("ơ cái đó ừm");
  await wait(1000);

  console.log("\n=== Kịch bản 4: control_door khi xe đang chạy (S3 — bị chặn hoàn toàn) ===");
  __setMockSpeedKph(40);
  await mockTurnService.sendText("mở khóa cửa");
  await wait(1500);
  console.log("vehicleState.doors =", (await mockTurnService.getVehicleState()).doors);

  unsubscribe();
  console.log("\nXong.");
}

main();
