/**
 * AImagician Prompts API
 * Types match backend PromptRead/PromptVersionRead schemas.
 */

import { get, post, put } from './client';

export interface PromptDefinition {
  id: string;
  prompt_key: string;
  label: string;
  domain: string;
  purpose?: string;
  source_kind?: string;
  source_path?: string;
  source_ref?: string;
  expected_variables_json?: Record<string, any>;
  output_schema_json?: Record<string, any>;
  default_model?: string;
  default_provider?: string;
  default_timeout_seconds?: number;
  owner_domain?: string;
  is_active?: boolean;
  active_version_id?: string;
  metadata_json?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface PromptVersion {
  id: string;
  prompt_id: string;
  version: string;
  content: string;
  status: 'draft' | 'active' | 'archived';
  created_at: string;
  activated_at?: string;
}

export interface PromptSnapshot {
  id: string;
  prompt_id: string;
  version_id: string;
  article_id?: string;
  run_id?: string;
  job_id?: string;
  rendered_content: string;
  created_at: string;
}

export async function listPrompts(domain?: string): Promise<PromptDefinition[]> {
  return get<PromptDefinition[]>('/api/prompts', domain ? { domain } : undefined);
}

export async function getPrompt(id: string): Promise<PromptDefinition> {
  return get<PromptDefinition>(`/api/prompts/${id}`);
}

export async function createPrompt(data: Partial<PromptDefinition>): Promise<PromptDefinition> {
  return post<PromptDefinition>('/api/prompts', data);
}

export async function updatePrompt(id: string, data: Partial<PromptDefinition>): Promise<PromptDefinition> {
  return put<PromptDefinition>(`/api/prompts/${id}`, data);
}

export async function getPromptVersions(promptId: string): Promise<PromptVersion[]> {
  return get<PromptVersion[]>(`/api/prompts/${promptId}/versions`);
}

export async function createPromptVersion(promptId: string, data: { content: string; version?: string }): Promise<PromptVersion> {
  return post<PromptVersion>(`/api/prompts/${promptId}/versions`, data);
}

export async function activatePromptVersion(promptId: string, versionId: string): Promise<PromptVersion> {
  return post<PromptVersion>(`/api/prompt-versions/${versionId}/activate`);
}

export async function getPromptSnapshots(promptId: string, params?: {
  article_id?: string;
  limit?: number;
}): Promise<PromptSnapshot[]> {
  return get<PromptSnapshot[]>('/api/prompt-snapshots', { prompt_key: promptId, ...params } as Record<string, string | number | boolean | undefined>);
}

export async function diffPromptVersions(promptId: string, versionIdA: string, versionIdB: string): Promise<{
  diff: string;
}> {
  return get(`/api/prompt-versions/${versionIdA}/diff/${versionIdB}`);
}
