/**
 * AImagician Auth API
 */

import { post, get, setCsrfToken, clearAuthTokens } from './client';

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  authenticated: boolean;
  csrf_token: string;
  expires_at: string;
  user: {
    id: string;
    email: string;
    display_name: string;
  };
}

export interface SessionResponse {
  authenticated: boolean;
  csrf_token_required: boolean;
  expires_at?: string;
  user?: {
    id: string;
    email: string;
    is_admin: boolean;
  };
}

export async function login(email: string, password: string): Promise<LoginResponse> {
  const res = await post<LoginResponse>('/api/auth/login', { email, password });
  setCsrfToken(res.csrf_token);
  return res;
}

export async function logout(): Promise<void> {
  try {
    await post('/api/auth/logout');
  } finally {
    clearAuthTokens();
  }
}

export async function getSession(): Promise<SessionResponse> {
  return get<SessionResponse>('/api/auth/session');
}

export async function refreshAgentToken(refreshToken: string): Promise<{ access_token: string }> {
  return post<{ access_token: string }>('/api/auth/agent-token/refresh', { refresh_token: refreshToken });
}
