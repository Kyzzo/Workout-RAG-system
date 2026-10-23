import { API_URL } from "./apiUrl";

// The one client every backend call goes through (JSON requests and the
// streamed chat alike). It attaches the Clerk session token, retries once
// with a fresh token on a 401, and turns a non-2xx response into an ApiError
// carrying FastAPI's readable `detail` instead of raw JSON.

export type ApiOptions = { method?: string; body?: unknown; signal?: AbortSignal };
export type Api = <T>(path: string, options?: ApiOptions) => Promise<T>;
// Resolves to the raw Response (any status) so the caller can read a stream.
export type ApiStream = (path: string, body: unknown, signal?: AbortSignal) => Promise<Response>;
export type TokenGetter = (options?: { skipCache?: boolean }) => Promise<string | null>;

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// FastAPI answers {"detail": "..."} for most errors and, for a 422,
// {"detail": [{loc, msg, type}, ...]}. Anything else is shown as sent.
export function readableDetail(text: string): string {
  try {
    const data: unknown = JSON.parse(text);
    if (data && typeof data === "object" && "detail" in data) {
      const detail = (data as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      if (Array.isArray(detail)) {
        const messages = detail
          .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
          .filter(Boolean);
        if (messages.length) return messages.join("; ");
      }
    }
  } catch {
    // Not JSON: fall through to the text itself.
  }
  return text.trim();
}

export function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  return String(err);
}

export function createApiClient(getToken: TokenGetter) {
  async function send(path: string, options: ApiOptions, fresh: boolean) {
    const token = await getToken(fresh ? { skipCache: true } : undefined);
    return fetch(`${API_URL}${path}`, {
      method: options.method ?? "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  }

  // Clerk session tokens last 60 seconds. A request that waited in line (the
  // browser's per-host connection limit, a busy server) can arrive with its
  // token already expired: retry once with a freshly minted one.
  async function request(path: string, options: ApiOptions) {
    const res = await send(path, options, false);
    if (res.status !== 401) return res;
    return send(path, options, true);
  }

  const api: Api = async <T,>(path: string, options: ApiOptions = {}): Promise<T> => {
    const res = await request(path, options);
    if (!res.ok) {
      const detail = readableDetail(await res.text());
      throw new ApiError(res.status, detail || `Request failed: ${res.status}`);
    }
    // 204 No Content (deletes) has no body to parse.
    return (res.status === 204 ? undefined : await res.json()) as T;
  };

  const stream: ApiStream = (path, body, signal) => request(path, { method: "POST", body, signal });

  return { api, stream };
}
