/**
 * AImagician Series API
 */

import { get, post, put } from './client';

export interface SeriesRead {
  id: string;
  name: string;
  description?: string;
  cover_url?: string;
  visual_style?: string;
  default_title_style?: string;
  default_writing_style?: string;
  default_cover_prompt?: string;
  created_at: string;
  updated_at: string;
}

export interface SeriesEntryRead {
  id: string;
  series_id: string;
  title: string;
  volume_id?: string;
  volume_name?: string;
  suggested_word_count?: number;
  suggested_depth?: string;
  status: string;
  archived: boolean;
  merged: boolean;
  article_id?: string;
  quality_status?: string;
  created_at: string;
  updated_at: string;
}

export interface SeriesWithEntries extends SeriesRead {
  entries: SeriesEntryRead[];
  stats: {
    total: number;
    pending: number;
    in_progress: number;
    completed: number;
    archived: number;
  };
}

export async function listSeries(): Promise<SeriesRead[]> {
  return get<SeriesRead[]>('/api/series');
}

export async function getSeries(id: string): Promise<SeriesWithEntries> {
  return get<SeriesWithEntries>(`/api/series/${id}`);
}

export async function createSeries(data: Partial<SeriesRead>): Promise<SeriesRead> {
  return post<SeriesRead>('/api/series', data);
}

export async function updateSeries(id: string, data: Partial<SeriesRead>): Promise<SeriesRead> {
  return put<SeriesRead>(`/api/series/${id}`, data);
}

export async function getSeriesEntries(seriesId: string): Promise<SeriesEntryRead[]> {
  return get<SeriesEntryRead[]>(`/api/series/${seriesId}/entries`);
}

export async function getNextSeriesEntry(seriesId: string): Promise<SeriesEntryRead | null> {
  return get<SeriesEntryRead | null>(`/api/series/${seriesId}/next-entry`);
}
