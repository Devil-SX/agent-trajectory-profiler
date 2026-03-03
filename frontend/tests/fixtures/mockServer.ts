/**
 * Mock server setup for Playwright tests
 */

import { Page } from '@playwright/test';
import { mockSessionList, mockSessionDetail, mockSessionStatistics } from './mockData';

/**
 * Setup mock API responses for tests
 */
export async function setupMockApi(page: Page) {
  const mockAnalyticsOverview = {
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total_sessions: 2,
    total_messages: 65,
    total_tokens: 40000,
    total_tool_calls: 18,
    total_input_tokens: 15000,
    total_output_tokens: 22000,
    total_tool_output_tokens: 4800,
    total_cache_read_tokens: 2000,
    total_cache_creation_tokens: 1000,
    total_trajectory_file_size_bytes: 81920,
    total_chars: 120000,
    total_user_chars: 28000,
    total_model_chars: 76000,
    total_tool_chars: 16000,
    total_cjk_chars: 4200,
    total_latin_chars: 102000,
    total_other_chars: 13800,
    yield_ratio_tokens_mean: 2.5,
    yield_ratio_tokens_median: 2.4,
    yield_ratio_tokens_p90: 3.1,
    yield_ratio_chars_mean: 2.7,
    yield_ratio_chars_median: 2.6,
    yield_ratio_chars_p90: 3.3,
    leverage_tokens_mean: 2.5,
    leverage_tokens_median: 2.4,
    leverage_tokens_p90: 3.1,
    leverage_chars_mean: 2.7,
    leverage_chars_median: 2.6,
    leverage_chars_p90: 3.3,
    avg_tokens_per_second_mean: 15.2,
    avg_tokens_per_second_median: 14.9,
    avg_tokens_per_second_p90: 22.8,
    read_tokens_per_second_mean: 4.2,
    read_tokens_per_second_median: 4.0,
    read_tokens_per_second_p90: 6.1,
    output_tokens_per_second_mean: 9.5,
    output_tokens_per_second_median: 9.2,
    output_tokens_per_second_p90: 14.0,
    cache_tokens_per_second_mean: 1.5,
    cache_tokens_per_second_median: 1.4,
    cache_tokens_per_second_p90: 2.2,
    cache_read_tokens_per_second_mean: 1.0,
    cache_read_tokens_per_second_median: 0.9,
    cache_read_tokens_per_second_p90: 1.5,
    cache_creation_tokens_per_second_mean: 0.5,
    cache_creation_tokens_per_second_median: 0.5,
    cache_creation_tokens_per_second_p90: 0.8,
    avg_automation_ratio: 2.1,
    avg_session_duration_seconds: 4600,
    model_time_seconds: 5300,
    tool_time_seconds: 2800,
    user_time_seconds: 1900,
    inactive_time_seconds: 600,
    day_model_time_seconds: 4100,
    day_tool_time_seconds: 1900,
    day_user_time_seconds: 1300,
    day_inactive_time_seconds: 300,
    night_model_time_seconds: 1200,
    night_tool_time_seconds: 900,
    night_user_time_seconds: 600,
    night_inactive_time_seconds: 300,
    active_time_ratio: 0.93,
    model_timeout_count: 1,
    source_breakdown: [
      {
        ecosystem: 'claude_code',
        label: 'Claude Code',
        sessions: 1,
        total_tokens: 23000,
        total_tool_calls: 11,
        active_time_seconds: 6200,
        percent_sessions: 50,
        percent_tokens: 57.5,
      },
      {
        ecosystem: 'codex',
        label: 'Codex',
        sessions: 1,
        total_tokens: 17000,
        total_tool_calls: 7,
        active_time_seconds: 3800,
        percent_sessions: 50,
        percent_tokens: 42.5,
      },
    ],
    role_source_breakdown: [
      {
        ecosystem: 'claude_code',
        ecosystem_label: 'Claude Code',
        role: 'model',
        role_label: 'Model',
        key: 'claude_code:model',
        label: 'Claude Code:Model',
        time_seconds: 3200,
        time_percent: 32,
        token_count: 13000,
        token_percent: 32.5,
        tool_calls: 0,
        tool_call_percent: 0,
        error_count: 1,
        error_percent: 33.3,
      },
      {
        ecosystem: 'claude_code',
        ecosystem_label: 'Claude Code',
        role: 'tool',
        role_label: 'Tool',
        key: 'claude_code:tool',
        label: 'Claude Code:Tool',
        time_seconds: 1800,
        time_percent: 18,
        token_count: 7000,
        token_percent: 17.5,
        tool_calls: 11,
        tool_call_percent: 61.1,
        error_count: 1,
        error_percent: 33.3,
      },
      {
        ecosystem: 'claude_code',
        ecosystem_label: 'Claude Code',
        role: 'user',
        role_label: 'User',
        key: 'claude_code:user',
        label: 'Claude Code:User',
        time_seconds: 1200,
        time_percent: 12,
        token_count: 3000,
        token_percent: 7.5,
        tool_calls: 0,
        tool_call_percent: 0,
        error_count: 0,
        error_percent: 0,
      },
      {
        ecosystem: 'codex',
        ecosystem_label: 'Codex',
        role: 'model',
        role_label: 'Model',
        key: 'codex:model',
        label: 'Codex:Model',
        time_seconds: 2100,
        time_percent: 21,
        token_count: 9000,
        token_percent: 22.5,
        tool_calls: 0,
        tool_call_percent: 0,
        error_count: 1,
        error_percent: 33.3,
      },
      {
        ecosystem: 'codex',
        ecosystem_label: 'Codex',
        role: 'tool',
        role_label: 'Tool',
        key: 'codex:tool',
        label: 'Codex:Tool',
        time_seconds: 1000,
        time_percent: 10,
        token_count: 3500,
        token_percent: 8.75,
        tool_calls: 7,
        tool_call_percent: 38.9,
        error_count: 1,
        error_percent: 33.3,
      },
      {
        ecosystem: 'codex',
        ecosystem_label: 'Codex',
        role: 'user',
        role_label: 'User',
        key: 'codex:user',
        label: 'Codex:User',
        time_seconds: 700,
        time_percent: 7,
        token_count: 12000,
        token_percent: 30,
        tool_calls: 0,
        tool_call_percent: 0,
        error_count: 0,
        error_percent: 0,
      },
    ],
    primary_bottleneck_key: 'claude_code:model',
    primary_bottleneck_label: 'Claude Code:Model',
    primary_bottleneck_source: 'claude_code',
    primary_bottleneck_role: 'model',
    bottleneck_distribution: [
      { key: 'model', label: 'Model', count: 1, value: 1, percent: 50 },
      { key: 'tool', label: 'Tool', count: 1, value: 1, percent: 50 },
    ],
    top_projects: [
      {
        project_path: '/home/user/project',
        project_name: 'project',
        sessions: 2,
        total_tokens: 40000,
        total_messages: 65,
        percent_sessions: 100,
        percent_tokens: 100,
        leverage_tokens_mean: 2.5,
        leverage_chars_mean: 2.7,
      },
    ],
    top_tools: [
      {
        tool_name: 'Edit',
        total_calls: 9,
        sessions_using_tool: 2,
        error_count: 1,
        avg_latency_seconds: 0.28,
        percent_of_tool_calls: 50,
      },
    ],
  };

  const mockRuntimePlane = {
    total_messages: mockAnalyticsOverview.total_messages,
    total_tokens: mockAnalyticsOverview.total_tokens,
    total_tool_calls: mockAnalyticsOverview.total_tool_calls,
    total_input_tokens: mockAnalyticsOverview.total_input_tokens,
    total_output_tokens: mockAnalyticsOverview.total_output_tokens,
    total_tool_output_tokens: mockAnalyticsOverview.total_tool_output_tokens,
    total_cache_read_tokens: mockAnalyticsOverview.total_cache_read_tokens,
    total_cache_creation_tokens: mockAnalyticsOverview.total_cache_creation_tokens,
    total_chars: mockAnalyticsOverview.total_chars,
    total_user_chars: mockAnalyticsOverview.total_user_chars,
    total_model_chars: mockAnalyticsOverview.total_model_chars,
    total_tool_chars: mockAnalyticsOverview.total_tool_chars,
    total_cjk_chars: mockAnalyticsOverview.total_cjk_chars,
    total_latin_chars: mockAnalyticsOverview.total_latin_chars,
    total_other_chars: mockAnalyticsOverview.total_other_chars,
    yield_ratio_tokens_mean: mockAnalyticsOverview.yield_ratio_tokens_mean,
    yield_ratio_tokens_median: mockAnalyticsOverview.yield_ratio_tokens_median,
    yield_ratio_tokens_p90: mockAnalyticsOverview.yield_ratio_tokens_p90,
    yield_ratio_chars_mean: mockAnalyticsOverview.yield_ratio_chars_mean,
    yield_ratio_chars_median: mockAnalyticsOverview.yield_ratio_chars_median,
    yield_ratio_chars_p90: mockAnalyticsOverview.yield_ratio_chars_p90,
    leverage_tokens_mean: mockAnalyticsOverview.leverage_tokens_mean,
    leverage_tokens_median: mockAnalyticsOverview.leverage_tokens_median,
    leverage_tokens_p90: mockAnalyticsOverview.leverage_tokens_p90,
    leverage_chars_mean: mockAnalyticsOverview.leverage_chars_mean,
    leverage_chars_median: mockAnalyticsOverview.leverage_chars_median,
    leverage_chars_p90: mockAnalyticsOverview.leverage_chars_p90,
    avg_tokens_per_second_mean: mockAnalyticsOverview.avg_tokens_per_second_mean,
    avg_tokens_per_second_median: mockAnalyticsOverview.avg_tokens_per_second_median,
    avg_tokens_per_second_p90: mockAnalyticsOverview.avg_tokens_per_second_p90,
    read_tokens_per_second_mean: mockAnalyticsOverview.read_tokens_per_second_mean,
    read_tokens_per_second_median: mockAnalyticsOverview.read_tokens_per_second_median,
    read_tokens_per_second_p90: mockAnalyticsOverview.read_tokens_per_second_p90,
    output_tokens_per_second_mean: mockAnalyticsOverview.output_tokens_per_second_mean,
    output_tokens_per_second_median: mockAnalyticsOverview.output_tokens_per_second_median,
    output_tokens_per_second_p90: mockAnalyticsOverview.output_tokens_per_second_p90,
    cache_tokens_per_second_mean: mockAnalyticsOverview.cache_tokens_per_second_mean,
    cache_tokens_per_second_median: mockAnalyticsOverview.cache_tokens_per_second_median,
    cache_tokens_per_second_p90: mockAnalyticsOverview.cache_tokens_per_second_p90,
    cache_read_tokens_per_second_mean: mockAnalyticsOverview.cache_read_tokens_per_second_mean,
    cache_read_tokens_per_second_median: mockAnalyticsOverview.cache_read_tokens_per_second_median,
    cache_read_tokens_per_second_p90: mockAnalyticsOverview.cache_read_tokens_per_second_p90,
    cache_creation_tokens_per_second_mean: mockAnalyticsOverview.cache_creation_tokens_per_second_mean,
    cache_creation_tokens_per_second_median: mockAnalyticsOverview.cache_creation_tokens_per_second_median,
    cache_creation_tokens_per_second_p90: mockAnalyticsOverview.cache_creation_tokens_per_second_p90,
    avg_automation_ratio: mockAnalyticsOverview.avg_automation_ratio,
    avg_session_duration_seconds: mockAnalyticsOverview.avg_session_duration_seconds,
    model_time_seconds: mockAnalyticsOverview.model_time_seconds,
    tool_time_seconds: mockAnalyticsOverview.tool_time_seconds,
    user_time_seconds: mockAnalyticsOverview.user_time_seconds,
    inactive_time_seconds: mockAnalyticsOverview.inactive_time_seconds,
    day_model_time_seconds: mockAnalyticsOverview.day_model_time_seconds,
    day_tool_time_seconds: mockAnalyticsOverview.day_tool_time_seconds,
    day_user_time_seconds: mockAnalyticsOverview.day_user_time_seconds,
    day_inactive_time_seconds: mockAnalyticsOverview.day_inactive_time_seconds,
    night_model_time_seconds: mockAnalyticsOverview.night_model_time_seconds,
    night_tool_time_seconds: mockAnalyticsOverview.night_tool_time_seconds,
    night_user_time_seconds: mockAnalyticsOverview.night_user_time_seconds,
    night_inactive_time_seconds: mockAnalyticsOverview.night_inactive_time_seconds,
    active_time_ratio: mockAnalyticsOverview.active_time_ratio,
    model_timeout_count: mockAnalyticsOverview.model_timeout_count,
    source_breakdown: mockAnalyticsOverview.source_breakdown,
    role_source_breakdown: mockAnalyticsOverview.role_source_breakdown,
    primary_bottleneck_key: mockAnalyticsOverview.primary_bottleneck_key,
    primary_bottleneck_label: mockAnalyticsOverview.primary_bottleneck_label,
    primary_bottleneck_source: mockAnalyticsOverview.primary_bottleneck_source,
    primary_bottleneck_role: mockAnalyticsOverview.primary_bottleneck_role,
    bottleneck_distribution: mockAnalyticsOverview.bottleneck_distribution,
    top_projects: mockAnalyticsOverview.top_projects,
    top_tools: mockAnalyticsOverview.top_tools,
  };

  const mockControlPlane = {
    logical_sessions: mockAnalyticsOverview.total_sessions,
    physical_sessions: mockAnalyticsOverview.total_sessions,
    files: {
      total_files: 22,
      parsed_files: 20,
      error_files: 1,
      pending_files: 1,
      total_tracked_file_size_bytes: 10240,
      total_trajectory_file_size_bytes: mockAnalyticsOverview.total_trajectory_file_size_bytes,
      last_parsed_at: '2026-02-27T01:02:03.000Z',
    },
    sync_running: false,
    last_sync: {
      status: 'completed',
      trigger: 'manual',
      started_at: '2026-02-27T01:01:00.000Z',
      finished_at: '2026-02-27T01:02:00.000Z',
      parsed: 5,
      skipped: 10,
      errors: 0,
      total_files_scanned: 15,
      total_file_size_bytes: 10240,
      ecosystems: [
        {
          ecosystem: 'claude_code',
          files_scanned: 10,
          file_size_bytes: 8192,
          parsed: 4,
          skipped: 6,
          errors: 0,
        },
        {
          ecosystem: 'codex',
          files_scanned: 5,
          file_size_bytes: 2048,
          parsed: 1,
          skipped: 4,
          errors: 0,
        },
      ],
      error_samples: [],
    },
  };

  Object.assign(mockAnalyticsOverview, {
    control_plane: mockControlPlane,
    runtime_plane: mockRuntimePlane,
  });

  const mockAutomationDistribution = {
    dimension: 'automation_band',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total: 2,
    buckets: [
      { key: 'medium', label: 'Medium', count: 1, value: 1, percent: 50 },
      { key: 'high', label: 'High', count: 1, value: 1, percent: 50 },
    ],
  };

  const mockSessionShareDistribution = {
    dimension: 'session_token_share',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total: 2,
    buckets: [
      { key: 'test-session-001', label: 'test-session-001', count: 1, value: 23000, percent: 57.5 },
      { key: 'test-session-002', label: 'test-session-002', count: 1, value: 17000, percent: 42.5 },
    ],
  };

  const mockAnalyticsTimeseries = {
    interval: 'day',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    points: [
      { period: '2026-02-26', sessions: 1, tokens: 17000, tool_calls: 7, avg_automation_ratio: 1.8, avg_duration_seconds: 3900 },
      { period: '2026-02-27', sessions: 1, tokens: 23000, tool_calls: 11, avg_automation_ratio: 2.4, avg_duration_seconds: 5300 },
    ],
  };

  const mockProjectComparison = {
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total_projects: 3,
    projects: [
      {
        project_path: '/home/user/project',
        project_name: 'project',
        sessions: 2,
        total_tokens: 40000,
        total_messages: 65,
        percent_sessions: 100,
        percent_tokens: 100,
        leverage_tokens_mean: 2.5,
        leverage_chars_mean: 2.7,
        active_ratio: 0.93,
      },
      {
        project_path: '/home/user/design-system',
        project_name: 'design-system',
        sessions: 1,
        total_tokens: 12000,
        total_messages: 22,
        percent_sessions: 50,
        percent_tokens: 30,
        leverage_tokens_mean: 1.6,
        leverage_chars_mean: 1.9,
        active_ratio: 0.82,
      },
      {
        project_path: '/home/user/infra',
        project_name: 'infra',
        sessions: 1,
        total_tokens: 8000,
        total_messages: 18,
        percent_sessions: 50,
        percent_tokens: 20,
        leverage_tokens_mean: 1.2,
        leverage_chars_mean: 1.4,
        active_ratio: 0.74,
      },
    ],
  };

  const mockProjectSwimlane = {
    interval: 'day',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    project_limit: 12,
    truncated_project_count: 0,
    periods: ['2026-02-26', '2026-02-27'],
    projects: mockProjectComparison.projects,
    points: [
      {
        period: '2026-02-26',
        project_path: '/home/user/project',
        project_name: 'project',
        sessions: 1,
        tokens: 17000,
        active_ratio: 0.91,
        leverage_tokens_mean: 2.2,
      },
      {
        period: '2026-02-27',
        project_path: '/home/user/project',
        project_name: 'project',
        sessions: 1,
        tokens: 23000,
        active_ratio: 0.94,
        leverage_tokens_mean: 2.8,
      },
      {
        period: '2026-02-27',
        project_path: '/home/user/design-system',
        project_name: 'design-system',
        sessions: 1,
        tokens: 12000,
        active_ratio: 0.82,
        leverage_tokens_mean: 1.6,
      },
      {
        period: '2026-02-26',
        project_path: '/home/user/infra',
        project_name: 'infra',
        sessions: 1,
        tokens: 8000,
        active_ratio: 0.74,
        leverage_tokens_mean: 1.2,
      },
    ],
  };

  const mockSyncStatus = {
    total_files: 22,
    total_sessions: 2,
    last_parsed_at: '2026-02-27T01:02:03.000Z',
    sync_running: false,
    last_sync: {
      status: 'completed',
      trigger: 'manual',
      started_at: '2026-02-27T01:01:00.000Z',
      finished_at: '2026-02-27T01:02:00.000Z',
      parsed: 5,
      skipped: 10,
      errors: 0,
      total_files_scanned: 15,
      total_file_size_bytes: 10240,
      ecosystems: [
        {
          ecosystem: 'claude_code',
          files_scanned: 10,
          file_size_bytes: 8192,
          parsed: 4,
          skipped: 6,
          errors: 0,
        },
        {
          ecosystem: 'codex',
          files_scanned: 5,
          file_size_bytes: 2048,
          parsed: 1,
          skipped: 4,
          errors: 0,
        },
      ],
      error_samples: [],
    },
  };

  const frontendPreferences = {
    locale: 'en',
    theme_mode: 'system',
    density_mode: 'comfortable',
    session_view_mode: 'table',
    session_aggregation_mode: 'logical',
    updated_at: null as string | null,
  };

  const mockCapabilities = {
    capabilities: [
      {
        schema_version: '1.0',
        ecosystem: 'claude_code',
        manifest_version: '1.0.0',
        display_name: 'Claude Code',
        parser: {
          adapter: 'claude_code.jsonl',
          session_id_strategy: 'filename',
          supports_logical_session: true,
          supports_physical_session: false,
          minimum_agent_version: null,
          default_roots: ['~/.claude/projects'],
        },
        event_shape_support: {
          message_events: true,
          tool_call_events: true,
          tool_result_events: true,
          session_boundary_events: true,
          timeline_timestamps: true,
          subagent_events: false,
          parent_child_session_links: false,
          streaming_partial_events: true,
        },
        token_field_support: {
          input_tokens: true,
          output_tokens: true,
          cache_read_tokens: true,
          cache_creation_tokens: true,
          reasoning_tokens: false,
          tool_output_tokens: true,
          token_units: 'token',
        },
        tool_error_taxonomy_support: {
          categorization_available: true,
          rule_version: '1.0.0',
          error_preview_available: true,
          error_detail_available: true,
          supports_timestamped_error_timeline: true,
          supports_tool_name_mapping: true,
        },
        fallback_behavior: {
          missing_token_fields: 'zero_fill',
          missing_timestamps: 'skip_timing_metrics',
          unknown_tool_errors: 'uncategorized',
        },
        known_limitations: [],
      },
      {
        schema_version: '1.0',
        ecosystem: 'codex',
        manifest_version: '1.0.0',
        display_name: 'Codex',
        parser: {
          adapter: 'codex.rollout',
          session_id_strategy: 'event_field',
          supports_logical_session: true,
          supports_physical_session: true,
          minimum_agent_version: null,
          default_roots: ['~/.codex/sessions'],
        },
        event_shape_support: {
          message_events: true,
          tool_call_events: true,
          tool_result_events: true,
          session_boundary_events: true,
          timeline_timestamps: true,
          subagent_events: true,
          parent_child_session_links: true,
          streaming_partial_events: true,
        },
        token_field_support: {
          input_tokens: true,
          output_tokens: true,
          cache_read_tokens: true,
          cache_creation_tokens: true,
          reasoning_tokens: false,
          tool_output_tokens: true,
          token_units: 'token',
        },
        tool_error_taxonomy_support: {
          categorization_available: true,
          rule_version: '1.0.0',
          error_preview_available: true,
          error_detail_available: true,
          supports_timestamped_error_timeline: true,
          supports_tool_name_mapping: true,
        },
        fallback_behavior: {
          missing_token_fields: 'zero_fill',
          missing_timestamps: 'infer_best_effort',
          unknown_tool_errors: 'uncategorized',
        },
        known_limitations: [],
      },
    ],
  };

  const cloneJson = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

  const filteredOverview = (ecosystem: string | null) => {
    const overview = cloneJson(mockAnalyticsOverview);
    if (!ecosystem) {
      return overview;
    }

    const sourceRows = overview.source_breakdown.filter(
      (row: { ecosystem: string }) => row.ecosystem === ecosystem
    );
    const roleRows = overview.role_source_breakdown.filter(
      (row: { ecosystem: string }) => row.ecosystem === ecosystem
    );
    if (sourceRows.length === 0) {
      overview.total_sessions = 0;
      overview.total_tokens = 0;
      overview.total_tool_calls = 0;
      overview.source_breakdown = [];
      overview.role_source_breakdown = [];
      overview.primary_bottleneck_key = null;
      overview.primary_bottleneck_label = null;
      overview.primary_bottleneck_source = null;
      overview.primary_bottleneck_role = null;
      overview.runtime_plane.total_tokens = 0;
      overview.runtime_plane.total_tool_calls = 0;
      overview.runtime_plane.source_breakdown = [];
      overview.runtime_plane.role_source_breakdown = [];
      overview.runtime_plane.primary_bottleneck_key = null;
      overview.runtime_plane.primary_bottleneck_label = null;
      overview.runtime_plane.primary_bottleneck_source = null;
      overview.runtime_plane.primary_bottleneck_role = null;
      return overview;
    }

    const selected = sourceRows[0];
    const primary = [...roleRows].sort((a, b) => b.time_seconds - a.time_seconds)[0] ?? null;
    const modelSeconds = roleRows
      .filter((row: { role: string }) => row.role === 'model')
      .reduce((sum: number, row: { time_seconds: number }) => sum + row.time_seconds, 0);
    const toolSeconds = roleRows
      .filter((row: { role: string }) => row.role === 'tool')
      .reduce((sum: number, row: { time_seconds: number }) => sum + row.time_seconds, 0);
    const userSeconds = roleRows
      .filter((row: { role: string }) => row.role === 'user')
      .reduce((sum: number, row: { time_seconds: number }) => sum + row.time_seconds, 0);

    overview.total_sessions = selected.sessions;
    overview.total_tokens = selected.total_tokens;
    overview.total_tool_calls = selected.total_tool_calls;
    overview.source_breakdown = sourceRows;
    overview.role_source_breakdown = roleRows;
    overview.primary_bottleneck_key = primary?.key ?? null;
    overview.primary_bottleneck_label = primary?.label ?? null;
    overview.primary_bottleneck_source = primary?.ecosystem ?? null;
    overview.primary_bottleneck_role = primary?.role ?? null;
    overview.runtime_plane.total_tokens = selected.total_tokens;
    overview.runtime_plane.total_tool_calls = selected.total_tool_calls;
    overview.runtime_plane.model_time_seconds = modelSeconds;
    overview.runtime_plane.tool_time_seconds = toolSeconds;
    overview.runtime_plane.user_time_seconds = userSeconds;
    overview.runtime_plane.source_breakdown = sourceRows;
    overview.runtime_plane.role_source_breakdown = roleRows;
    overview.runtime_plane.primary_bottleneck_key = primary?.key ?? null;
    overview.runtime_plane.primary_bottleneck_label = primary?.label ?? null;
    overview.runtime_plane.primary_bottleneck_source = primary?.ecosystem ?? null;
    overview.runtime_plane.primary_bottleneck_role = primary?.role ?? null;
    return overview;
  };

  const filteredTimeseries = (ecosystem: string | null) => {
    if (!ecosystem) {
      return mockAnalyticsTimeseries;
    }
    const point =
      ecosystem === 'claude_code' ? mockAnalyticsTimeseries.points[1] : mockAnalyticsTimeseries.points[0];
    return {
      ...mockAnalyticsTimeseries,
      points: point ? [point] : [],
    };
  };

  const filteredProjectComparison = (ecosystem: string | null) => {
    if (!ecosystem) {
      return mockProjectComparison;
    }
    const baseProject = mockProjectComparison.projects[0];
    if (!baseProject) {
      return { ...mockProjectComparison, total_projects: 0, projects: [] };
    }
    const sessions = 1;
    const totalTokens = ecosystem === 'claude_code' ? 23000 : 17000;
    return {
      ...mockProjectComparison,
      total_projects: 1,
      projects: [
        {
          ...baseProject,
          sessions,
          total_tokens: totalTokens,
          percent_sessions: 100,
          percent_tokens: 100,
        },
      ],
    };
  };

  const filteredProjectSwimlane = (ecosystem: string | null) => {
    if (!ecosystem) {
      return mockProjectSwimlane;
    }
    const points = mockProjectSwimlane.points.filter((point) =>
      ecosystem === 'claude_code' ? point.period === '2026-02-27' : point.period === '2026-02-26'
    );
    const projects = filteredProjectComparison(ecosystem).projects;
    return {
      ...mockProjectSwimlane,
      projects,
      points,
      periods: points.map((point) => point.period),
      truncated_project_count: 0,
    };
  };

  await page.route(/\/api\/state\/frontend-preferences(?:\?.*)?$/, async (route) => {
    const method = route.request().method();
    if (method === 'PUT') {
      const patch = (await route.request().postDataJSON()) as Record<string, unknown> | null;
      if (patch && typeof patch === 'object') {
        if (patch.locale === 'en' || patch.locale === 'zh-CN') {
          frontendPreferences.locale = patch.locale;
        }
        if (
          patch.theme_mode === 'system' ||
          patch.theme_mode === 'light' ||
          patch.theme_mode === 'dark'
        ) {
          frontendPreferences.theme_mode = patch.theme_mode;
        }
        if (patch.density_mode === 'comfortable' || patch.density_mode === 'compact') {
          frontendPreferences.density_mode = patch.density_mode;
        }
        if (patch.session_view_mode === 'cards' || patch.session_view_mode === 'table') {
          frontendPreferences.session_view_mode = patch.session_view_mode;
        }
        if (
          patch.session_aggregation_mode === 'logical' ||
          patch.session_aggregation_mode === 'physical'
        ) {
          frontendPreferences.session_aggregation_mode = patch.session_aggregation_mode;
        }
      }
      frontendPreferences.updated_at = '2026-02-27T02:00:00.000Z';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(frontendPreferences),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(frontendPreferences),
    });
  });

  // Mock sessions list endpoint
  await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionList),
    });
  });

  // Mock session detail endpoint
  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionDetail),
    });
  });

  // Mock session statistics endpoint
  await page.route('**/api/sessions/test-session-001/statistics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionStatistics),
    });
  });

  // Mock second session detail endpoint
  await page.route('**/api/sessions/test-session-002', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionDetail,
        session: {
          ...mockSessionDetail.session,
          metadata: {
            ...mockSessionDetail.session.metadata,
            session_id: 'test-session-002',
          },
        },
      }),
    });
  });

  // Mock second session statistics endpoint
  await page.route('**/api/sessions/test-session-002/statistics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionStatistics,
        session_id: 'test-session-002',
      }),
    });
  });

  await page.route(/\/api\/sync\/status(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncStatus),
    });
  });

  await page.route(/\/api\/sync\/run(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncStatus.last_sync),
    });
  });

  await page.route(/\/api\/capabilities(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockCapabilities),
    });
  });

  await page.route(/\/api\/analytics\/overview(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const ecosystem = url.searchParams.get('ecosystem');
    const payload = filteredOverview(ecosystem);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  await page.route(/\/api\/analytics\/distribution(?:s)?(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const dimension = url.searchParams.get('dimension');
    const ecosystem = url.searchParams.get('ecosystem');
    const payload = dimension === 'session_token_share'
      ? cloneJson(mockSessionShareDistribution)
      : cloneJson(mockAutomationDistribution);

    if (ecosystem) {
      if (dimension === 'session_token_share') {
        payload.buckets = payload.buckets.filter((bucket: { key: string }) =>
          ecosystem === 'claude_code' ? bucket.key === 'test-session-001' : bucket.key === 'test-session-002'
        );
      } else {
        payload.buckets = ecosystem === 'claude_code'
          ? [{ key: 'high', label: 'High', count: 1, value: 1, percent: 100 }]
          : [{ key: 'medium', label: 'Medium', count: 1, value: 1, percent: 100 }];
      }
      payload.total = payload.buckets.reduce(
        (sum: number, bucket: { value?: number; count?: number }) =>
          sum + Number(bucket.value ?? bucket.count ?? 0),
        0
      );
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  await page.route(/\/api\/analytics\/timeseries(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const ecosystem = url.searchParams.get('ecosystem');
    const payload = filteredTimeseries(ecosystem);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  await page.route(/\/api\/analytics\/project-comparison(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const ecosystem = url.searchParams.get('ecosystem');
    const payload = filteredProjectComparison(ecosystem);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  await page.route(/\/api\/analytics\/project-swimlane(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const ecosystem = url.searchParams.get('ecosystem');
    const payload = filteredProjectSwimlane(ecosystem);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });
}
