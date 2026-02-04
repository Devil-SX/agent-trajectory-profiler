/**
 * API client for session-related endpoints.
 */

import type {
  SessionListResponse,
  SessionDetailResponse,
  SessionStatisticsResponse,
} from '../types/session';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

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
 * Fetch all available sessions from the API with pagination support.
 *
 * @param page - Page number (1-indexed, default: 1)
 * @param pageSize - Number of items per page (default: 50)
 * @returns Promise resolving to session list response
 * @throws APIError if the API request fails
 */
export async function fetchSessions(
  page: number = 1,
  pageSize: number = 50
): Promise<SessionListResponse> {
  try {
    const params = new URLSearchParams({
      page: page.toString(),
      page_size: pageSize.toString(),
    });
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
