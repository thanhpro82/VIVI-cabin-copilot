import { sessionService } from "../session";
import { reportAuthFailure } from "../shared/authFailure";
import { ServiceError } from "../shared/errors";
import type { Place, PlaceLabel, Places, PlacesService } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface ApiErrorBody {
  error?: { code?: string; message?: string; retryable?: boolean };
}

function authHeaders(): Record<string, string> {
  const stored = sessionService.getStoredSession();
  if (!stored) {
    reportAuthFailure("Phiên đăng nhập đã hết hạn.");
    throw new ServiceError({ code: "AUTH_REQUIRED", message: "Chưa đăng nhập.", retryable: false });
  }
  return { Authorization: `Bearer ${stored.accessToken}` };
}

async function throwIfError(res: Response, fallbackCode: string): Promise<void> {
  if (res.ok) return;
  const body = (await res.json().catch(() => null)) as ApiErrorBody | null;
  const message = body?.error?.message ?? "Yêu cầu thất bại.";
  if (res.status === 401) reportAuthFailure(message);
  throw new ServiceError({
    code: body?.error?.code ?? fallbackCode,
    message,
    retryable: body?.error?.retryable ?? false,
  });
}

function mapPlace(
  label: PlaceLabel,
  raw: { destination_id: string; name: string | null; valid: boolean; updated_at: string } | null,
): Place | null {
  if (!raw) return null;
  return { label, destinationId: raw.destination_id, name: raw.name, valid: raw.valid, updatedAt: raw.updated_at };
}

function mapPlaces(raw: {
  home: Parameters<typeof mapPlace>[1];
  office: Parameters<typeof mapPlace>[1];
}): Places {
  return { home: mapPlace("home", raw.home), office: mapPlace("office", raw.office) };
}

export const realPlacesService: PlacesService = {
  async getPlaces() {
    const res = await fetch(`${API_BASE}/places`, { headers: authHeaders() });
    await throwIfError(res, "FORBIDDEN");
    const body = (await res.json()) as { data: Parameters<typeof mapPlaces>[0] };
    return mapPlaces(body.data);
  },

  async setPlace(label, destinationId) {
    const res = await fetch(`${API_BASE}/places/${label}`, {
      method: "PUT",
      headers: { ...authHeaders(), "Content-Type": "application/json; charset=utf-8" },
      body: JSON.stringify({ destination_id: destinationId }),
    });
    await throwIfError(res, "PLACE_DESTINATION_INVALID");
    const body = (await res.json()) as { data: Parameters<typeof mapPlaces>[0] };
    return mapPlaces(body.data);
  },

  async clearPlace(label) {
    const res = await fetch(`${API_BASE}/places/${label}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    // 204 không có thân — idempotent kể cả nhãn vốn chưa gán (đọc docstring backend).
    await throwIfError(res, "PLACE_LABEL_UNKNOWN");
  },
};
