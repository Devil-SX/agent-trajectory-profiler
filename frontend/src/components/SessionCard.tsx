/**
 * SessionCard component displays a clickable session summary card with:
 * - Project name, relative time, token count
 * - Bottleneck badge with color coding
 * - Automation ratio and message count
 * - Git branch (if available)
 * - Selected state and hover effects
 */

import type { SessionSummary } from '../types/session';
import {
  formatAbsoluteTime,
  formatRelativeWithAbsolute,
  getProjectName,
  truncateMiddle,
} from '../utils/display';
import './SessionCard.css';

interface SessionCardProps {
  session: SessionSummary;
  isSelected?: boolean;
  onClick?: (id: string) => void;
}

const BOTTLENECK_COLORS: Record<string, string> = {
  Model: '#ef4444',
  Tool: '#f97316',
  User: '#22c55e',
};

function getDisplayName(
  projectName: string,
  gitBranch: string | null,
): string {
  const parts = [projectName];
  if (gitBranch) {
    parts.push(gitBranch);
  }
  return parts.join(' | ');
}

export function SessionCard({
  session,
  isSelected = false,
  onClick,
}: SessionCardProps) {
  const projectName = getProjectName(session.project_path);
  const updatedTime = session.updated_at || session.created_at;
  const relativeWithAbsolute = formatRelativeWithAbsolute(updatedTime);
  const absoluteTime = formatAbsoluteTime(updatedTime);
  const displayName = getDisplayName(projectName, session.git_branch);
  const bottleneckColor = session.bottleneck
    ? BOTTLENECK_COLORS[session.bottleneck] || '#6b7280'
    : '#6b7280';
  const automationRatioDisplay = session.automation_ratio
    ? `${session.automation_ratio.toFixed(1)}x`
    : 'N/A';
  const shortSessionId = truncateMiddle(session.session_id, 4, 3);

  return (
    <button
      type="button"
      className={`session-card ${isSelected ? 'session-card--selected' : ''}`}
      onClick={() => onClick?.(session.session_id)}
      aria-pressed={isSelected}
      aria-label={`Session ${projectName}, updated ${relativeWithAbsolute}`}
    >
      {/* Header with project and branch */}
      <div className="session-card__header">
        <h3 className="session-card__title" title={session.project_path}>
          {displayName}
        </h3>
      </div>
      <p className="session-card__time" title={absoluteTime}>
        Updated {relativeWithAbsolute}
      </p>

      {/* Bottleneck badge */}
      {session.bottleneck && (
        <div className="session-card__bottleneck">
          <div
            className="session-card__bottleneck-badge"
            style={{ borderColor: bottleneckColor, backgroundColor: bottleneckColor }}
          >
            <span className="session-card__bottleneck-text">{session.bottleneck}</span>
          </div>
        </div>
      )}

      {/* Main stats grid */}
      <div className="session-card__stats">
        <div className="session-card__stat-item">
          <span className="session-card__stat-label">Tokens</span>
          <span className="session-card__stat-value">
            {session.total_tokens.toLocaleString()}
          </span>
        </div>

        <div className="session-card__stat-item">
          <span className="session-card__stat-label">Automation</span>
          <span className="session-card__stat-value">{automationRatioDisplay}</span>
        </div>

        <div className="session-card__stat-item">
          <span className="session-card__stat-label">Messages</span>
          <span className="session-card__stat-value">{session.total_messages}</span>
        </div>
      </div>

      {/* Footer with session ID badge */}
      <div className="session-card__footer">
        <span className="session-card__session-id">
          <code>{shortSessionId}</code>
        </span>
      </div>
    </button>
  );
}
