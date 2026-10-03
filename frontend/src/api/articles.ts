/**
 * AImagician Articles API
 * Types match backend ArticleRead schema exactly.
 */

import { get, post, put } from './client';

export interface ArticleRead {
  id: string;
  source_kind: string;
  source_ref?: string;
  notion_page_id?: string;
  notion_url?: string;
  slug?: string;
  seed_title?: string;
  confirmed_title?: string;
  short_title?: string;
  subtitle?: string;
  summary?: string;
  opening_hook?: string;
  article_style_key?: string;
  content_mode_key?: string;
  target_word_count?: number;
  actual_word_count?: number;
  target_platforms: string[];
  tags: string[];
  platform_tags?: Record<string, string[]>;
  status: string;
  review_status?: string;
  review_risk_level?: string;
  review_issue_codes?: string[];
  blocking_count: number;
  warning_count: number;
  research_evidence_count: number;
  current_version_id?: string;
  metadata_json?: Record<string, any>;
  archived_at?: string;
  created_at: string;
  updated_at: string;
  series_id?: string;
  series_name?: string;
}

export interface ArticleVersion {
  id: string;
  article_id: string;
  version_number: number;
  body_markdown?: string;
  body_html?: string;
  change_summary?: string;
  created_at: string;
  created_by?: string;
}

export interface ArticleRun {
  id: string;
  article_id: string;
  status: string;
  trigger: string;
  started_at?: string;
  finished_at?: string;
  error_message?: string;
}

export interface QualityFinding {
  id: string;
  article_id: string;
  category: string;
  severity: string;
  description: string;
  module?: string;
  fixed: boolean;
  created_at: string;
}

export async function listArticles(params?: {
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ArticleRead[]> {
  return get<ArticleRead[]>('/api/articles', params as Record<string, string | number | boolean | undefined>);
}

export async function searchArticles(params?: {
  search?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ArticleRead[]> {
  return get<ArticleRead[]>('/api/articles', params as Record<string, string | number | boolean | undefined>);
}

export async function getArticle(id: string): Promise<ArticleRead> {
  return get<ArticleRead>(`/api/articles/${id}`);
}

export async function createArticle(data: {
  seed_title: string;
  series_id?: string;
  target_platforms?: string[];
}): Promise<ArticleRead> {
  return post<ArticleRead>('/api/articles', data);
}

export async function updateArticle(id: string, data: Partial<ArticleRead>): Promise<ArticleRead> {
  return put<ArticleRead>(`/api/articles/${id}`, data);
}

export async function getArticleVersions(articleId: string): Promise<ArticleVersion[]> {
  return get<ArticleVersion[]>(`/api/articles/${articleId}/versions`);
}

export async function getArticleBody(articleId: string, versionId?: string): Promise<{ body_markdown: string; body_html?: string }> {
  if (versionId) {
    const versions = await get<ArticleVersion[]>(`/api/articles/${articleId}/versions`);
    const version = versions.find(v => v.id === versionId);
    return { body_markdown: version?.body_markdown || '', body_html: version?.body_html };
  }
  const versions = await get<ArticleVersion[]>(`/api/articles/${articleId}/versions`);
  const latest = versions[0];
  return { body_markdown: latest?.body_markdown || '', body_html: latest?.body_html };
}

export async function getArticleJobs(articleId: string): Promise<ArticleRun[]> {
  return get<ArticleRun[]>(`/api/articles/${articleId}/jobs`);
}

export async function getArticleQualityFindings(articleId: string): Promise<QualityFinding[]> {
  return get<QualityFinding[]>(`/api/articles/${articleId}/quality-findings`);
}

export async function listUnpublishedArticles(): Promise<ArticleRead[]> {
  return get<ArticleRead[]>('/api/articles', { status: 'ready_to_publish' } as Record<string, string | number | boolean | undefined>);
}

// Domain job APIs
export interface ArticleDomainJobResponse {
  article: ArticleRead;
  run: ArticleRun;
  job: { id: string; status: string };
  next_action: string;
}

export async function triggerResearchJob(
  articleId: string,
  data?: { query?: string; provider?: string; extract_limit?: number; search_per_query?: number },
): Promise<ArticleDomainJobResponse> {
  return post<ArticleDomainJobResponse>(`/api/articles/${articleId}/research-jobs`, data || {});
}

export async function triggerTitleOutlineJob(
  articleId: string,
  data?: { title?: string; source_notes?: string; direction?: string; content_mode?: string; article_style?: string; target_word_count?: number; keywords?: string },
): Promise<ArticleDomainJobResponse> {
  return post<ArticleDomainJobResponse>(`/api/articles/${articleId}/title-outline-jobs`, data || {});
}

export async function triggerBodyJob(
  articleId: string,
  data?: { confirmed_title?: string; source_notes?: string; direction?: string; content_mode?: string; article_style?: string; target_word_count?: number; keywords?: string },
): Promise<ArticleDomainJobResponse> {
  return post<ArticleDomainJobResponse>(`/api/articles/${articleId}/body-jobs`, data || {});
}

export async function triggerCoverBriefJob(
  articleId: string,
  data?: { style_direction?: string },
): Promise<ArticleDomainJobResponse> {
  return post<ArticleDomainJobResponse>(`/api/articles/${articleId}/cover-brief-jobs`, data || {});
}

export async function getArticleEvidence(articleId: string): Promise<any[]> {
  return get<any[]>(`/api/articles/${articleId}/evidence`);
}
