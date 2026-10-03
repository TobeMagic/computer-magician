/**
 * AImagician Publish API
 * Types match backend PublicationDispatchRequest/Response schemas.
 */

import { get, post } from './client';

export type PublishMode = 'no_publish' | 'preview' | 'selected_platforms' | 'full_network' | 'missing_only' | 'force_republish';

export interface PublishRequest {
  article_id: string;
  mode: PublishMode;
  platforms?: string[];
  force_reason?: string;
  skip_platforms?: string[];
}

export interface PublishResult {
  article_id: string;
  mode: string;
  status: string;
  message: string;
  target_platforms: string[];
  queued_platforms: string[];
  skipped_platforms: string[];
  run?: any;
  job?: any;
  publications?: any[];
  publication_matrix?: Record<string, any>;
}

export interface PublicationRow {
  platform: string;
  status: string;
  public_url?: string;
  candidate_public_url?: string;
  draft_id?: string;
  visibility?: string;
  public_check_status?: string;
  can_refresh_public_url?: boolean;
  public_url_check_required?: boolean;
  next_action?: string;
  published_at?: string;
  error_message?: string;
}

export interface PlatformHealth {
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

export async function publishArticle(data: PublishRequest): Promise<PublishResult> {
  return post<PublishResult>(`/api/articles/${data.article_id}/publications/dispatch`, {
    mode: data.mode,
    platforms: data.platforms || [],
    force_republish: data.mode === 'force_republish',
    force_republish_reason: data.force_reason,
  });
}

export async function publishMissingPlatforms(articleId: string, platforms?: string[]): Promise<PublishResult> {
  return post<PublishResult>(`/api/articles/${articleId}/publications/dispatch`, {
    mode: 'selected_platforms',
    platforms: platforms || [],
  });
}

export async function getPublicationMatrix(articleId: string): Promise<PublicationRow[]> {
  return get<PublicationRow[]>(`/api/articles/${articleId}/publication-matrix`);
}

export async function refreshPublicUrl(articleId: string, platform: string): Promise<PublicationRow> {
  return post<PublicationRow>(`/api/articles/${articleId}/publications/${platform}/refresh-url`);
}

export async function getPlatformHealth(platform?: string): Promise<PlatformHealth[]> {
  if (platform) {
    return get<PlatformHealth[]>(`/api/platforms/${platform}/health`);
  }
  return get<PlatformHealth[]>('/api/platforms/health');
}

export async function checkPlatformSession(platform: string): Promise<{ health: PlatformHealth; run: any; job: any }> {
  return post<{ health: PlatformHealth; run: any; job: any }>(`/api/platforms/${platform}/check-session`, {});
}
