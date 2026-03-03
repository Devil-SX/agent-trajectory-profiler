/**
 * SessionMetadataSidebar component for displaying session metadata.
 *
 * Features:
 * - Fixed sidebar on right side of screen
 * - Displays session ID, creation time, duration
 * - Shows total message count
 * - Lists all models used in session
 * - Displays session status/state
 * - Clean typography and layout
 * - Responsive behavior on smaller screens
 */

import { useEffect, useState, useCallback } from 'react';
import { fetchSessionDetail } from '../api/sessions';
import type { Session, SessionMetadataDisplay } from '../types/session';
import { formatTokenCount } from '../utils/tokenFormat';
import './SessionMetadataSidebar.css';

interface SessionMetadataSidebarProps {
  sessionId: string | null;
}

export function SessionMetadataSidebar({ sessionId }: SessionMetadataSidebarProps) {
  const [metadata, setMetadata] = useState<SessionMetadataDisplay | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialLoading = loading && !metadata;
  const switchingLoading = loading && !!metadata;
  const blockingError = Boolean(error && !metadata);

  const formatDuration = useCallback((ms: number): string => {
    const seconds = Math.floor(ms / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (days > 0) {
      return `${days}d ${hours % 24}h`;
    }
    if (hours > 0) {
      return `${hours}h ${minutes % 60}m`;
    }
    if (minutes > 0) {
      return `${minutes}m ${seconds % 60}s`;
    }
    return `${seconds}s`;
  }, []);

  const computeSessionMetadata = useCallback((session: Session): SessionMetadataDisplay => {
    const { metadata, messages } = session;

    // Calculate duration
    const createdAt = new Date(metadata.created_at);
    const updatedAt = metadata.updated_at ? new Date(metadata.updated_at) : new Date();
    const durationMs = updatedAt.getTime() - createdAt.getTime();
    const duration = formatDuration(durationMs);

    // Extract unique models used
    const modelsUsed = new Set<string>();
    messages.forEach((msg) => {
      if (msg.message?.model) {
        modelsUsed.add(msg.message.model);
      }
    });

    // Determine session status
    const status: 'active' | 'completed' | 'error' = metadata.updated_at ? 'completed' : 'active';

    return {
      sessionId: metadata.session_id,
      createdAt: metadata.created_at,
      duration,
      totalMessages: metadata.total_messages,
      modelsUsed: Array.from(modelsUsed),
      status,
      gitBranch: metadata.git_branch,
      projectPath: metadata.project_path,
      version: metadata.version,
      totalTokens: metadata.total_tokens,
    };
  }, [formatDuration]);

  useEffect(() => {
    if (!sessionId) {
      setMetadata(null);
      return;
    }

    async function loadMetadata() {
      if (!sessionId) return;

      try {
        setLoading(true);
        setError(null);
        const data = await fetchSessionDetail(sessionId);
        const displayMetadata = computeSessionMetadata(data.session);
        setMetadata(displayMetadata);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load metadata');
      } finally {
        setLoading(false);
      }
    }

    loadMetadata();
  }, [sessionId, computeSessionMetadata]);

  const formatTimestamp = (timestamp: string): string => {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getStatusBadgeClass = (status: string): string => {
    switch (status) {
      case 'active':
        return 'status-active';
      case 'completed':
        return 'status-completed';
      case 'error':
        return 'status-error';
      default:
        return '';
    }
  };

  if (!sessionId) {
    return (
      <aside className="metadata-sidebar">
        <div className="sidebar-content empty">
          <p>Select a session to view metadata</p>
        </div>
      </aside>
    );
  }

  if (initialLoading) {
    return (
      <aside className="metadata-sidebar">
        <div className="sidebar-content loading">
          <div className="loading-spinner" role="status" aria-live="polite">
            <span>Loading metadata...</span>
            <div className="sidebar-loading-skeleton" aria-hidden="true">
              {Array.from({ length: 5 }, (_, index) => (
                <div key={index} className="sidebar-loading-skeleton-row" />
              ))}
            </div>
          </div>
        </div>
      </aside>
    );
  }

  if (blockingError) {
    return (
      <aside className="metadata-sidebar">
        <div className="sidebar-content error">
          <p className="error-text">{error}</p>
          <button
            type="button"
            className="sidebar-retry-button"
            onClick={() => {
              if (sessionId) {
                setLoading(true);
                setError(null);
                fetchSessionDetail(sessionId)
                  .then((data) => setMetadata(computeSessionMetadata(data.session)))
                  .catch((err) =>
                    setError(err instanceof Error ? err.message : 'Failed to load metadata')
                  )
                  .finally(() => setLoading(false));
              }
            }}
          >
            Retry
          </button>
        </div>
      </aside>
    );
  }

  if (!metadata) {
    return null;
  }

  return (
    <aside className="metadata-sidebar">
      <div className="sidebar-content">
        {(switchingLoading || error) && (
          <div className="sidebar-refresh-indicator" role="status" aria-live="polite">
            {switchingLoading ? 'Refreshing metadata...' : 'Showing cached metadata (refresh failed)'}
          </div>
        )}
        {switchingLoading && (
          <div className="sidebar-loading-overlay" role="status" aria-live="polite">
            <span>Switching session...</span>
          </div>
        )}
        <h2 className="sidebar-title">Session Metadata</h2>

        <div className="metadata-section">
          <h3 className="section-title">Session Info</h3>
          <div className="metadata-item">
            <span className="label">Session ID</span>
            <span className="value session-id">{metadata.sessionId}</span>
          </div>
          <div className="metadata-item">
            <span className="label">Status</span>
            <span className={`value status-badge ${getStatusBadgeClass(metadata.status)}`}>
              {metadata.status}
            </span>
          </div>
          <div className="metadata-item">
            <span className="label">Created</span>
            <span className="value">{formatTimestamp(metadata.createdAt)}</span>
          </div>
          <div className="metadata-item">
            <span className="label">Duration</span>
            <span className="value">{metadata.duration}</span>
          </div>
        </div>

        <div className="metadata-section">
          <h3 className="section-title">Statistics</h3>
          <div className="metadata-item">
            <span className="label">Total Messages</span>
            <span className="value metric">{metadata.totalMessages}</span>
          </div>
          <div className="metadata-item">
            <span className="label">Total Tokens</span>
            <span className="value metric" title={metadata.totalTokens.toLocaleString()}>
              {formatTokenCount(metadata.totalTokens)}
            </span>
          </div>
        </div>

        <div className="metadata-section">
          <h3 className="section-title">Models Used</h3>
          {metadata.modelsUsed.length > 0 ? (
            <ul className="models-list">
              {metadata.modelsUsed.map((model) => (
                <li key={model} className="model-item">
                  {model}
                </li>
              ))}
            </ul>
          ) : (
            <p className="no-data">No models recorded</p>
          )}
        </div>

        <div className="metadata-section">
          <h3 className="section-title">Project Info</h3>
          {metadata.gitBranch && (
            <div className="metadata-item">
              <span className="label">Git Branch</span>
              <span className="value git-branch">{metadata.gitBranch}</span>
            </div>
          )}
          <div className="metadata-item">
            <span className="label">Version</span>
            <span className="value">{metadata.version}</span>
          </div>
          <div className="metadata-item full-width">
            <span className="label">Project Path</span>
            <span className="value project-path">{metadata.projectPath}</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
