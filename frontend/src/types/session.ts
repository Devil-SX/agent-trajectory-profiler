/**
 * TypeScript types for Claude Code Session data.
 * Mirrors the API response models from the backend.
 */

export interface SessionSummary {
  session_id: string;
  ecosystem: string;
  project_path: string;
  created_at: string;
  updated_at: string | null;
  total_messages: number;
  total_tokens: number;
  git_branch: string | null;
  version: string;
  parsed_at: string | null;
  duration_seconds: number | null;
  bottleneck: string | null;
  automation_ratio: number | null;
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface SyncEcosystemDetail {
  ecosystem: string;
  files_scanned: number;
  file_size_bytes: number;
  parsed: number;
  skipped: number;
  errors: number;
}

export type SyncRunState = 'idle' | 'running' | 'completed' | 'failed' | 'already_running';
export type SyncTrigger = 'startup' | 'manual' | 'refresh';

export interface SyncRunDetail {
  status: SyncRunState;
  trigger: SyncTrigger;
  started_at: string | null;
  finished_at: string | null;
  parsed: number;
  skipped: number;
  errors: number;
  total_files_scanned: number;
  total_file_size_bytes: number;
  ecosystems: SyncEcosystemDetail[];
  error_samples: string[];
}

export interface SyncStatusResponse {
  total_files: number;
  total_sessions: number;
  last_parsed_at: string | null;
  sync_running: boolean;
  last_sync: SyncRunDetail | null;
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

export interface TimeBreakdown {
  total_model_time_seconds: number;
  total_tool_time_seconds: number;
  total_user_time_seconds: number;
  total_inactive_time_seconds: number;
  total_active_time_seconds: number;
  model_time_percent: number;
  tool_time_percent: number;
  user_time_percent: number;
  inactive_time_percent: number;
  active_time_ratio: number;
  inactivity_threshold_seconds: number;
  user_interaction_count: number;
  interactions_per_hour: number;
  model_timeout_count: number;
  model_timeout_threshold_seconds: number;
}

export interface TokenBreakdown {
  input_percent: number;
  output_percent: number;
  cache_read_percent: number;
  cache_creation_percent: number;
}

export interface ToolCallStatistics {
  tool_name: string;
  count: number;
  total_tokens: number;
  success_count: number;
  error_count: number;
  total_latency_seconds: number;
  avg_latency_seconds: number;
  tool_group: string;
}

export interface ToolGroupStatistics {
  group_name: string;
  count: number;
  total_tokens: number;
  success_count: number;
  error_count: number;
  total_latency_seconds: number;
  avg_latency_seconds: number;
  tool_count: number;
  tools: string[];
}

export interface CharacterBreakdown {
  total_chars: number;
  user_chars: number;
  model_chars: number;
  tool_chars: number;
  cjk_chars: number;
  latin_chars: number;
  digit_chars: number;
  whitespace_chars: number;
  other_chars: number;
}

export interface ToolErrorRecord {
  timestamp: string;
  tool_name: string;
  category: string;
  matched_rule: string | null;
  preview: string;
  detail: string;
}

export interface CompactEvent {
  timestamp: string;
  trigger: string;
  pre_tokens: number;
}

export interface BashCommandStats {
  command_name: string;
  count: number;
  total_latency_seconds: number;
  avg_latency_seconds: number;
  total_output_chars: number;
  avg_output_chars: number;
}

export interface BashBreakdown {
  total_calls: number;
  total_sub_commands: number;
  avg_commands_per_call: number;
  commands_per_call_distribution: Record<number, number>;
  command_stats: BashCommandStats[];
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
  trajectory_file_size_bytes: number;
  character_breakdown: CharacterBreakdown;
  user_yield_ratio_tokens: number | null;
  user_yield_ratio_chars: number | null;
  leverage_ratio_tokens: number | null;
  leverage_ratio_chars: number | null;
  avg_tokens_per_second: number | null;
  read_tokens_per_second: number | null;
  output_tokens_per_second: number | null;
  cache_tokens_per_second: number | null;
  cache_read_tokens_per_second: number | null;
  cache_creation_tokens_per_second: number | null;
  tool_calls: ToolCallStatistics[];
  tool_groups: ToolGroupStatistics[];
  total_tool_calls: number;
  tool_error_records: ToolErrorRecord[];
  tool_error_category_counts: Record<string, number>;
  error_taxonomy_version: string;
  subagent_count: number;
  subagent_sessions: Record<string, number>;
  session_duration_seconds: number | null;
  first_message_time: string | null;
  last_message_time: string | null;
  time_breakdown: TimeBreakdown | null;
  token_breakdown: TokenBreakdown | null;
  bash_breakdown: BashBreakdown | null;
  compact_count: number;
  compact_events: CompactEvent[];
}

export interface SessionStatisticsResponse {
  session_id: string;
  statistics: SessionStatistics;
}

export interface AnalyticsBucket {
  key: string;
  label: string;
  count: number;
  value: number;
  percent: number;
}

export interface ProjectAggregate {
  project_path: string;
  project_name: string;
  sessions: number;
  total_tokens: number;
  total_messages: number;
  percent_sessions: number;
  percent_tokens: number;
  leverage_tokens_mean: number | null;
  leverage_chars_mean: number | null;
}

export interface ToolAggregate {
  tool_name: string;
  total_calls: number;
  sessions_using_tool: number;
  error_count: number;
  avg_latency_seconds: number;
  percent_of_tool_calls: number;
}

export interface AnalyticsOverviewResponse {
  start_date: string;
  end_date: string;
  total_sessions: number;
  total_messages: number;
  total_tokens: number;
  total_tool_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tool_output_tokens: number;
  total_cache_read_tokens: number;
  total_cache_creation_tokens: number;
  total_trajectory_file_size_bytes: number;
  total_chars: number;
  total_user_chars: number;
  total_model_chars: number;
  total_tool_chars: number;
  total_cjk_chars: number;
  total_latin_chars: number;
  total_other_chars: number;
  yield_ratio_tokens_mean: number;
  yield_ratio_tokens_median: number;
  yield_ratio_tokens_p90: number;
  yield_ratio_chars_mean: number;
  yield_ratio_chars_median: number;
  yield_ratio_chars_p90: number;
  leverage_tokens_mean: number;
  leverage_tokens_median: number;
  leverage_tokens_p90: number;
  leverage_chars_mean: number;
  leverage_chars_median: number;
  leverage_chars_p90: number;
  avg_tokens_per_second_mean: number;
  avg_tokens_per_second_median: number;
  avg_tokens_per_second_p90: number;
  read_tokens_per_second_mean: number;
  read_tokens_per_second_median: number;
  read_tokens_per_second_p90: number;
  output_tokens_per_second_mean: number;
  output_tokens_per_second_median: number;
  output_tokens_per_second_p90: number;
  cache_tokens_per_second_mean: number;
  cache_tokens_per_second_median: number;
  cache_tokens_per_second_p90: number;
  cache_read_tokens_per_second_mean: number;
  cache_read_tokens_per_second_median: number;
  cache_read_tokens_per_second_p90: number;
  cache_creation_tokens_per_second_mean: number;
  cache_creation_tokens_per_second_median: number;
  cache_creation_tokens_per_second_p90: number;
  avg_automation_ratio: number;
  avg_session_duration_seconds: number;
  model_time_seconds: number;
  tool_time_seconds: number;
  user_time_seconds: number;
  inactive_time_seconds: number;
  day_model_time_seconds: number;
  day_tool_time_seconds: number;
  day_user_time_seconds: number;
  day_inactive_time_seconds: number;
  night_model_time_seconds: number;
  night_tool_time_seconds: number;
  night_user_time_seconds: number;
  night_inactive_time_seconds: number;
  active_time_ratio: number;
  model_timeout_count: number;
  bottleneck_distribution: AnalyticsBucket[];
  top_projects: ProjectAggregate[];
  top_tools: ToolAggregate[];
}

export type AnalyticsDimension =
  | 'bottleneck'
  | 'project'
  | 'branch'
  | 'automation_band'
  | 'tool'
  | 'session_token_share';

export interface AnalyticsDistributionResponse {
  dimension: AnalyticsDimension;
  start_date: string;
  end_date: string;
  total: number;
  buckets: AnalyticsBucket[];
}

export type AnalyticsInterval = 'day' | 'week';

export interface AnalyticsTimeseriesPoint {
  period: string;
  sessions: number;
  tokens: number;
  tool_calls: number;
  avg_automation_ratio: number;
  avg_duration_seconds: number;
}

export interface AnalyticsTimeseriesResponse {
  interval: AnalyticsInterval;
  start_date: string;
  end_date: string;
  points: AnalyticsTimeseriesPoint[];
}
