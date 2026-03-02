/**
 * React Query hooks for session data with caching and optimistic updates.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query';
import {
  fetchAnalyticsDistribution,
  fetchAnalyticsOverview,
  fetchAnalyticsTimeseries,
  fetchProjectComparison,
  fetchProjectSwimlane,
  fetchFrontendPreferences,
  fetchSyncStatus,
  fetchSessions,
  fetchSessionDetail,
  fetchSessionStatistics,
  triggerSync,
  updateFrontendPreferences,
} from '../api/sessions';
import type {
  AnalyticsDimension,
  AnalyticsDistributionResponse,
  AnalyticsInterval,
  AnalyticsOverviewResponse,
  AnalyticsTimeseriesResponse,
  FrontendPreferences,
  FrontendPreferencesUpdate,
  ProjectComparisonResponse,
  ProjectSwimlaneResponse,
  SyncRunDetail,
  SyncStatusResponse,
  SessionListResponse,
  SessionDetailResponse,
  SessionStatisticsResponse,
} from '../types/session';

/**
 * Query keys for React Query caching
 */
export const sessionKeys = {
  all: ['sessions'] as const,
  lists: () => [...sessionKeys.all, 'list'] as const,
  list: (
    page: number,
    pageSize: number,
    startDate?: string | null,
    endDate?: string | null,
    viewMode: 'logical' | 'physical' = 'logical',
  ) =>
    [...sessionKeys.lists(), { page, pageSize, startDate, endDate, viewMode }] as const,
  details: () => [...sessionKeys.all, 'detail'] as const,
  detail: (id: string) => [...sessionKeys.details(), id] as const,
  statistics: () => [...sessionKeys.all, 'statistics'] as const,
  statistic: (id: string) => [...sessionKeys.statistics(), id] as const,
  analytics: () => [...sessionKeys.all, 'analytics'] as const,
  analyticsOverview: (startDate: string | null, endDate: string | null) =>
    [...sessionKeys.analytics(), 'overview', { startDate, endDate }] as const,
  analyticsOverviewByEcosystem: (
    startDate: string | null,
    endDate: string | null,
    ecosystem: string | null,
  ) => [...sessionKeys.analytics(), 'overview', { startDate, endDate, ecosystem }] as const,
  analyticsDistribution: (
    dimension: AnalyticsDimension,
    startDate: string | null,
    endDate: string | null,
    ecosystem: string | null,
  ) =>
    [...sessionKeys.analytics(), 'distribution', { dimension, startDate, endDate, ecosystem }] as const,
  analyticsTimeseries: (
    interval: AnalyticsInterval,
    startDate: string | null,
    endDate: string | null,
    ecosystem: string | null,
  ) =>
    [...sessionKeys.analytics(), 'timeseries', { interval, startDate, endDate, ecosystem }] as const,
  projectComparison: (
    startDate: string | null,
    endDate: string | null,
    limit: number,
    ecosystem: string | null,
  ) =>
    [...sessionKeys.analytics(), 'project-comparison', { startDate, endDate, limit, ecosystem }] as const,
  projectSwimlane: (
    interval: AnalyticsInterval,
    startDate: string | null,
    endDate: string | null,
    projectLimit: number,
    ecosystem: string | null,
  ) =>
    [
      ...sessionKeys.analytics(),
      'project-swimlane',
      { interval, startDate, endDate, projectLimit, ecosystem },
    ] as const,
  syncStatus: () => [...sessionKeys.all, 'sync-status'] as const,
  frontendPreferences: () => [...sessionKeys.all, 'frontend-preferences'] as const,
};

/**
 * Hook to fetch sessions list with pagination and optional date filtering
 */
export function useSessionsQuery(
  page: number = 1,
  pageSize: number = 50,
  startDate: string | null = null,
  endDate: string | null = null,
  viewMode: 'logical' | 'physical' = 'logical',
): UseQueryResult<SessionListResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.list(page, pageSize, startDate, endDate, viewMode),
    queryFn: () => fetchSessions(page, pageSize, startDate, endDate, viewMode),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

/**
 * Hook to fetch session detail
 */
export function useSessionDetailQuery(
  sessionId: string | null
): UseQueryResult<SessionDetailResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.detail(sessionId || ''),
    queryFn: () => fetchSessionDetail(sessionId!),
    enabled: !!sessionId,
    staleTime: 10 * 60 * 1000, // 10 minutes - session data is immutable
  });
}

