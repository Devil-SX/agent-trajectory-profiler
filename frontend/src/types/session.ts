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

export enum MessageRole {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
}

export enum MessageSource {
  MAIN = 'main',
  SUBAGENT = 'subagent',
}

export enum MessageType {
  USER = 'user',
  ASSISTANT = 'assistant',
  FILE_HISTORY_SNAPSHOT = 'file-history-snapshot',
  SUMMARY = 'summary',
}

export interface ContentBlock {
  type: string;
}

export interface TextContent extends ContentBlock {
  type: 'text';
  text: string;
}

export interface ThinkingContent extends ContentBlock {
  type: 'thinking';
  thinking: string;
  signature?: string | null;
}

export interface ToolUseContent extends ContentBlock {
  type: 'tool_use';
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface ToolResultContent extends ContentBlock {
  type: 'tool_result';
  tool_use_id: string;
  content: string | Array<Record<string, unknown>>;
  is_error?: boolean | null;
}

export type MessageContent = TextContent | ThinkingContent | ToolUseContent | ToolResultContent;

export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens?: number | null;
  cache_read_input_tokens?: number | null;
  service_tier?: string | null;
}

export interface ClaudeMessage {
  role: MessageRole;
  content: string | Array<Record<string, unknown>>;
  model?: string | null;
  id?: string | null;
  type?: string | null;
  stop_reason?: string | null;
  stop_sequence?: string | null;
  usage?: TokenUsage | null;
}

export interface MessageRecord {
  sessionId: string;
  uuid: string;
  timestamp: string;
  type: MessageType;
  parentUuid?: string | null;
  userType?: string | null;
  cwd?: string | null;
  version?: string | null;
  gitBranch?: string | null;
  isSidechain?: boolean | null;
  agentId?: string | null;
  message?: ClaudeMessage | null;
  isMeta?: boolean | null;
  isSnapshotUpdate?: boolean | null;
}

export interface SessionMetadata {
  session_id: string;
  project_path: string;
  git_branch?: string | null;
  version: string;
  created_at: string;
  updated_at?: string | null;
  total_messages: number;
  total_tokens: number;
  user_type?: string | null;
}

export interface Session {
  metadata: SessionMetadata;
  messages: MessageRecord[];
}

export interface SessionDetailResponse {
  session: Session;
}
