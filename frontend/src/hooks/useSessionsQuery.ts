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
  fetchSyncStatus,
  fetchSessions,
  fetchSessionDetail,
  fetchSessionStatistics,
  triggerSync,
} from '../api/sessions';
import type {
  AnalyticsDimension,
  AnalyticsDistributionResponse,
  AnalyticsInterval,
  AnalyticsOverviewResponse,
  AnalyticsTimeseriesResponse,
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
  list: (page: number, pageSize: number, startDate?: string | null, endDate?: string | null) =>
    [...sessionKeys.lists(), { page, pageSize, startDate, endDate }] as const,
  details: () => [...sessionKeys.all, 'detail'] as const,
  detail: (id: string) => [...sessionKeys.details(), id] as const,
  statistics: () => [...sessionKeys.all, 'statistics'] as const,
  statistic: (id: string) => [...sessionKeys.statistics(), id] as const,
  analytics: () => [...sessionKeys.all, 'analytics'] as const,
  analyticsOverview: (startDate: string | null, endDate: string | null) =>
    [...sessionKeys.analytics(), 'overview', { startDate, endDate }] as const,
  analyticsDistribution: (
    dimension: AnalyticsDimension,
    startDate: string | null,
    endDate: string | null,
  ) =>
    [...sessionKeys.analytics(), 'distribution', { dimension, startDate, endDate }] as const,
  analyticsTimeseries: (
    interval: AnalyticsInterval,
    startDate: string | null,
    endDate: string | null,
  ) =>
    [...sessionKeys.analytics(), 'timeseries', { interval, startDate, endDate }] as const,
  syncStatus: () => [...sessionKeys.all, 'sync-status'] as const,
};

/**
 * Hook to fetch sessions list with pagination and optional date filtering
 */
export function useSessionsQuery(
  page: number = 1,
  pageSize: number = 50,
  startDate: string | null = null,
  endDate: string | null = null
): UseQueryResult<SessionListResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.list(page, pageSize, startDate, endDate),
    queryFn: () => fetchSessions(page, pageSize, startDate, endDate),
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
  endDate: string | null = null
): UseQueryResult<AnalyticsOverviewResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.analyticsOverview(startDate, endDate),
    queryFn: () => fetchAnalyticsOverview(startDate, endDate),
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
): UseQueryResult<AnalyticsDistributionResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.analyticsDistribution(dimension, startDate, endDate),
    queryFn: () => fetchAnalyticsDistribution(dimension, startDate, endDate),
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
): UseQueryResult<AnalyticsTimeseriesResponse, Error> {
  return useQuery({
    queryKey: sessionKeys.analyticsTimeseries(interval, startDate, endDate),
    queryFn: () => fetchAnalyticsTimeseries(interval, startDate, endDate),
    staleTime: 60 * 1000, // 1 minute
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
