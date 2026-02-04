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

export type MessageRole = 'user' | 'assistant' | 'system';

export type MessageSource = 'main' | 'subagent';

export type MessageType = 'user' | 'assistant' | 'file-history-snapshot' | 'summary';

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

// Tool categories for visualization
export type ToolCategory =
  | 'file-read'
  | 'file-write'
  | 'file-search'
  | 'execution'
  | 'agent'
  | 'web'
  | 'analysis'
  | 'other';

// Enhanced tool call data for visualization
export interface ToolCallDisplay {
  id: string;
  name: string;
  category: ToolCategory;
  input: Record<string, unknown>;
  result?: ToolResultContent;
  tokens?: {
    input: number;
    output: number;
    total: number;
  };
  hasError: boolean;
  timestamp?: string;
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

export type SubagentType =
  | 'Explore'
  | 'Bash'
  | 'general-purpose'
  | 'Plan'
  | 'test-runner'
  | 'build-validator'
  | 'statusline-setup'
  | 'prompt_suggestion'
  | 'other';

export interface SubagentSession {
  agent_id: string;
  agent_type: SubagentType;
  messages: MessageRecord[];
  start_time: string;
  end_time?: string | null;
  parent_message_uuid: string;
}

export interface SessionMetadataDisplay {
  sessionId: string;
  createdAt: string;
  duration: string;
  totalMessages: number;
  modelsUsed: string[];
  status: 'active' | 'completed' | 'error';
  gitBranch?: string | null;
  projectPath: string;
  version: string;
  totalTokens: number;
}

export interface ToolCallStatistics {
  tool_name: string;
  count: number;
  total_tokens: number;
  success_count: number;
  error_count: number;
}

export interface SessionStatistics {
  message_count: number;
  user_message_count: number;
  assistant_message_count: number;
  system_message_count: number;
  total_tokens: number;
  total_input_tokens: number;
  total_output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  tool_calls: ToolCallStatistics[];
  total_tool_calls: number;
  subagent_count: number;
  subagent_sessions: Record<string, number>;
  session_duration_seconds: number | null;
  first_message_time: string | null;
  last_message_time: string | null;
}

export interface SessionStatisticsResponse {
  session_id: string;
  statistics: SessionStatistics;
}
