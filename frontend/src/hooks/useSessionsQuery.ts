/**
 * React Query hooks for session data with caching and optimistic updates.
 */

import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import {
  fetchSessions,
  fetchSessionDetail,
  fetchSessionStatistics,
} from '../api/sessions';
import type {
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
