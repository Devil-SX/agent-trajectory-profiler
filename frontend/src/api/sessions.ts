/**
 * API client for session-related endpoints.
 */

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

function resolveApiBaseUrl(): string {
  const fromEnv = import.meta.env.VITE_API_BASE_URL?.trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, '');
  }

  if (typeof window === 'undefined') {
    return 'http://localhost:8000';
  }

  const { hostname, port, protocol } = window.location;

  // Local frontend dev server should target backend on :8000 by default.
  if (port === '5173' || port === '5174' || port === '3000') {
    return `${protocol}//${hostname}:8000`;
  }

  // When served from backend/static host, use same-origin API paths.
  return '';
}

const API_BASE_URL = resolveApiBaseUrl();

/**
 * Retry configuration
 */
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

/**
 * Custom error class for API errors with status code
 */
export class APIError extends Error {
  statusCode: number;
  isNetworkError: boolean;

  constructor(
    message: string,
    statusCode: number,
    isNetworkError: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
    this.statusCode = statusCode;
    this.isNetworkError = isNetworkError;
  }
}

/**
 * Sleep utility for retry delays
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/**
 * Get user-friendly error message based on status code
 */
function getUserFriendlyMessage(statusCode: number, defaultMessage: string): string {
  switch (statusCode) {
    case 404:
      return 'The requested resource was not found';
    case 500:
      return 'Server error occurred. Please try again later';
    case 503:
      return 'Service is temporarily unavailable. Please try again';
    default:
      return defaultMessage;
  }
}

/**
 * Fetch with automatic retry logic for network errors and 5xx status codes
 */
async function fetchWithRetry(
  url: string,
  options?: RequestInit,
  retries: number = MAX_RETRIES
): Promise<Response> {
  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await fetch(url, options);

      // Don't retry on 4xx client errors (except auth issues)
      if (!response.ok && response.status >= 400 && response.status < 500) {
        const errorText = await response.text();
        const message = getUserFriendlyMessage(
          response.status,
          `Request failed: ${response.status} ${errorText}`
        );
        throw new APIError(message, response.status);
      }

      // Retry on 5xx server errors
      if (!response.ok && response.status >= 500) {
        const errorText = await response.text();
        const message = getUserFriendlyMessage(
          response.status,
          `Server error: ${response.status} ${errorText}`
        );
        lastError = new APIError(message, response.status);

        if (attempt < retries) {
          console.warn(`Attempt ${attempt + 1}/${retries + 1} failed, retrying...`);
          await sleep(RETRY_DELAY_MS * (attempt + 1)); // Exponential backoff
          continue;
        }
        throw lastError;
      }

      return response;
    } catch (error) {
      // Network errors (no response)
      if (error instanceof TypeError && error.message.includes('fetch')) {
        lastError = new APIError(
          'Network error: Unable to connect to server. Please check your connection.',
          0,
          true
        );

        if (attempt < retries) {
          console.warn(`Network error on attempt ${attempt + 1}/${retries + 1}, retrying...`);
          await sleep(RETRY_DELAY_MS * (attempt + 1));
          continue;
        }
        throw lastError;
      }

      // Re-throw APIError or other errors
      throw error;
    }
  }

  // Should not reach here, but TypeScript needs this
  throw lastError || new Error('Unknown error occurred');
}

/**
 * Fetch all available sessions from the API with pagination and optional date filtering.
 *
 * @param page - Page number (1-indexed, default: 1)
 * @param pageSize - Number of items per page (default: 50)
 * @param startDate - Filter sessions updated after this date (ISO 8601: YYYY-MM-DD)
 * @param endDate - Filter sessions updated before this date (ISO 8601: YYYY-MM-DD)
 * @returns Promise resolving to session list response
 * @throws APIError if the API request fails
 */
export async function fetchSessions(
  page: number = 1,
  pageSize: number = 50,
  startDate: string | null = null,
  endDate: string | null = null,
  viewMode: 'logical' | 'physical' = 'logical'
): Promise<SessionListResponse> {
  try {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
      view: viewMode,
    });

    if (startDate) {
      params.append('start_date', startDate);
    }

    if (endDate) {
      params.append('end_date', endDate);
    }

    const response = await fetchWithRetry(`${API_BASE_URL}/api/sessions?${params}`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch sessions:', error);
    }
    throw error;
  }
}

/**
 * Fetch detailed session data including all messages.
 *
 * @param sessionId - The session ID to fetch
 * @returns Promise resolving to session detail response
 * @throws APIError if the API request fails
 */
export async function fetchSessionDetail(sessionId: string): Promise<SessionDetailResponse> {
  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/sessions/${sessionId}`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error(`Failed to fetch session ${sessionId}:`, error);
    }
    throw error;
  }
}

/**
 * Fetch session statistics and analytics.
 *
 * @param sessionId - The session ID to fetch statistics for
 * @returns Promise resolving to session statistics response
 * @throws APIError if the API request fails
 */
export async function fetchSessionStatistics(
  sessionId: string,
): Promise<SessionStatisticsResponse> {
  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/sessions/${sessionId}/statistics`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error(`Failed to fetch statistics for session ${sessionId}:`, error);
    }
    throw error;
  }
}

/**
 * Fetch cross-session analytics overview.
 *
 * @param startDate - Optional start date (YYYY-MM-DD)
 * @param endDate - Optional end date (YYYY-MM-DD)
 */
