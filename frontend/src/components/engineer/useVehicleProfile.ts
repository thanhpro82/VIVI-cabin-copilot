"use client";

import { useCallback, useEffect, useState } from "react";
import { engineerService } from "@/lib/services/engineer";
import type { VehicleBattery, VehicleProfile, VehicleTrim } from "@/lib/services/engineer";

/**
 * State cho cấu hình xe demo (issue #125) — tách khỏi component vì **chip trên
 * header và form trong popover cùng đọc một profile**: chip hiện nhãn, form sửa.
 *
 * Không gộp vào `EngineerShellProvider`: provider giữ luồng WS dùng chung cho mọi
 * panel, còn cái này chỉ hai chỗ đọc và có vòng đời riêng (request rời, không đến
 * từ stream). Nhét vào provider là bắt cả bảng log render lại mỗi lần bấm lưu.
 */
export interface VehicleProfileState {
  profile: VehicleProfile | null;
  trim: VehicleTrim | null;
  battery: VehicleBattery | null;
  setTrim: (v: VehicleTrim | null) => void;
  setBattery: (v: VehicleBattery | null) => void;
  busy: boolean;
  error: string | null;
  /** Đã đổi lựa chọn so với thứ backend đang giữ. */
  dirty: boolean;
  /** Đọc thẳng `is_complete` của backend — KHÔNG tính lại `trim != null && battery != null`. */
  configured: boolean;
  save: (trim: VehicleTrim | null, battery: VehicleBattery | null) => Promise<void>;
}

export function useVehicleProfile(): VehicleProfileState {
  const [profile, setProfile] = useState<VehicleProfile | null>(null);
  const [trim, setTrim] = useState<VehicleTrim | null>(null);
  const [battery, setBattery] = useState<VehicleBattery | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const adopt = useCallback((next: VehicleProfile) => {
    setProfile(next);
    setTrim(next.trim);
    setBattery(next.battery);
  }, []);

  useEffect(() => {
    let alive = true;
    engineerService
      .getVehicleProfile()
      .then((p) => {
        if (alive) adopt(p);
      })
      // Đọc hỏng thì để `profile` ở null và báo lỗi — KHÔNG dựng một profile rỗng
      // giả, vì rỗng-giả trông y hệt "xe chưa khai báo" thật.
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "Không đọc được cấu hình xe.");
      });
    return () => {
      alive = false;
    };
  }, [adopt]);

  const save = useCallback(
    async (nextTrim: VehicleTrim | null, nextBattery: VehicleBattery | null) => {
      setBusy(true);
      setError(null);
      try {
        adopt(await engineerService.setVehicleProfile({ trim: nextTrim, battery: nextBattery }));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Lưu cấu hình thất bại.");
      } finally {
        setBusy(false);
      }
    },
    [adopt],
  );

  return {
    profile,
    trim,
    battery,
    setTrim,
    setBattery,
    busy,
    error,
    dirty: profile !== null && (trim !== profile.trim || battery !== profile.battery),
    configured: profile?.isComplete === true,
    save,
  };
}
