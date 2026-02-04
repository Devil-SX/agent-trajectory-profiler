/**
 * API client for session-related endpoints.
 */

import type { SessionListResponse } from '../types/session';

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
