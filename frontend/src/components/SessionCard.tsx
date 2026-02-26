/**
 * SessionCard component displays a clickable session summary card with:
 * - Project name, relative time, token count
 * - Bottleneck badge with color coding
 * - Automation ratio and message count
 * - Git branch (if available)
 * - Selected state and hover effects
 */

import type { SessionSummary } from '../types/session';
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

function getRelativeTime(timestamp: string): string {
  const now = new Date();
  const past = new Date(timestamp);
  const diffMs = now.getTime() - past.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return past.toLocaleDateString();
}

function getProjectName(projectPath: string): string {
  const segments = projectPath.split('/').filter(Boolean);
  return segments[segments.length - 1] || projectPath;
}

function getDisplayName(
  projectName: string,
  gitBranch: string | null,
  relativeTime: string,
): string {
  const parts = [projectName];
  if (gitBranch) parts.push(gitBranch);
  parts.push(relativeTime);
  return parts.join(' \u2022 ');
}

export function SessionCard({
  session,
  isSelected = false,
  onClick,
}: SessionCardProps) {
  const projectName = getProjectName(session.project_path);
  const relativeTime = getRelativeTime(session.updated_at || session.created_at);
  const displayName = getDisplayName(projectName, session.git_branch, relativeTime);
  const bottleneckColor = session.bottleneck
    ? BOTTLENECK_COLORS[session.bottleneck] || '#6b7280'
    : '#6b7280';
  const automationRatioDisplay = session.automation_ratio
    ? `${session.automation_ratio.toFixed(1)}x`
    : 'N/A';
  const shortSessionId = session.session_id.slice(0, 8);

  return (
    <div
      className={`session-card ${isSelected ? 'session-card--selected' : ''}`}
      onClick={() => onClick?.(session.session_id)}
    >
      {/* Header with project-branch-time display */}
      <div className="session-card__header">
        <h3 className="session-card__title" title={session.project_path}>
          {displayName}
        </h3>
      </div>

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
    </div>
  );
}
