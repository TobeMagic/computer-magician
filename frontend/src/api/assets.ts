/**
 * AImagician Assets API
 * Types match backend ArticleAssetRead and duplicate check schemas.
 */

import { get } from './client';

export interface AssetRead {
  id: string;
  article_id: string;
  run_id?: string;
  job_id?: string;
  asset_type: string;
  role?: string;
  local_path?: string;
  hosted_url?: string;
  source_url?: string;
  source_kind?: string;
  prompt?: string;
  hook_text?: string;
  deck_text?: string;
  caption?: string;
  alt_text?: string;
  width?: number;
  height?: number;
  checksum?: string;
  selected_at?: string;
  metadata_json?: Record<string, any>;
  created_at: string;
}

export interface AssetDuplicateGroup {
  asset_id: string;
  checksum: string;
  duplicate_count: number;
  duplicates: AssetRead[];
  duplicate_groups?: any[];
  semantic_tag?: string;
  semantic_match_count?: number;
  semantic_matches?: any[];
}

export interface AssetDuplicateCheck {
  duplicates: AssetDuplicateGroup[];
  total_count: number;
}

export async function listAssets(params?: {
  type?: string;
  article_id?: string;
  limit?: number;
  offset?: number;
}): Promise<AssetRead[]> {
  return get<AssetRead[]>('/api/assets', params as Record<string, string | number | boolean | undefined>);
}

export async function getAsset(id: string): Promise<AssetRead> {
  return get<AssetRead>(`/api/assets/${id}`);
}

export async function getAssetDuplicates(): Promise<AssetDuplicateCheck> {
  const result = await get<AssetDuplicateGroup[]>('/api/asset-library/duplicates');
  return {
    duplicates: Array.isArray(result) ? result : [],
    total_count: Array.isArray(result) ? result.length : 0,
  };
}

export async function getAssetSemanticFit(id: string, articleId?: string): Promise<{ asset_id: string; fit_score: number; fit_reason: string }> {
  return get(`/api/assets/${id}/semantic-fit`, articleId ? { article_id: articleId } : undefined);
}
