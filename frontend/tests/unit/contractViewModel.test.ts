import { describe, expect, it } from 'vitest';
import type { CapabilityListResponse, SessionStatistics } from '../../src/types/session';
import {
  buildCapabilityIndex,
  buildSessionStatisticsViewModel,
  deriveCapabilityNotices,
  getEcosystemPresentation,
} from '../../src/utils/contractViewModel';

const capabilities: CapabilityListResponse = {
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

describe('contractViewModel', () => {
  it('builds capability index and resolves ecosystem presentation', () => {
    const index = buildCapabilityIndex(capabilities);
    const claude = getEcosystemPresentation('claude_code', index);
    const codex = getEcosystemPresentation('codex', index);
    const unknown = getEcosystemPresentation('custom_agent', index);

    expect(Object.keys(index)).toEqual(['claude_code', 'codex']);
    expect(claude.label).toBe('Claude Code');
    expect(codex.label).toBe('Codex');
    expect(unknown.label).toBe('custom_agent');
    expect(unknown.color).toMatch(/^#/);
  });

  it('derives capability notices from manifest fallback and support flags', () => {
    const index = buildCapabilityIndex(capabilities);
    const codexNotices = deriveCapabilityNotices(index.codex);
    const claudeNotices = deriveCapabilityNotices(index.claude_code);

    expect(codexNotices.some((item) => item.id === 'timestamp_inference')).toBe(true);
    expect(codexNotices.some((item) => item.id === 'reasoning_tokens')).toBe(true);
    expect(claudeNotices.some((item) => item.id === 'lineage_links')).toBe(true);
  });

  it('builds statistics view model with ratios and capability notices', () => {
    const index = buildCapabilityIndex(capabilities);
    const statistics = {
      total_tool_calls: 12,
      time_breakdown: {
        user_interaction_count: 4,
      },
      leverage_ratio_tokens: 3.0,
      leverage_ratio_chars: 2.2,
      user_yield_ratio_tokens: 0,
      user_yield_ratio_chars: 0,
    } as unknown as SessionStatistics;

    const vm = buildSessionStatisticsViewModel(statistics, index.codex);
    expect(vm.automationRatio).toBe(3);
    expect(vm.tokenYieldRatio).toBe(3);
    expect(vm.charYieldRatio).toBe(2.2);
    expect(vm.capabilityNotices.length).toBeGreaterThan(0);
  });
});
