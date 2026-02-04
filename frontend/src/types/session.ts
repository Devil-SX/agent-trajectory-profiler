/**
 * TypeScript types for Claude Code Session data.
 * Mirrors the API response models from the backend.
 */

export interface SessionSummary {
  session_id: string;
  project_path: string;
  created_at: string;
  updated_at: string | null;
  total_messages: number;
  total_tokens: number;
  git_branch: string | null;
  version: string;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  count: number;
}

export interface ErrorResponse {
  error: string;
  detail?: string;
  status_code?: number;
}
