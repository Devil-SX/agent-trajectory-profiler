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
import { SessionCard } from './SessionCard';
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

export function SessionListView({
  sessions,
  selectedId,
  onSelect,
  viewMode = 'cards',
}: SessionListViewProps) {
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

  // Empty state
  if (sessions.length === 0) {
    return (
      <div className="session-list-view" ref={containerRef}>
        <div className="session-list-empty">
          <p>No sessions found</p>
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
                <th>Session</th>
                <th>Ecosystem</th>
                <th>Project</th>
                <th>Updated</th>
                <th>Tokens</th>
                <th>Messages</th>
                <th>Bottleneck</th>
                <th>Automation</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => {
                const updated = session.updated_at || session.created_at;
                const automation = session.automation_ratio === null
                  ? '--'
                  : `${session.automation_ratio.toFixed(2)}x`;
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
                    <td title={session.session_id}>
                      <code>{session.session_id.slice(0, 12)}</code>
                    </td>
                    <td>{session.ecosystem}</td>
                    <td title={session.project_path}>{session.project_path}</td>
                    <td>{new Date(updated).toLocaleString()}</td>
                    <td>{session.total_tokens.toLocaleString()}</td>
                    <td>{session.total_messages.toLocaleString()}</td>
                    <td>{session.bottleneck ?? '--'}</td>
                    <td>{automation}</td>
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
