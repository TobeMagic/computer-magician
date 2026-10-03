/**
 * AImagician MCP Console API
 * Types match backend McpToolCallRead/McpCapabilitiesRead schemas.
 */

import { get } from './client';

export interface McpToolCall {
  id: string;
  trace_id?: string;
  tool_name: string;
  status: string;
  actor_label?: string;
  article_id?: string;
  run_id?: string;
  job_id?: string;
  request_json?: Record<string, any>;
  response_json?: Record<string, any>;
  failure_code?: string;
  failure_message?: string;
  duration_ms?: number;
  created_at: string;
  finished_at?: string;
  metadata_json?: Record<string, any>;
}

export interface McpCapabilities {
  protocol: string;
  endpoint: string;
  transport: string;
  auth: string;
  tools: string[];
  resources: string[];
  prompts: string[];
  publisher_capabilities: Record<string, any>;
  notes: string[];
}

export async function getMcpToolCalls(params?: {
  tool_name?: string;
  status?: string;
  article_id?: string;
  limit?: number;
  offset?: number;
}): Promise<McpToolCall[]> {
  return get<McpToolCall[]>('/api/mcp/tool-calls', params as Record<string, string | number | boolean | undefined>);
}

export async function getMcpCapabilities(): Promise<McpCapabilities> {
  return get<McpCapabilities>('/api/mcp/capabilities');
}
