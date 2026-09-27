"use client";

import { useEffect, useRef, useState } from "react";
import "@google/model-viewer";
// $scene là export nội bộ (protected trong .d.ts, nhưng runtime chỉ là 1
// Symbol) — model-viewer KHÔNG có API công khai để xoay 1 node/mesh riêng lẻ
// (chỉ hỗ trợ animation clip bake sẵn trong file .gltf, mà scene.gltf hiện
// tại không có clip nào). Đây là cách duy nhất khả thi để mô phỏng mở/đóng
// cửa mà không cần dựng lại model bằng Blender — có rủi ro vỡ khi
// @google/model-viewer nâng version (xem model-viewer-base.d.ts).
import { $scene } from "@google/model-viewer/lib/model-viewer-base.js";
import type { ModelScene } from "@google/model-viewer/lib/three-components/ModelScene.js";
import { Box3, Group, Matrix4, type Object3D } from "three";
import type { VehicleState } from "@/lib/services/turn/types";
import { computeCameraView, firstOpenDoor, isDoorVisuallyOpen, type DoorKey } from "./car3dCamera";
import { DOOR_GROUP_NODE_NAMES, DOOR_NODE_NAMES, TRUNK_NODE_NAME } from "./car3dNodes";

const MODEL_SRC = "/assets/models/sedan-realistic/scene.gltf";


export interface Car3DViewerProps {
  /** null = đang tải trạng thái xe lần đầu (hiện skeleton), không tự gọi API. */
  vehicleState: VehicleState | null;
  className?: string;
}


// Tên node cửa lấy trực tiếp từ scene.gltf (mục "nodes", không phải "meshes").
// Trục dọc xe là Z — xác nhận qua node bánh xe thật trong scene.gltf:
// "DEF-Wheel.Ft.L_124" z=+1.28 (bánh trước) vs "DEF-Wheel.Bk.L_132" z=-1.63
// (bánh sau) → đầu xe hướng +Z. X dương = bên "l" (trái), X âm = bên "r"
// (phải) — khớp translation của chính node cửa (door-front-l x=+0.838,
// door-front-r x=-0.838). Dấu dưới đây suy ra từ toán xoay quanh trục Y
// (three.js): với bản lề đặt ở mép +Z của cửa (xem createDoorPivot), để mép
// còn lại (mép sau, nơi tay nắm) văng RA XA thân xe — tức +X cho cửa bên
// trái, -X cho cửa bên phải — góc xoay phải ÂM ở bên trái, DƯƠNG ở bên phải.
const DOOR_OPEN_SIGN: Record<DoorKey, 1 | -1> = {
  frontLeft: -1,
  frontRight: 1,
  rearLeft: -1,
  rearRight: 1,
};

const DOOR_OPEN_RADIANS = 0.75; // ~43°
const DOOR_ANIM_MS = 450;

// Nắp cốp lật lên quanh trục X (ngang), không phải trục Y như cửa — dấu +
// suy ra từ cùng công thức xoay quanh trục X của three.js áp cho góc xa nhất
// (thấp nhất + xa bản lề nhất) của nắp cốp, CHƯA verify trực quan.
const TRUNK_OPEN_RADIANS = 0.9; // ~52°
const TRUNK_ANIM_MS = 500;

type HingeAxis = "x" | "y";

function getModelScene(viewer: HTMLElement): ModelScene | null {
  return (viewer as unknown as { [$scene]?: ModelScene })[$scene] ?? null;
}

