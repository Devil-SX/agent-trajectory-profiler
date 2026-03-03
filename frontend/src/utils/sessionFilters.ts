import type { SessionSummary } from '../types/session';

export type SessionSortOption = 'updated' | 'created' | 'tokens' | 'duration' | 'automation';
export type SessionBottleneckFilter = 'all' | 'model' | 'tool' | 'user';

export function filterSessions(
  sessions: SessionSummary[],
  searchQuery: string,
  bottleneckFilter: SessionBottleneckFilter
): SessionSummary[] {
  let filtered = sessions;

  const normalizedSearch = searchQuery.trim().toLowerCase();
  if (normalizedSearch.length > 0) {
    filtered = filtered.filter(
      (session) =>
        session.project_path.toLowerCase().includes(normalizedSearch) ||
        session.session_id.toLowerCase().includes(normalizedSearch)
    );
  }

  if (bottleneckFilter !== 'all') {
    filtered = filtered.filter(
      (session) => session.bottleneck?.toLowerCase() === bottleneckFilter.toLowerCase()
    );
  }

  return filtered;
}

export function sortSessions(
  sessions: SessionSummary[],
  sortBy: SessionSortOption
): SessionSummary[] {
  return [...sessions].sort((a, b) => {
    switch (sortBy) {
      case 'updated':
        return (
          new Date(b.updated_at || b.created_at).getTime() -
          new Date(a.updated_at || a.created_at).getTime()
        );
      case 'created':
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      case 'tokens':
        return b.total_tokens - a.total_tokens;
      case 'duration':
        return (b.duration_seconds || 0) - (a.duration_seconds || 0);
      case 'automation':
        return (b.automation_ratio || 0) - (a.automation_ratio || 0);
      default:
        return 0;
    }
  });
}

export function filterAndSortSessions(
  sessions: SessionSummary[],
  searchQuery: string,
  bottleneckFilter: SessionBottleneckFilter,
  sortBy: SessionSortOption
): SessionSummary[] {
  const filtered = filterSessions(sessions, searchQuery, bottleneckFilter);
  return sortSessions(filtered, sortBy);
}