export async function fetchAnalyticsOverview(
  startDate: string | null = null,
  endDate: string | null = null,
  ecosystem: string | null = null,
): Promise<AnalyticsOverviewResponse> {
  try {
    const params = new URLSearchParams();
    if (startDate) {
      params.append('start_date', startDate);
    }
    if (endDate) {
      params.append('end_date', endDate);
    }
    if (ecosystem) {
      params.append('ecosystem', ecosystem);
    }

    const suffix = params.toString() ? `?${params.toString()}` : '';
    const response = await fetchWithRetry(`${API_BASE_URL}/api/analytics/overview${suffix}`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch analytics overview:', error);
    }
    throw error;
  }
}

/**
 * Fetch cross-session analytics distribution for a single dimension.
 *
 * @param dimension - Distribution dimension
 * @param startDate - Optional start date (YYYY-MM-DD)
 * @param endDate - Optional end date (YYYY-MM-DD)
 */
export async function fetchAnalyticsDistribution(
  dimension: AnalyticsDimension,
  startDate: string | null = null,
  endDate: string | null = null,
  ecosystem: string | null = null,
): Promise<AnalyticsDistributionResponse> {
  try {
    const params = new URLSearchParams({
      dimension,
    });
    if (startDate) {
      params.append('start_date', startDate);
    }
    if (endDate) {
      params.append('end_date', endDate);
    }
    if (ecosystem) {
      params.append('ecosystem', ecosystem);
    }

    const response = await fetchWithRetry(`${API_BASE_URL}/api/analytics/distributions?${params.toString()}`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error(`Failed to fetch analytics distribution (${dimension}):`, error);
    }
    throw error;
  }
}

/**
 * Fetch cross-session analytics time-series.
 *
 * @param interval - Grouping interval (day|week)
 * @param startDate - Optional start date (YYYY-MM-DD)
 * @param endDate - Optional end date (YYYY-MM-DD)
 */
export async function fetchAnalyticsTimeseries(
  interval: AnalyticsInterval = 'day',
  startDate: string | null = null,
  endDate: string | null = null,
  ecosystem: string | null = null,
): Promise<AnalyticsTimeseriesResponse> {
  try {
    const params = new URLSearchParams({
      interval,
    });
    if (startDate) {
      params.append('start_date', startDate);
    }
    if (endDate) {
      params.append('end_date', endDate);
    }
    if (ecosystem) {
      params.append('ecosystem', ecosystem);
    }

    const response = await fetchWithRetry(`${API_BASE_URL}/api/analytics/timeseries?${params.toString()}`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch analytics timeseries:', error);
    }
    throw error;
  }
}

/**
 * Fetch project comparison KPI rows for cross-session analytics.
 */
export async function fetchProjectComparison(
  startDate: string | null = null,
  endDate: string | null = null,
  limit: number = 10,
  ecosystem: string | null = null,
): Promise<ProjectComparisonResponse> {
  try {
    const params = new URLSearchParams({
      limit: String(limit),
    });
    if (startDate) {
      params.append('start_date', startDate);
    }
    if (endDate) {
      params.append('end_date', endDate);
    }
    if (ecosystem) {
      params.append('ecosystem', ecosystem);
    }
    const response = await fetchWithRetry(
      `${API_BASE_URL}/api/analytics/project-comparison?${params.toString()}`
    );
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch project comparison:', error);
    }
    throw error;
  }
}

/**
 * Fetch swimlane points for cross-session project activity.
 */
export async function fetchProjectSwimlane(
  interval: AnalyticsInterval = 'day',
  startDate: string | null = null,
  endDate: string | null = null,
  projectLimit: number = 12,
  ecosystem: string | null = null,
): Promise<ProjectSwimlaneResponse> {
  try {
    const params = new URLSearchParams({
      interval,
      project_limit: String(projectLimit),
    });
    if (startDate) {
      params.append('start_date', startDate);
    }
    if (endDate) {
      params.append('end_date', endDate);
    }
    if (ecosystem) {
      params.append('ecosystem', ecosystem);
    }
    const response = await fetchWithRetry(
      `${API_BASE_URL}/api/analytics/project-swimlane?${params.toString()}`
    );
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch project swimlane:', error);
    }
    throw error;
  }
}

/**
 * Fetch synchronization status and last-run details.
 */
export async function fetchSyncStatus(): Promise<SyncStatusResponse> {
  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/sync/status`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch sync status:', error);
    }
    throw error;
  }
}

/**
 * Trigger manual synchronization.
 */
export async function triggerSync(force: boolean = false): Promise<SyncRunDetail> {
  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/sync/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ force }),
    });
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to trigger sync:', error);
    }
    throw error;
  }
}

/**
 * Fetch persisted frontend preferences from local state storage.
 */
export async function fetchFrontendPreferences(): Promise<FrontendPreferences> {
  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/state/frontend-preferences`);
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to fetch frontend preferences:', error);
    }
    throw error;
  }
}

/**
 * Persist partial frontend preference updates.
 */
export async function updateFrontendPreferences(
  payload: FrontendPreferencesUpdate
): Promise<FrontendPreferences> {
  try {
    const response = await fetchWithRetry(`${API_BASE_URL}/api/state/frontend-preferences`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
    return response.json();
  } catch (error) {
    if (import.meta.env.DEV) {
      console.error('Failed to update frontend preferences:', error);
    }
    throw error;
  }
}
