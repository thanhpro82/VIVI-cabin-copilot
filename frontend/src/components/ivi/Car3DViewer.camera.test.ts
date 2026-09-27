import { describe, expect, it } from "vitest";
import { computeCameraView, firstOpenDoor, ORBIT_DEFAULT } from "./car3dCamera";
import type { VehicleState } from "@/lib/services/turn/types";

const CLOSED: VehicleState["doors"] = {
  frontLeft: "closed",
  frontRight: "closed",
  rearLeft: "closed",
  rearRight: "closed",
};

describe("firstOpenDoor", () => {
  it("không cửa nào mở thì không có gì để ngó", () => {
    expect(firstOpenDoor(CLOSED)).toBeNull();
  });

  it("ưu tiên ghế lái khi nhiều cửa cùng mở — camera chỉ có một hướng", () => {
    expect(firstOpenDoor({ ...CLOSED, rearRight: "open", frontLeft: "open" })).toBe("frontLeft");
    expect(firstOpenDoor({ ...CLOSED, rearRight: "open", rearLeft: "open" })).toBe("rearLeft");
  });

  it("chỉ 'open' mới tính là mở", () => {
    expect(firstOpenDoor({ ...CLOSED, frontRight: "open" })).toBe("frontRight");
    expect(firstOpenDoor({ ...CLOSED, frontRight: "locked" })).toBeNull();
  });
});

describe("computeCameraView", () => {
  it("cửa đóng, kính đóng → giữ nguyên góc mặc định", () => {
    expect(computeCameraView(null, 0).orbit).toBe(ORBIT_DEFAULT);
  });

  it("chỉ hạ kính (không mở cửa) → giữ hành vi cũ: xoay nhẹ", () => {
    expect(computeCameraView(null, 50).orbit).toBe("28deg 78deg auto");
  });

  /**
   * Quy ước model-viewer: theta=0 nhìn từ đầu xe (+Z), theta=+90 từ bên trái
   * (+X, phía "l" trong tên node .gltf). Nên cửa bên trái phải ra góc DƯƠNG,
   * bên phải ra góc ÂM — đảo dấu là camera ngó sang đúng mạn xe đối diện.
   */
  it("cửa trái ra góc dương, cửa phải ra góc âm", () => {
    expect(computeCameraView("frontLeft", 0).orbit).toMatch(/^70deg /);
    expect(computeCameraView("rearLeft", 0).orbit).toMatch(/^110deg /);
    expect(computeCameraView("frontRight", 0).orbit).toMatch(/^-70deg /);
    expect(computeCameraView("rearRight", 0).orbit).toMatch(/^-110deg /);
  });

  /**
   * Regression cho hai lỗi hình ảnh liên tiếp ngày 2026-08-15. Bản đầu ghé sát
   * bằng bán kính 0.62 lần chiều dài xe — camera lọt vào trong khối bao, near
   * plane xẻ đôi thân xe. Lùi ra 1.15 thì hết xẻ, nhưng cận cảnh lại phơi ra
   * khuyết tật có sẵn của model: mở cửa thì kính đứng nguyên tại chỗ vì nó là
   * mesh rời. Kết luận: camera CHỈ được đổi góc, không bao giờ đổi khoảng cách.
   */
  it("không bao giờ đổi khoảng cách — mọi góc nhìn đều để `auto`", () => {
    const everyView = [
      computeCameraView(null, 0),
      computeCameraView(null, 100),
      computeCameraView("frontLeft", 0),
      computeCameraView("frontRight", 0),
      computeCameraView("rearLeft", 100),
      computeCameraView("rearRight", 50),
    ];

    for (const view of everyView) {
      expect(view.orbit.split(" ")[2]).toBe("auto");
    }
  });

  it("không đặt camera-target: dời điểm ngắm cũng là một kiểu ghé sát", () => {
    expect(computeCameraView("frontLeft", 0)).not.toHaveProperty("target");
  });
});
