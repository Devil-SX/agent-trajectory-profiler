import { describe, expect, it } from 'vitest';
import type { SessionSummary } from '../../src/types/session';
import {
  buildSessionQueryFilters,
  DEFAULT_SESSION_FILTERS,
  filterAndSortSessions,
  filterSessions,
  hasActiveSessionFilter,
  resolveAutomationRange,
  sortSessions,
} from '../../src/utils/sessionFilters';

const sessions: SessionSummary[] = [
  {
    session_id: 'session-01',
    ecosystem: 'codex',
    project_path: '/home/sdu/frontend-app',
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T10:30:00Z',
    total_messages: 20,
    total_tokens: 12000,
    git_branch: 'main',
    version: '1.0.0',
    parsed_at: null,
    duration_seconds: 1800,
    bottleneck: 'model',
    automation_ratio: 0.7,
  },
  {
    session_id: 'session-02',
    ecosystem: 'claude_code',
    project_path: '/home/sdu/backend-api',
    created_at: '2026-03-02T08:00:00Z',
    updated_at: '2026-03-02T09:00:00Z',
    total_messages: 35,
    total_tokens: 30000,
    git_branch: 'feature/x',
    version: '1.0.0',
    parsed_at: null,
    duration_seconds: 4200,
    bottleneck: 'tool',
    automation_ratio: 1.2,
  },
  {
    session_id: 'session-03',
    ecosystem: 'codex',
    project_path: '/home/sdu/frontend-app',
    created_at: '2026-03-01T12:00:00Z',
    updated_at: null,
    total_messages: 12,
    total_tokens: 5000,
    git_branch: 'main',
    version: '1.0.0',
    parsed_at: null,
    duration_seconds: 900,
    bottleneck: 'user',
    automation_ratio: 3.4,
  },
];

describe('sessionFilters', () => {
  it('applies multi-dimensional filters with AND semantics', () => {
    const filtered = filterSessions(sessions, {
      ...DEFAULT_SESSION_FILTERS,
      search_query: 'frontend-app',
      ecosystem: 'codex',
      bottleneck: 'user',
      token_min: 3000,
      token_max: 7000,
      message_min: 10,
      message_max: 15,
      automation_band: 'high',
    });

    expect(filtered.map((session) => session.session_id)).toEqual(['session-03']);
  });

  it('resolves automation band and manual range as intersection', () => {
    expect(resolveAutomationRange('medium', null, null)).toEqual([1, 3]);
    expect(resolveAutomationRange('medium', 1.5, 2.2)).toEqual([1.5, 2.2]);
    expect(resolveAutomationRange('high', 4.0, null)).toEqual([4.0, null]);
  });

  it('supports sort direction for all key metrics', () => {
    expect(sortSessions(sessions, 'tokens', 'desc')[0].session_id).toBe('session-02');
    expect(sortSessions(sessions, 'tokens', 'asc')[0].session_id).toBe('session-03');

    expect(sortSessions(sessions, 'messages', 'desc')[0].session_id).toBe('session-02');
    expect(sortSessions(sessions, 'messages', 'asc')[0].session_id).toBe('session-03');
  });

  it('combines filtering and sorting deterministically', () => {
    const result = filterAndSortSessions(sessions, {
      ...DEFAULT_SESSION_FILTERS,
      ecosystem: 'codex',
      sort_by: 'tokens',
      sort_direction: 'asc',
    });
    expect(result.map((session) => session.session_id)).toEqual(['session-03', 'session-01']);
  });

  it('builds server query filters from browser state', () => {
    const query = buildSessionQueryFilters({
      ...DEFAULT_SESSION_FILTERS,
      bottleneck: 'tool',
      ecosystem: 'claude_code',
      sort_by: 'messages',
      sort_direction: 'asc',
      token_min: 1000,
      message_max: 60,
      automation_band: 'medium',
    });

    expect(query).toEqual({
      bottleneck: 'tool',
      ecosystem: 'claude_code',
      sort_by: 'messages',
      sort_direction: 'asc',
      min_tokens: 1000,
      max_tokens: null,
      min_messages: null,
      max_messages: 60,
      min_automation: 1,
      max_automation: 3,
    });
  });

  it('tracks whether any filter is active', () => {
    expect(hasActiveSessionFilter(DEFAULT_SESSION_FILTERS)).toBe(false);
    expect(
      hasActiveSessionFilter({
        ...DEFAULT_SESSION_FILTERS,
        search_query: 'abc',
      })
    ).toBe(true);
  });
});
