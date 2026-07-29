const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001/api";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const fetcher = async (url: string) => {
  const res = await fetch(`${API_BASE}${url}`);
  if (!res.ok) throw new ApiError(res.status, `API error: ${res.status}`);
  const text = await res.text();
  return text ? JSON.parse(text) : null;
};

export async function apiPost(url: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${url}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || `API error: ${res.status}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export async function apiPatch(url: string, body: unknown) {
  const res = await fetch(`${API_BASE}${url}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || `API error: ${res.status}`);
  }
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export async function apiDelete(url: string) {
  const res = await fetch(`${API_BASE}${url}`, { method: "DELETE" });
  if (!res.ok) {
    throw new ApiError(res.status, `API error: ${res.status}`);
  }
}
