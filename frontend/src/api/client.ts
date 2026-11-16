let version = "";

export async function initClient(): Promise<void> {
  const resp = await fetch("/initialize.json");
  if (!resp.ok) throw new Error("Cannot reach NextPanel backend");
  const data = await resp.json();
  version = data.version;
}

export function appVersion(): string {
  return version;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(status: number, message: string, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api/v1${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    let code: string | undefined;
    try {
      const data = await resp.json();
      if (typeof data.detail?.message === "string" && typeof data.detail?.code === "string") {
        detail = data.detail.message;
        code = data.detail.code;
      } else {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      /* not json */
    }
    throw new ApiError(resp.status, detail, code);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  del: <T>(path: string) => request<T>("DELETE", path),
};
