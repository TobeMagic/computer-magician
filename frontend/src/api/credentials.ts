/**
 * AImagician Credentials API
 * Types match backend PlatformHealthRead and login schemas.
 * All login endpoints return PlatformHealthCheckResponse.
 */

import { get, post } from './client';

export interface PlatformCredential {
  id: string;
  platform: string;
  status: string;
  readiness: string;
  credential_id?: string;
  last_checked_at?: string;
  blockers_json?: Record<string, any>;
  warnings_json?: Record<string, any>;
  capabilities_json?: Record<string, any>;
  metadata_json?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface PlatformLoginResponse {
  health: PlatformCredential;
  run: any;
  job: any;
}

export async function listCredentials(): Promise<PlatformCredential[]> {
  return get<PlatformCredential[]>('/api/platforms');
}

export async function uploadCredential(platform: string, data: {
  credential_kind: string;
  material: Record<string, any>;
  source_machine?: string;
  notes?: string;
}): Promise<any> {
  return post<any>(`/api/credentials/${platform}/upload`, data);
}

export async function requestCode(platform: string, phone: string): Promise<PlatformLoginResponse> {
  return post<PlatformLoginResponse>(`/api/platforms/${platform}/login/request-code`, { phone });
}

export async function submitCode(platform: string, code: string): Promise<PlatformLoginResponse> {
  return post<PlatformLoginResponse>(`/api/platforms/${platform}/login/submit-code`, { code });
}

export async function checkPlatformSessionHealth(platform: string): Promise<PlatformLoginResponse> {
  return post<PlatformLoginResponse>(`/api/platforms/${platform}/check-session`, {});
}

export async function bootstrapLogin(platform: string, data?: {
  login_method?: string;
}): Promise<PlatformLoginResponse> {
  return post<PlatformLoginResponse>(`/api/platforms/${platform}/login/bootstrap`, data || {});
}
