import { describe, expect, it } from 'vitest';
import type { SessionSummary } from '../../src/types/session';
import { filterAndSortSessions, filterSessions, sortSessions } from '../../src/utils/sessionFilters';

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
    automation_ratio: 0.4,
  },
];

describe('sessionFilters', () => {
  it('filters by search query and bottleneck', () => {
    const byProject = filterSessions(sessions, 'frontend-app', 'all');
    expect(byProject).toHaveLength(2);

    const byId = filterSessions(sessions, 'session-02', 'all');
    expect(byId.map((session) => session.session_id)).toEqual(['session-02']);

    const byBottleneck = filterSessions(sessions, '', 'tool');
    expect(byBottleneck.map((session) => session.session_id)).toEqual(['session-02']);
  });

  it('sorts according to requested strategy', () => {
    expect(sortSessions(sessions, 'tokens')[0].session_id).toBe('session-02');
    expect(sortSessions(sessions, 'duration')[0].session_id).toBe('session-02');
    expect(sortSessions(sessions, 'automation')[0].session_id).toBe('session-02');
    expect(sortSessions(sessions, 'created')[0].session_id).toBe('session-02');
    expect(sortSessions(sessions, 'updated')[0].session_id).toBe('session-02');
  });

  it('combines filter and sort deterministically', () => {
    const result = filterAndSortSessions(sessions, 'frontend-app', 'all', 'tokens');
    expect(result.map((session) => session.session_id)).toEqual(['session-01', 'session-03']);
  });
});
