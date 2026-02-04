/**
 * API client for session-related endpoints.
 */

import type { SessionListResponse, SessionDetailResponse } from '../types/session';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * Fetch all available sessions from the API.
 *
 * @returns Promise resolving to session list response
 * @throws Error if the API request fails
 */
export async function fetchSessions(): Promise<SessionListResponse> {
  const response = await fetch(`${API_BASE_URL}/api/sessions`);

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to fetch sessions: ${response.status} ${errorText}`);
  }

  return response.json();
}

/**
 * Fetch detailed session data including all messages.
 *
 * @param sessionId - The session ID to fetch
 * @returns Promise resolving to session detail response
 * @throws Error if the API request fails
 */
export async function fetchSessionDetail(sessionId: string): Promise<SessionDetailResponse> {
  const response = await fetch(`${API_BASE_URL}/api/sessions/${sessionId}`);

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to fetch session details: ${response.status} ${errorText}`);
  }

  return response.json();
}