function animateRotation(
  node: Object3D,
  axis: HingeAxis,
  targetRadians: number,
  durationMs: number,
  scene: ModelScene,
  isCancelled: () => boolean,
) {
  const startRadians = node.rotation[axis];
  if (Math.abs(startRadians - targetRadians) < 0.001) return;
  const startTime = performance.now();

  function tick(now: number) {
    if (isCancelled()) return;
    const t = Math.min(1, (now - startTime) / durationMs);
    const eased = 1 - (1 - t) * (1 - t); // ease-out
    node.rotation[axis] = startRadians + (targetRadians - startRadians) * eased;
    scene.queueRender();
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/**
 * Bounding box của node trong hệ toạ độ CỤC BỘ của chính nó (không phải thế
 * giới) — dùng để tìm cạnh bản lề thật thay vì xoay quanh tâm node (đó là lý
 * do bản cửa đầu tiên xoay "ngược": xoay quanh gốc node, gần tâm cửa, khiến
 * cả 2 mép cùng vung ra thay vì có 1 mép đứng yên như bản lề thật).
 */
function computeLocalBoundingBox(node: Object3D): Box3 {
  const box = new Box3();
  const inverseWorld = new Matrix4().copy(node.matrixWorld).invert();
  node.traverse((child) => {
    const mesh = child as unknown as {
      isMesh?: boolean;
      geometry?: { boundingBox: Box3 | null; computeBoundingBox: () => void };
      matrixWorld: Matrix4;
    };
    if (!mesh.isMesh || !mesh.geometry) return;
    if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
    const localBox = mesh.geometry.boundingBox;
    if (!localBox) return;
    const relative = new Matrix4().multiplyMatrices(inverseWorld, mesh.matrixWorld);
    box.union(localBox.clone().applyMatrix4(relative));
  });
  return box;
}

/** Chèn 1 Group vô hình làm cha của node, đặt đúng tại điểm bản lề
 * (`pivotOffset` tính theo hệ cục bộ của node), rồi dịch node bù lại — hình
 * dạng lúc đứng yên không đổi, chỉ đổi tâm xoay. */
function createHingePivot(node: Object3D, pivotOffset: { y?: number; z?: number }): Object3D {
  return createHingePivotForGroup([node], node, pivotOffset);
}

/**
 * Như `createHingePivot` nhưng gom NHIỀU node vào cùng một pivot (vỏ cửa + tấm
 * ốp + kính, xem DOOR_GROUP_NODE_NAMES). Điểm bản lề tính theo `anchor` — vỏ
 * cửa — vì kính nằm cao hơn hẳn, lấy cả cụm sẽ đẩy trục xoay lệch lên trên.
 *
 * Mấu chốt là dòng `node.position.sub(pivot.position)`: mỗi node có `matrix`
 * riêng đặt nó vào đúng chỗ trên xe, nên sau khi đổi cha phải trừ đi vị trí
 * pivot để GIỮ NGUYÊN vị trí tuyệt đối, chứ không phải gán cho tất cả cùng một
 * giá trị. Bản đầu gán chung `(0, -offsetY, -offsetZ)` cho mọi node — đúng cho
 * trường hợp một node, nhưng với ba node thì nó dồn kính và tấm ốp về đúng chỗ
 * vỏ cửa, ra lỗi "kính chồng đè lên cánh cửa".
 */
function createHingePivotForGroup(
  nodes: Object3D[],
  anchor: Object3D,
  pivotOffset: { y?: number; z?: number },
): Object3D {
  const parent = anchor.parent;
  if (!parent) return anchor;
  const pivot = new Group();
  pivot.name = `${anchor.name}-hinge-pivot`;
  pivot.position.copy(anchor.position);
  pivot.position.y += pivotOffset.y ?? 0;
  pivot.position.z += pivotOffset.z ?? 0;
  parent.add(pivot);
  nodes.forEach((node) => {
    const keepAt = node.position.clone().sub(pivot.position);
    pivot.add(node);
    node.position.copy(keepAt);
  });
  return pivot;
}

/** Dựng pivot bản lề đúng 1 lần cho mỗi cửa rồi cache lại — các lần đổi
 * trạng thái sau chỉ xoay pivot đã có, không dựng lại. */
function ensureDoorPivots(
  scene: ModelScene,
  cache: Partial<Record<DoorKey, Object3D>>,
): Partial<Record<DoorKey, Object3D>> {
  if (Object.keys(cache).length === Object.keys(DOOR_NODE_NAMES).length) return cache;
  scene.model.updateMatrixWorld(true);
  (Object.keys(DOOR_NODE_NAMES) as DoorKey[]).forEach((key) => {
    if (cache[key]) return;
    const shell = scene.model.getObjectByName(DOOR_NODE_NAMES[key]);
    if (!shell) return;
    const hingeZ = computeLocalBoundingBox(shell).max.z;
    const group = DOOR_GROUP_NODE_NAMES[key]
      .map((nodeName) => scene.model.getObjectByName(nodeName))
      .filter((node): node is Object3D => Boolean(node));
    cache[key] = createHingePivotForGroup(group, shell, { z: hingeZ });
  });
  return cache;
}

/** Nắp cốp bản lề ở mép trên-trước (max Y, max Z) — top vì lật lên, trước vì
 * giáp kính hậu, cùng quy ước "bản lề ở mép hướng về đầu xe" như cửa. */
function ensureTrunkPivot(scene: ModelScene, cache: { current: Object3D | null }): Object3D | null {
  if (cache.current) return cache.current;
  scene.model.updateMatrixWorld(true);
  const node = scene.model.getObjectByName(TRUNK_NODE_NAME);
  if (!node) return null;
  const box = computeLocalBoundingBox(node);
  cache.current = createHingePivot(node, { y: box.max.y, z: box.max.z });
  return cache.current;
}

function animateDoors(
  scene: ModelScene,
  doors: VehicleState["doors"],
  pivotCache: Partial<Record<DoorKey, Object3D>>,
  isCancelled: () => boolean,
) {
  const pivots = ensureDoorPivots(scene, pivotCache);
  (Object.keys(DOOR_NODE_NAMES) as DoorKey[]).forEach((key) => {
    const pivot = pivots[key];
    if (!pivot) return;
    const target = isDoorVisuallyOpen(doors[key]) ? DOOR_OPEN_RADIANS * DOOR_OPEN_SIGN[key] : 0;
    animateRotation(pivot, "y", target, DOOR_ANIM_MS, scene, isCancelled);
  });
}

function animateTrunk(
  scene: ModelScene,
  trunk: string,
  pivotCache: { current: Object3D | null },
  isCancelled: () => boolean,
) {
  const pivot = ensureTrunkPivot(scene, pivotCache);
  if (!pivot) return;
  const target = trunk === "open" ? TRUNK_OPEN_RADIANS : 0;
  animateRotation(pivot, "x", target, TRUNK_ANIM_MS, scene, isCancelled);
}

function doorsSignature(vehicleState: VehicleState): string {
  const { frontLeft, frontRight, rearLeft, rearRight } = vehicleState.doors;
  return `${frontLeft}|${frontRight}|${rearLeft}|${rearRight}|${vehicleState.trunk.position}`;
}

function maxWindowOpenPercent(vehicleState: VehicleState): number {
  const { frontLeft, frontRight, rearLeft, rearRight } = vehicleState.windows;
  return Math.max(frontLeft, frontRight, rearLeft, rearRight);
}

/**
 * Component thuần theo docs/ARCHITECTURE.md mục 5 — chỉ nhận `vehicleState`
 * qua props, không tự gọi API/WS. Bám sát cách ánh xạ camera-orbit/exposure
 * của bản đặc tả gốc `vivi_ivi_vf8style (1).html` (updateCar3D()). Model
 * không tách mesh đèn riêng nên "đèn pha" chỉ mô phỏng bằng glow nền ở 2 vị
 * trí đèn (giống bản gốc), không phải tia sáng thật. `lights`/`trunk` giờ là
 * dữ liệu BE thật, không còn là GAP mock-only — xem types.ts. Cửa trời không có trong P0 nên
 * bỏ hẳn nhánh đó của bản gốc.
 */
export function Car3DViewer({ vehicleState, className }: Car3DViewerProps) {
  const prevDoorsSignature = useRef<string | null>(null);
  const [pulse, setPulse] = useState(false);
  const viewerRef = useRef<HTMLElement | null>(null);
  const doorPivotsRef = useRef<Partial<Record<DoorKey, Object3D>>>({});
  const trunkPivotRef = useRef<Object3D | null>(null);
  // issue #323: chữ "Đang tải mô hình xe…" trước đây chỉ hiện lúc
  // `vehicleState === null` — tức TRƯỚC KHI `<model-viewer>` được mount và bắt
  // đầu tải model 3D (~43 MB, ~44 s trên VPS) — rồi biến mất đúng lúc phần tải
  // nặng thật sự bắt đầu. Theo dõi 2 sự kiện gốc của model-viewer để hiện tiến
  // độ THẬT trong lúc nó đang tải: `progress` (0-1) và `load` (xong).
  const [modelLoaded, setModelLoaded] = useState(false);
  const [modelProgress, setModelProgress] = useState(0);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl || !vehicleState) return;
    function onProgress(e: Event) {
      const detail = (e as CustomEvent<{ totalProgress: number }>).detail;
      setModelProgress(detail?.totalProgress ?? 0);
    }
    function onLoad() {
      setModelLoaded(true);
    }
    viewerEl.addEventListener("progress", onProgress);
    viewerEl.addEventListener("load", onLoad, { once: true });
    return () => {
      viewerEl.removeEventListener("progress", onProgress);
      viewerEl.removeEventListener("load", onLoad);
    };
  }, [vehicleState]);

  useEffect(() => {
    if (!vehicleState) return;
    const signature = doorsSignature(vehicleState);
    if (prevDoorsSignature.current !== null && prevDoorsSignature.current !== signature) {
      setPulse(true);
      const timer = setTimeout(() => setPulse(false), 600);
      return () => clearTimeout(timer);
    }
    prevDoorsSignature.current = signature;
  }, [vehicleState]);

  useEffect(() => {
    const viewerEl = viewerRef.current;
    if (!viewerEl || !vehicleState) return;
    let cancelled = false;
    const doors = vehicleState.doors;
    const trunk = vehicleState.trunk.position;

    function apply() {
      const scene = viewerEl && getModelScene(viewerEl);
      if (!scene || cancelled) return;
      animateDoors(scene, doors, doorPivotsRef.current, () => cancelled);
      animateTrunk(scene, trunk, trunkPivotRef, () => cancelled);
    }

    if ((viewerEl as unknown as { loaded?: boolean }).loaded) {
      apply();
    } else {
      viewerEl.addEventListener("load", apply, { once: true });
    }

    return () => {
      cancelled = true;
      viewerEl.removeEventListener("load", apply);
    };
  }, [vehicleState]);

  // Cửa mở thì camera xoay về phía cửa đó — chỉ xoay, giữ nguyên khoảng cách
  // khung mặc định (xem DOOR_VIEW_PHI_DEG trong car3dCamera.ts về việc đã thử
  // ghé sát rồi phải bỏ).
  const openDoor = vehicleState ? firstOpenDoor(vehicleState.doors) : null;
  const windowOpenPercent = vehicleState ? maxWindowOpenPercent(vehicleState) : 0;
  const { orbit: cameraOrbit } = computeCameraView(openDoor, windowOpenPercent);

  const temperatureC = vehicleState?.hvac.temperatureC ?? 24;
  const acExposure = vehicleState?.hvac.power
    ? 0.85 + ((temperatureC - 16) / 14) * 0.35
    : 0.85;
  // `headlight` là enum, không phải boolean (issue #115). `auto` nghĩa là xe tự
  // quyết theo cảm biến sáng — mô phỏng không có cảm biến đó nên coi như chưa
  // bật, còn `high_beam` sáng hơn `low_beam` đúng như tên gọi.
  const headlightMode = vehicleState?.lights.headlight ?? "auto";
  const headlightGlow = headlightMode === "auto" ? 0 : headlightMode === "high_beam" ? 0.25 : 0.15;
  const exposure = (acExposure + headlightGlow).toFixed(2);

  return (
    <div
      className={`car3d-stage relative overflow-hidden rounded-(--r-md) ${pulse ? "car3d-stage--pulse" : ""} ${className ?? ""}`}
      style={{
        // Trước đây hard-code hex (#181D26/#0D1017, vi phạm quy tắc "không
        // thêm hex mới") và không có điểm nhấn màu nào — chỉ 1 vignette phẳng
        // tối. Đổi sang token có sẵn (--bg2 sáng hơn --bg) làm nền, cộng 1
        // quầng sáng cyan phía sau xe làm điểm nhấn, cộng vài chấm sao nhỏ
        // (kỹ thuật giống hệt nền <body>, xem globals.css) rải ở phần trên/2
        // bên — tránh giữa khung nơi xe đứng để không rối mắt.
        background:
          "radial-gradient(1.4px 1.4px at 18% 14%, color-mix(in srgb, var(--ink) 80%, transparent), transparent 60%)," +
          "radial-gradient(1.2px 1.2px at 78% 18%, color-mix(in srgb, var(--ink) 65%, transparent), transparent 60%)," +
          "radial-gradient(1.6px 1.6px at 88% 42%, color-mix(in srgb, var(--ink) 70%, transparent), transparent 60%)," +
          "radial-gradient(1.2px 1.2px at 10% 46%, color-mix(in srgb, var(--ink) 55%, transparent), transparent 60%)," +
          "radial-gradient(1.4px 1.4px at 58% 10%, color-mix(in srgb, var(--ink) 75%, transparent), transparent 60%)," +
          "radial-gradient(ellipse 65% 50% at 50% 58%, color-mix(in srgb, var(--cyan) 28%, transparent) 0%, transparent 72%)," +
          "radial-gradient(ellipse at 50% 68%, var(--bg2) 0%, var(--bg) 82%)",
      }}
    >
      <div
        aria-hidden
        className={`car3d-headlight-glow pointer-events-none absolute inset-0 transition-opacity duration-500 ${
          headlightMode === "high_beam" ? "opacity-100" : headlightMode === "low_beam" ? "opacity-60" : "opacity-0"
        }`}
      />
      {vehicleState ? (
        <>
          <model-viewer
            ref={viewerRef}
            src={MODEL_SRC}
            alt="Mô hình 3D xe VIVI Cabin Copilot"
            camera-controls
            camera-orbit={cameraOrbit}
            exposure={exposure}
            shadow-intensity="0.9"
            environment-image="neutral"
            interaction-prompt="none"
            style={{ width: "100%", height: "100%" }}
          />
          {/* issue #323 bước 1 — tiến độ THẬT (`progress` của model-viewer), không phải
              chữ tĩnh biến mất ngay lúc phần tải nặng bắt đầu. Đè lên model-viewer thay vì
              thay chỗ nó, vì model-viewer đã bắt đầu tải ngay khi mount — ẩn nó đi không
              dừng được request đang chạy, chỉ che mất tín hiệu duy nhất của việc đó. */}
          {!modelLoaded && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 bg-bg/70">
              <p className="text-sm text-ink-dim">Đang tải mô hình xe… {Math.round(modelProgress * 100)}%</p>
              <div className="h-1 w-40 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-cyan transition-[width]"
                  style={{ width: `${Math.round(modelProgress * 100)}%` }}
                />
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-ink-dim">
          Đang tải mô hình xe…
        </div>
      )}
      <p className="absolute right-3 bottom-2 font-technical text-[9px] leading-tight text-ink-dim/60">
        &quot;Generic Sedan Car&quot; · Márcio Meireles · CC-BY 4.0
      </p>
    </div>
  );
}
