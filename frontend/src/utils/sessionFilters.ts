import type {
  SessionAutomationBand,
  SessionBottleneckFilter,
  SessionBrowserFilters,
  SessionEcosystemFilter,
  SessionQueryFilters,
  SessionSortDirection,
  SessionSortOption,
  SessionSummary,
} from '../types/session';

export type {
  SessionAutomationBand,
  SessionBottleneckFilter,
  SessionBrowserFilters,
  SessionEcosystemFilter,
  SessionSortDirection,
  SessionSortOption,
};

export const DEFAULT_SESSION_FILTERS: SessionBrowserFilters = {
  search_query: '',
  start_date: null,
  end_date: null,
  sort_by: 'updated',
  sort_direction: 'desc',
  bottleneck: 'all',
  ecosystem: 'all',
  token_min: null,
  token_max: null,
  message_min: null,
  message_max: null,
  automation_band: 'all',
  automation_min: null,
  automation_max: null,
};

function normalizeText(value: string): string {
  return value.trim().toLowerCase();
}

function valueOrNull(value: number | null | undefined): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (!Number.isFinite(value)) {
    return null;
  }
  return value;
}

function normalizeRange(
  minValue: number | null | undefined,
  maxValue: number | null | undefined
): [number | null, number | null] {
  const min = valueOrNull(minValue);
  const max = valueOrNull(maxValue);
  if (min !== null && max !== null && min > max) {
    return [max, min];
  }
  return [min, max];
}

function automationBandRange(
  band: SessionAutomationBand
): [number | null, number | null] {
  if (band === 'low') {
    return [0, 1];
  }
  if (band === 'medium') {
    return [1, 3];
  }
  if (band === 'high') {
    return [3, null];
  }
  return [null, null];
}

export function resolveAutomationRange(
  band: SessionAutomationBand,
  minValue: number | null | undefined,
  maxValue: number | null | undefined
): [number | null, number | null] {
  const [bandMin, bandMax] = automationBandRange(band);
  const [manualMin, manualMax] = normalizeRange(minValue, maxValue);

  let mergedMin = manualMin;
  let mergedMax = manualMax;

  if (bandMin !== null) {
    mergedMin = mergedMin === null ? bandMin : Math.max(mergedMin, bandMin);
  }
  if (bandMax !== null) {
    mergedMax = mergedMax === null ? bandMax : Math.min(mergedMax, bandMax);
  }

  if (mergedMin !== null && mergedMax !== null && mergedMin > mergedMax) {
    return [mergedMax, mergedMin];
  }
  return [mergedMin, mergedMax];
}

export function filterSessions(
  sessions: SessionSummary[],
  filters: SessionBrowserFilters
): SessionSummary[] {
  const normalizedSearch = normalizeText(filters.search_query);
  const bottleneckFilter = filters.bottleneck;
  const ecosystemFilter = filters.ecosystem;
  const [tokenMin, tokenMax] = normalizeRange(filters.token_min, filters.token_max);
  const [messageMin, messageMax] = normalizeRange(filters.message_min, filters.message_max);
  const [automationMin, automationMax] = resolveAutomationRange(
    filters.automation_band,
    filters.automation_min,
    filters.automation_max
  );

  return sessions.filter((session) => {
    if (normalizedSearch.length > 0) {
      const projectPath = (session.project_path || '').toLowerCase();
      const sessionId = (session.session_id || '').toLowerCase();
      if (!projectPath.includes(normalizedSearch) && !sessionId.includes(normalizedSearch)) {
        return false;
      }
    }

    if (bottleneckFilter !== 'all') {
      const normalizedBottleneck = (session.bottleneck || '').trim().toLowerCase();
      if (normalizedBottleneck !== bottleneckFilter) {
        return false;
      }
    }

    if (ecosystemFilter !== 'all' && session.ecosystem !== ecosystemFilter) {
      return false;
    }

    if (tokenMin !== null && session.total_tokens < tokenMin) {
      return false;
    }
    if (tokenMax !== null && session.total_tokens > tokenMax) {
      return false;
    }

    if (messageMin !== null && session.total_messages < messageMin) {
      return false;
    }
    if (messageMax !== null && session.total_messages > messageMax) {
      return false;
    }

    if (automationMin !== null) {
      const ratio = session.automation_ratio;
      if (ratio === null || ratio < automationMin) {
        return false;
      }
    }
    if (automationMax !== null) {
      const ratio = session.automation_ratio;
      if (ratio === null || ratio > automationMax) {
        return false;
      }
    }

    return true;
  });
}

