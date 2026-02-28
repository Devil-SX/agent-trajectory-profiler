/**
 * SessionListView component displays a virtualized list of sessions with:
 * - Virtual scrolling (react-window) for handling 200+ sessions efficiently
 * - Optional compact table mode for dense scanning
 * - SessionCard rendering for each session
 * - Selected state management
 * - Empty state message
 */

import { useEffect, useRef, useState } from 'react';
import { List } from 'react-window';
import type { SessionSummary } from '../types/session';
import {
  getProjectName,
  truncateMiddle,
} from '../utils/display';
import { SessionCard } from './SessionCard';
import { useI18n } from '../i18n';
import './SessionListView.css';

interface SessionListViewProps {
  sessions: SessionSummary[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  viewMode?: 'cards' | 'table';
}

const ITEM_SIZE = 188; // SessionCard row height
const MIN_LIST_HEIGHT = 260;
const FALLBACK_LIST_HEIGHT = 520;

function normalizeEcosystem(ecosystem: string | null | undefined): 'codex' | 'claude' | 'other' {
  if (ecosystem === 'codex') {
    return 'codex';
  }
  if (ecosystem === 'claude_code') {
    return 'claude';
  }
  return 'other';
}

function ecosystemLabel(ecosystem: string | null | undefined, unknownLabel: string): string {
  if (ecosystem === 'codex') {
    return 'Codex';
  }
  if (ecosystem === 'claude_code') {
    return 'Claude Code';
  }
  return ecosystem || unknownLabel;
}

function normalizeBottleneck(value: string | null | undefined): 'model' | 'tool' | 'user' | 'unknown' {
  const normalized = (value || '').trim().toLowerCase();
  if (normalized === 'model') {
    return 'model';
  }
  if (normalized === 'tool') {
    return 'tool';
  }
  if (normalized === 'user') {
    return 'user';
  }
  return 'unknown';
}

function getAutomationBand(
  ratio: number | null | undefined
): 'low' | 'medium' | 'high' | 'unknown' {
  if (ratio === null || ratio === undefined) {
    return 'unknown';
  }
  if (ratio < 1) {
    return 'low';
  }
  if (ratio < 3) {
    return 'medium';
  }
  return 'high';
}

export function SessionListView({
  sessions,
  selectedId,
  onSelect,
  viewMode = 'cards',
}: SessionListViewProps) {
  const { t, formatDateTime, formatNumber, formatRelativeWithAbsolute } = useI18n();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [listHeight, setListHeight] = useState<number>(FALLBACK_LIST_HEIGHT);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }

    const container = containerRef.current;
    const updateHeight = () => {
      const next = Math.max(container.clientHeight, MIN_LIST_HEIGHT);
      setListHeight(next);
    };

    updateHeight();
    const observer = new ResizeObserver(() => updateHeight());
    observer.observe(container);

    return () => observer.disconnect();
  }, []);

  const handleCopySessionId = async (
    event: React.MouseEvent<HTMLButtonElement>,
    sessionId: string
  ) => {
    event.stopPropagation();
    try {
      await navigator.clipboard.writeText(sessionId);
    } catch (error) {
      console.error('Failed to copy session ID', error);
    }
  };

  // Empty state
  if (sessions.length === 0) {
    return (
      <div className="session-list-view" ref={containerRef}>
        <div className="session-list-empty">
          <p>{t('table.noSessionsFound')}</p>
        </div>
      </div>
    );
  }

  if (viewMode === 'table') {
    return (
      <div className="session-list-view session-list-view--table" ref={containerRef}>
        <div className="session-table-container">
          <table className="session-table">
            <thead>
              <tr>
                <th>{t('table.project')}</th>
                <th>{t('table.updated')}</th>
                <th>{t('table.sessionId')}</th>
                <th>{t('table.ecosystem')}</th>
                <th>{t('table.tokens')}</th>
                <th>{t('table.messages')}</th>
                <th>{t('table.bottleneck')}</th>
                <th>{t('table.automation')}</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => {
                const updated = session.updated_at || session.created_at;
                const automation = session.automation_ratio === null
                  ? '--'
                  : `${session.automation_ratio.toFixed(2)}x`;
                const projectName = getProjectName(session.project_path);
                const updatedLabel = formatRelativeWithAbsolute(updated);
                const updatedAbsolute = formatDateTime(updated, {
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                });
                return (
                  <tr
                    key={session.session_id}
                    data-session-id={session.session_id}
                    className={session.session_id === selectedId ? 'selected' : ''}
                    onClick={() => onSelect(session.session_id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        onSelect(session.session_id);
                      }
                    }}
                    tabIndex={0}
                  >
                    <td className="session-table__project" title={session.project_path}>
                      {projectName}
                    </td>
                    <td className="session-table__updated" title={updatedAbsolute}>
                      {updatedLabel}
                    </td>
                    <td className="session-table__id" title={session.session_id}>
                      <code>{truncateMiddle(session.session_id, 6, 4)}</code>
                      <button
                        type="button"
                        className="session-table__copy-id"
                        onClick={(event) => {
                          void handleCopySessionId(event, session.session_id);
                        }}
                        onKeyDown={(event) => event.stopPropagation()}
                        aria-label={t('table.copySessionId', { values: { id: session.session_id } })}
                      >
                        {t('table.copy')}
                      </button>
                    </td>
                    <td>
                      <span
                        className={`session-tag session-tag--ecosystem-${normalizeEcosystem(session.ecosystem)}`}
                      >
                        {ecosystemLabel(session.ecosystem, t('table.unknown'))}
                      </span>
                    </td>
                    <td>{formatNumber(session.total_tokens)}</td>
                    <td>{formatNumber(session.total_messages)}</td>
                    <td>
                      <span
                        className={`session-tag session-tag--bottleneck-${normalizeBottleneck(session.bottleneck)}`}
                      >
                        {session.bottleneck ?? t('table.unknown')}
                      </span>
                    </td>
                    <td>
                      <span
                        className={`session-tag session-tag--automation-${getAutomationBand(session.automation_ratio)}`}
                      >
                        {automation}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Row component for virtualized list
  const RowComponent = ({
    index,
    style,
  }: {
    index: number;
    style: React.CSSProperties;
  }) => {
    const session = sessions[index];
    return (
      <div style={style} className="session-list-item">
        <SessionCard
          session={session}
          isSelected={session.session_id === selectedId}
          onClick={onSelect}
        />
      </div>
    );
  };

  return (
    <div className="session-list-view" ref={containerRef}>
      <List<Record<string, never>>
        rowComponent={RowComponent}
        rowCount={sessions.length}
        rowHeight={ITEM_SIZE}
        rowProps={{} as Record<string, never>}
        style={{ height: listHeight, width: '100%' }}
      />
    </div>
  );
}