/**
 * Hook to fetch session statistics
 */
export function useSessionStatisticsQuery(
  sessionId: string | null
): UseQueryResult<SessionStatisticsResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.statistic(sessionId || ''),
    queryFn: () => fetchSessionStatistics(sessionId!),
    enabled: !!sessionId,
    staleTime: 10 * 60 * 1000, // 10 minutes - statistics are immutable
  });
}

/**
 * Hook to fetch cross-session analytics overview.
 */
export function useAnalyticsOverviewQuery(
  startDate: string | null = null,
  endDate: string | null = null,
  ecosystem: string | null = null,
): UseQueryResult<AnalyticsOverviewResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.analyticsOverviewByEcosystem(startDate, endDate, ecosystem),
    queryFn: () => fetchAnalyticsOverview(startDate, endDate, ecosystem),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Hook to fetch cross-session analytics distribution.
 */
export function useAnalyticsDistributionQuery(
  dimension: AnalyticsDimension,
  startDate: string | null = null,
  endDate: string | null = null,
  ecosystem: string | null = null,
): UseQueryResult<AnalyticsDistributionResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.analyticsDistribution(dimension, startDate, endDate, ecosystem),
    queryFn: () => fetchAnalyticsDistribution(dimension, startDate, endDate, ecosystem),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Hook to fetch cross-session analytics timeseries.
 */
export function useAnalyticsTimeseriesQuery(
  interval: AnalyticsInterval = 'day',
  startDate: string | null = null,
  endDate: string | null = null,
  ecosystem: string | null = null,
): UseQueryResult<AnalyticsTimeseriesResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.analyticsTimeseries(interval, startDate, endDate, ecosystem),
    queryFn: () => fetchAnalyticsTimeseries(interval, startDate, endDate, ecosystem),
    staleTime: 60 * 1000, // 1 minute
  });
}

/**
 * Hook to fetch cross-session project comparison rows.
 */
export function useProjectComparisonQuery(
  startDate: string | null = null,
  endDate: string | null = null,
  limit: number = 10,
  ecosystem: string | null = null,
): UseQueryResult<ProjectComparisonResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.projectComparison(startDate, endDate, limit, ecosystem),
    queryFn: () => fetchProjectComparison(startDate, endDate, limit, ecosystem),
    staleTime: 60 * 1000,
  });
}

/**
 * Hook to fetch cross-session project swimlane points.
 */
export function useProjectSwimlaneQuery(
  interval: AnalyticsInterval = 'day',
  startDate: string | null = null,
  endDate: string | null = null,
  projectLimit: number = 12,
  ecosystem: string | null = null,
): UseQueryResult<ProjectSwimlaneResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.projectSwimlane(interval, startDate, endDate, projectLimit, ecosystem),
    queryFn: () => fetchProjectSwimlane(interval, startDate, endDate, projectLimit, ecosystem),
    staleTime: 60 * 1000,
  });
}

/**
 * Hook to fetch synchronization status.
 */
export function useSyncStatusQuery(): UseQueryResult<SyncStatusResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.syncStatus(),
    queryFn: fetchSyncStatus,
    staleTime: 15 * 1000,
    refetchInterval: 15 * 1000,
  });
}

/**
 * Hook to trigger manual synchronization.
 */
export function useRunSyncMutation() {
  const queryClient = useQueryClient();

  return useMutation<SyncRunDetail, Error, { force?: boolean }>({
    mutationFn: async ({ force = false }) => triggerSync(force),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: sessionKeys.syncStatus() }),
        queryClient.invalidateQueries({ queryKey: sessionKeys.lists() }),
      ]);
    },
  });
}

/**
 * Hook to fetch persisted frontend preferences.
 */
export function useFrontendPreferencesQuery(): UseQueryResult<FrontendPreferences, Error> {
  return useQuery({
    queryKey: sessionKeys.frontendPreferences(),
    queryFn: fetchFrontendPreferences,
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Hook to persist frontend preferences.
 */
export function useUpdateFrontendPreferencesMutation() {
  const queryClient = useQueryClient();

  return useMutation<FrontendPreferences, Error, FrontendPreferencesUpdate>({
    mutationFn: updateFrontendPreferences,
    onSuccess: (data) => {
      queryClient.setQueryData(sessionKeys.frontendPreferences(), data);
    },
  });
}
