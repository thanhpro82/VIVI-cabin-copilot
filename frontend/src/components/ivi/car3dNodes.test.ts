import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { DOOR_GROUP_NODE_NAMES, DOOR_NODE_NAMES, TRUNK_NODE_NAME } from "./car3dNodes";
import type { DoorKey } from "./car3dCamera";

/**
 * Đối chiếu thẳng với file model thật, không mock.
 *
 * Lý do tồn tại: gõ sai một tên node KHÔNG làm vỡ gì cả — `getObjectByName` trả
 * `undefined`, `Car3DViewer` bỏ qua im lặng, và bộ phận đó đơn giản là không
 * nhúc nhích khi mở cửa. Không có bài test này thì lỗi kiểu đó chỉ lộ ra khi có
 * người mở cửa trên màn hình và để ý thấy thiếu — tức là lúc đang demo.
 */
const SCENE_PATH = path.resolve(
  import.meta.dirname,
  "../../../public/assets/models/sedan-realistic/scene.gltf",
);

const nodeNames: Set<string> = new Set(
  (JSON.parse(readFileSync(SCENE_PATH, "utf8")) as { nodes: { name?: string }[] }).nodes
    .map((node) => node.name)
    .filter((name): name is string => Boolean(name)),
);

const DOOR_KEYS = Object.keys(DOOR_NODE_NAMES) as DoorKey[];

describe("tên node 3D khớp scene.gltf thật", () => {
  it.each(DOOR_KEYS)("vỏ cửa %s tồn tại trong model", (key) => {
    expect(nodeNames.has(DOOR_NODE_NAMES[key])).toBe(true);
  });

  it.each(DOOR_KEYS)("cả cụm cửa %s (vỏ + tấm ốp + kính) đều tồn tại", (key) => {
    for (const name of DOOR_GROUP_NODE_NAMES[key]) {
      expect(nodeNames.has(name), `thiếu node ${name}`).toBe(true);
    }
  });

  it("nắp cốp tồn tại", () => {
    expect(nodeNames.has(TRUNK_NODE_NAME)).toBe(true);
  });

  /**
   * Vỏ cửa phải nằm TRONG cụm: pivot bản lề được tính theo nó (`anchor`), nên
   * quên nó khỏi danh sách nhóm nghĩa là chính cánh cửa không xoay.
   */
  it.each(DOOR_KEYS)("cụm %s chứa đúng vỏ cửa của nó", (key) => {
    expect(DOOR_GROUP_NODE_NAMES[key]).toContain(DOOR_NODE_NAMES[key]);
  });

  /**
   * Mỗi cụm phải có đủ ba mảnh. Bản trước chỉ xoay vỏ cửa và đó chính là lỗi
   * "xe thừa ra một cánh cửa đứng im" — bài test này khoá lại số ba đó.
   */
  it.each(DOOR_KEYS)("cụm %s có đủ vỏ cửa, tấm ốp nội thất và kính", (key) => {
    const group = DOOR_GROUP_NODE_NAMES[key];

    expect(group).toHaveLength(3);
    expect(group.some((name) => name.includes("interior-panel"))).toBe(true);
    expect(group.some((name) => name.includes("window-glass"))).toBe(true);
  });

  /**
   * Mảnh kính tam giác cố định trên khung xe — nó KHÔNG đi theo cánh cửa, nên
   * kéo nó vào cụm sẽ xé nó khỏi trụ xe khi mở cửa.
   */
  it("không kéo theo kính trim cố định của khung xe", () => {
    const all = DOOR_KEYS.flatMap((key) => [...DOOR_GROUP_NODE_NAMES[key]]);
    expect(all.filter((name) => name.includes("trim-glass"))).toHaveLength(0);
  });

  it("không có node nào bị gán cho hai cửa khác nhau", () => {
    const all = DOOR_KEYS.flatMap((key) => [...DOOR_GROUP_NODE_NAMES[key]]);
    expect(new Set(all).size).toBe(all.length);
  });
});
