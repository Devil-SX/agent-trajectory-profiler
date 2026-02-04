/**
 * SessionSelector component for selecting Claude Code sessions.
 *
 * Features:
 * - Fetches sessions from API
 * - Displays session name/ID and timestamp
 * - Supports single-session mode via URL parameter
 * - Handles loading and error states
 */

import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { fetchSessions, APIError } from '../api/sessions';
import type { SessionSummary } from '../types/session';
import './SessionSelector.css';

interface SessionSelectorProps {
  onSessionChange?: (sessionId: string | null) => void;
  onComparisonSessionChange?: (sessionId: string | null) => void;
  selectedSessionId?: string | null;
  comparisonSessionId?: string | null;
}

export function SessionSelector({
  onSessionChange,
  onComparisonSessionChange,
}: SessionSelectorProps) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [comparisonSessionId, setComparisonSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Check for single-session mode via URL parameter
    const urlParams = new URLSearchParams(window.location.search);
    const sessionIdParam = urlParams.get('session');

    async function loadSessions() {
      try {
        setLoading(true);
        setError(null);
        const data = await fetchSessions();
        setSessions(data.sessions);

        // If single-session mode is enabled via URL parameter
        if (sessionIdParam) {
          const sessionExists = data.sessions.some((s) => s.session_id === sessionIdParam);
          if (sessionExists) {
            setSelectedSessionId(sessionIdParam);
            onSessionChange?.(sessionIdParam);
          } else {
            const errorMsg = `Session not found: ${sessionIdParam}`;
            setError(errorMsg);
            toast.error(errorMsg);
          }
        } else if (data.sessions.length > 0) {
          // Default to first session in default mode
          setSelectedSessionId(data.sessions[0].session_id);
          onSessionChange?.(data.sessions[0].session_id);
        }
      } catch (err) {
        const errorMessage = err instanceof APIError ? err.message : 'Failed to load sessions';
        setError(errorMessage);
        toast.error(errorMessage);
        console.error('Failed to load sessions:', err);
      } finally {
        setLoading(false);
      }
    }

    loadSessions();
  }, [onSessionChange]);

  const handleSessionChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const sessionId = event.target.value;
    setSelectedSessionId(sessionId);
    onSessionChange?.(sessionId);
  };

  const handleComparisonSessionChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const sessionId = event.target.value || null;
    setComparisonSessionId(sessionId);
    onComparisonSessionChange?.(sessionId);
  };

  if (loading) {
    return (
      <div className="session-selector loading">
        <label htmlFor="session-select">Session:</label>
        <select id="session-select" disabled>
          <option>Loading sessions...</option>
        </select>
      </div>
    );
  }

  if (error) {
    return (
      <div className="session-selector error">
        <label htmlFor="session-select">Session:</label>
        <select id="session-select" disabled>
          <option>Error: {error}</option>
        </select>
        <p className="error-message">{error}</p>
      </div>
    );
  }

  if (sessions.length === 0) {
    return (
      <div className="session-selector empty">
        <label htmlFor="session-select">Session:</label>
        <select id="session-select" disabled>
          <option>No sessions available</option>
        </select>
      </div>
    );
  }

  const showComparison = onComparisonSessionChange !== undefined;

  return (
    <div className="session-selector">
      <div className="selector-row">
        <label htmlFor="session-select">Session:</label>
        <select id="session-select" value={selectedSessionId || ''} onChange={handleSessionChange}>
          {sessions.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {session.session_id} - {new Date(session.created_at).toLocaleString()}
            </option>
          ))}
        </select>
      </div>

      {showComparison && (
        <div className="selector-row">
          <label htmlFor="comparison-select">Compare with:</label>
          <select
            id="comparison-select"
            value={comparisonSessionId || ''}
            onChange={handleComparisonSessionChange}
          >
            <option value="">None</option>
            {sessions
              .filter((s) => s.session_id !== selectedSessionId)
              .map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.session_id} - {new Date(session.created_at).toLocaleString()}
                </option>
              ))}
          </select>
        </div>
      )}

      <div className="session-info">
        {selectedSessionId && (
          <>
            <span className="session-count">
              {sessions.length} session{sessions.length !== 1 ? 's' : ''} available
            </span>
          </>
        )}
      </div>
    </div>
  );
}
