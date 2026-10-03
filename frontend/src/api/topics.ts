/**
 * AImagician Topics API
 * Types match backend TopicCandidateRead schemas.
 */

import { get, post } from './client';

export interface TopicCandidate {
  id: string;
  topic_key: string;
  title: string;
  hook?: string;
  summary?: string;
  source_kind: string;
  source_url?: string;
  evidence_urls: string[];
  status: string;
  adopted_article_id?: string;
  adopted_at?: string;
  metadata_json?: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface HotspotCollection {
  status: string;
  candidates: TopicCandidate[];
  next_action: string;
}

export async function listTopicCandidates(params?: {
  source?: string;
  adopted?: boolean;
  limit?: number;
}): Promise<TopicCandidate[]> {
  return get<TopicCandidate[]>('/api/topics/hotspots/candidates', params as Record<string, string | number | boolean | undefined>);
}

export async function collectHotspotTopics(source?: string): Promise<HotspotCollection> {
  return post<HotspotCollection>('/api/topics/hotspots/collect', { source });
}

export interface TopicAdoptResponse {
  status: string;
  candidate: TopicCandidate;
  article: {
    id: string;
    seed_title?: string;
    confirmed_title?: string;
    status: string;
    summary?: string;
    target_word_count?: number;
    actual_word_count?: number;
    created_at?: string;
    updated_at?: string;
  };
  next_action: string;
}

export async function adoptTopicCandidate(id: string, seriesId?: string): Promise<TopicAdoptResponse> {
  return post<TopicAdoptResponse>(`/api/topics/${id}/adopt`, { series_id: seriesId });
}

export async function ignoreTopicCandidate(id: string): Promise<void> {
  return post(`/api/topics/${id}/ignore`);
}
