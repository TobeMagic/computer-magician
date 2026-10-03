/**
 * AImagician API Client
 * Base fetch wrapper with auth, error handling, and CSRF support.
 * Uses session cookies (credentials: 'include') + CSRF token header.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

interface ApiOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

function buildUrl(path: string, params?: Record<string, string | number | boolean | undefined>): string {
  const url = new URL(path, API_BASE || window.location.origin);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
  }
  return url.toString();
}

const CSRF_STORAGE_KEY = 'aimagician_csrf_token';

let csrfToken: string | null = null;

function getCsrfToken(): string | null {
  return csrfToken;
}

export function setCsrfToken(token: string): void {
  csrfToken = token;
  try { sessionStorage.setItem(CSRF_STORAGE_KEY, token); } catch {}
}

export function clearAuthTokens(): void {
  csrfToken = null;
  try { sessionStorage.removeItem(CSRF_STORAGE_KEY); } catch {}
}

export function isAuthenticated(): boolean {
  return getCsrfToken() !== null;
}

export function initAuth(): void {
  const stored = typeof sessionStorage !== 'undefined' ? sessionStorage.getItem(CSRF_STORAGE_KEY) : null;
  if (stored) {
    csrfToken = stored;
  }
}

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === 'string' ? detail : JSON.stringify(detail));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function apiFetch<T>(path: string, options: ApiOptions = {}): Promise<T> {
  const { params, ...fetchOptions } = options;
  const url = buildUrl(path, params);

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(fetchOptions.headers as Record<string, string> || {}),
  };

  const csrf = getCsrfToken();
  if (csrf) {
    headers['X-CSRF-Token'] = csrf;
  }

  const res = await fetch(url, {
    ...fetchOptions,
    headers,
    credentials: 'include',
  });

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      detail = await res.text();
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json();
}

export function get<T>(path: string, params?: Record<string, string | number | boolean | undefined>): Promise<T> {
  return apiFetch<T>(path, { method: 'GET', params });
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined });
}

export function put<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined });
}

export function patch<T>(path: string, body?: unknown): Promise<T> {
  return apiFetch<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined });
}

export function del<T>(path: string): Promise<T> {
  return apiFetch<T>(path, { method: 'DELETE' });
}
