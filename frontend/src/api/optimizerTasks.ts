import { get, post, patch, del } from './client';

export interface OptimizerTask {
  id: string;
  source_type: string;
  title: string;
  description: string;
  related_article_id?: string;
  related_article_title?: string;
  attributed_issue_id?: string;
  priority: 'High' | 'Medium' | 'Low';
  status: 'Pending' | 'Applied' | 'Ignored';
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface OptimizerTaskCreate {
  source_type: string;
  title: string;
  description?: string;
  related_article_id?: string;
  related_article_title?: string;
  attributed_issue_id?: string;
  priority?: string;
  status?: string;
  metadata_json?: Record<string, unknown>;
}

export async function listOptimizerTasks(params?: {
  source_type?: string;
  status?: string;
  priority?: string;
  article_id?: string;
  limit?: number;
}): Promise<OptimizerTask[]> {
  const query = new URLSearchParams();
  if (params?.source_type) query.set('source_type', params.source_type);
  if (params?.status) query.set('status', params.status);
  if (params?.priority) query.set('priority', params.priority);
  if (params?.article_id) query.set('article_id', params.article_id);
  if (params?.limit) query.set('limit', String(params.limit));
  const qs = query.toString();
  return get<OptimizerTask[]>(`/api/optimizer-tasks${qs ? `?${qs}` : ''}`);
}

export async function getOptimizerTask(id: string): Promise<OptimizerTask> {
  return get<OptimizerTask>(`/api/optimizer-tasks/${id}`);
}

export async function createOptimizerTask(data: OptimizerTaskCreate): Promise<OptimizerTask> {
  return post<OptimizerTask>('/api/optimizer-tasks', data);
}

export async function updateOptimizerTask(
  id: string,
  data: Partial<OptimizerTaskCreate>,
): Promise<OptimizerTask> {
  return patch<OptimizerTask>(`/api/optimizer-tasks/${id}`, data);
}

export async function deleteOptimizerTask(id: string): Promise<void> {
  return del(`/api/optimizer-tasks/${id}`);
}
