/**
 * AImagician Dashboard API
 * Types match backend dashboard/summary response.
 */

import { get } from './client';

export interface DashboardData {
  recent_articles: any[];
  pending_series_entries: any[];
  platform_coverage: any[];
  notion_outbox_backlog: any[];
  recent_severe_events: any[];
  platform_health: Array<{
    platform: string;
    health: string;
    session_status: string;
    blocked_jobs_count: number;
  }>;
  active_runs: any[];
  failed_jobs: any[];
  manual_blockers: any[];
  recent_runtime_events: any[];
}

export async function getDashboard(): Promise<DashboardData> {
  return get<DashboardData>('/api/dashboard/summary');
}

export interface DashboardAnalyticsData {
  article_count: number;
  publication_count: number;
  published_public_count: number;
  draft_created_count: number;
  failed_publication_count: number;
  active_run_count: number;
  queued_job_count: number;
  failed_job_count: number;
  severe_event_counts: Array<{ key: string; count: number }>;
  severe_event_type_counts: Array<{ key: string; count: number }>;
}

export async function getDashboardAnalytics(): Promise<DashboardAnalyticsData> {
  return get<DashboardAnalyticsData>('/api/dashboard/analytics');
}

export async function getHealth(): Promise<{ status: string; version?: string }> {
  return get('/api/health');
}