function compareNumbers(
  left: number | null | undefined,
  right: number | null | undefined
): number {
  const a = left ?? 0;
  const b = right ?? 0;
  return a - b;
}

export function sortSessions(
  sessions: SessionSummary[],
  sortBy: SessionSortOption,
  sortDirection: SessionSortDirection
): SessionSummary[] {
  const direction = sortDirection === 'asc' ? 1 : -1;
  return [...sessions].sort((a, b) => {
    let raw = 0;
    switch (sortBy) {
      case 'updated':
        raw =
          new Date(a.updated_at || a.created_at).getTime() -
          new Date(b.updated_at || b.created_at).getTime();
        break;
      case 'created':
        raw = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
        break;
      case 'tokens':
        raw = compareNumbers(a.total_tokens, b.total_tokens);
        break;
      case 'duration':
        raw = compareNumbers(a.duration_seconds, b.duration_seconds);
        break;
      case 'automation':
        raw = compareNumbers(a.automation_ratio, b.automation_ratio);
        break;
      case 'messages':
        raw = compareNumbers(a.total_messages, b.total_messages);
        break;
      default:
        raw = 0;
    }

    if (raw !== 0) {
      return raw * direction;
    }

    const fallback =
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    return fallback * direction;
  });
}

export function filterAndSortSessions(
  sessions: SessionSummary[],
  filters: SessionBrowserFilters
): SessionSummary[] {
  const filtered = filterSessions(sessions, filters);
  return sortSessions(filtered, filters.sort_by, filters.sort_direction);
}

export function buildSessionQueryFilters(
  filters: SessionBrowserFilters
): SessionQueryFilters {
  const [tokenMin, tokenMax] = normalizeRange(filters.token_min, filters.token_max);
  const [messageMin, messageMax] = normalizeRange(filters.message_min, filters.message_max);
  const [automationMin, automationMax] = resolveAutomationRange(
    filters.automation_band,
    filters.automation_min,
    filters.automation_max
  );

  return {
    ecosystem:
      filters.ecosystem === 'all'
        ? null
        : (filters.ecosystem as Exclude<SessionEcosystemFilter, 'all'>),
    bottleneck:
      filters.bottleneck === 'all'
        ? null
        : (filters.bottleneck as Exclude<SessionBottleneckFilter, 'all'>),
    sort_by: filters.sort_by,
    sort_direction: filters.sort_direction,
    min_tokens: tokenMin,
    max_tokens: tokenMax,
    min_messages: messageMin,
    max_messages: messageMax,
    min_automation: automationMin,
    max_automation: automationMax,
  };
}

export function hasActiveSessionFilter(filters: SessionBrowserFilters): boolean {
  return (
    filters.search_query.trim().length > 0 ||
    filters.start_date !== null ||
    filters.end_date !== null ||
    filters.sort_by !== DEFAULT_SESSION_FILTERS.sort_by ||
    filters.sort_direction !== DEFAULT_SESSION_FILTERS.sort_direction ||
    filters.bottleneck !== 'all' ||
    filters.ecosystem !== 'all' ||
    filters.token_min !== null ||
    filters.token_max !== null ||
    filters.message_min !== null ||
    filters.message_max !== null ||
    filters.automation_band !== 'all' ||
    filters.automation_min !== null ||
    filters.automation_max !== null
  );
}
