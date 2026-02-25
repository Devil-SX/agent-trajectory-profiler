/**
 * SessionSelector component for selecting Claude Code sessions.
 *
 * Features:
 * - Fetches sessions from API
 * - Displays session name/ID and timestamp
 * - Supports single-session mode via URL parameter
 * - Handles loading and error states
 */

import { useEffect, useState, useRef } from 'react';
import toast from 'react-hot-toast';
import { useSessionsQuery } from '../hooks/useSessionsQuery';
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
  const [page] = useState(1);
  const [pageSize] = useState(200); // Fetch more sessions for dropdown
  const { data, isLoading, error: queryError } = useSessionsQuery(page, pageSize);

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [comparisonSessionId, setComparisonSessionId] = useState<string | null>(null);

  const sessions: SessionSummary[] = data?.sessions || [];
  const loading = isLoading;
  const error = queryError?.message || null;

  // Initialize selection on first load - using a ref to track if we've done this
  const initRef = useRef(false);

  useEffect(() => {
    // Only notify parent of selection changes after initialization
    if (sessions.length > 0 && !initRef.current) {
      const urlParams = new URLSearchParams(window.location.search);
      const sessionIdParam = urlParams.get('session');

      let initialSessionId: string | null = null;

      if (sessionIdParam) {
        const sessionExists = sessions.some((s) => s.session_id === sessionIdParam);
        if (sessionExists) {
          initialSessionId = sessionIdParam;
        } else {
          toast.error(`Session not found: ${sessionIdParam}`);
        }
      } else {
        initialSessionId = sessions[0].session_id;
      }

      if (initialSessionId) {
        // Use setTimeout to defer state update to next tick
        setTimeout(() => {
          setSelectedSessionId(initialSessionId);
          onSessionChange?.(initialSessionId);
        }, 0);
      }

      initRef.current = true;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions.length, onSessionChange]);

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

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

  const formatDuration = (seconds: number | null): string => {
    if (seconds == null) return '';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    if (mins < 60) return `${mins}m`;
    return `${Math.floor(mins / 60)}h ${mins % 60}m`;
  };

  const formatOptionLabel = (session: SessionSummary): string => {
    const date = new Date(session.created_at).toLocaleString();
    const dur = session.duration_seconds ? ` (${formatDuration(session.duration_seconds)})` : '';
    const bn = session.bottleneck ? ` [${session.bottleneck}]` : '';
    return `${session.session_id.slice(0, 8)}... - ${date}${dur}${bn}`;
  };

  return (
    <div className="session-selector">
      <div className="selector-row">
        <label htmlFor="session-select">Session:</label>
        <select id="session-select" value={selectedSessionId || ''} onChange={handleSessionChange}>
          {sessions.map((session) => (
            <option key={session.session_id} value={session.session_id}>
              {formatOptionLabel(session)}
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
