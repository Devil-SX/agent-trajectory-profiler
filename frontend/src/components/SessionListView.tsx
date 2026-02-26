/**
 * SessionListView component displays a virtualized list of sessions with:
 * - Virtual scrolling (react-window) for handling 200+ sessions efficiently
 * - SessionCard rendering for each session
 * - Selected state management
 * - Empty state message
 */

import { List } from 'react-window';
import type { SessionSummary } from '../types/session';
import { SessionCard } from './SessionCard';
import './SessionListView.css';

interface SessionListViewProps {
  sessions: SessionSummary[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
}

const ITEM_SIZE = 180; // SessionCard height in pixels
const LIST_HEIGHT = 600; // Virtual list container height

export function SessionListView({
  sessions,
  selectedId,
  onSelect,
}: SessionListViewProps) {
  // Empty state
  if (sessions.length === 0) {
    return (
      <div className="session-list-view">
        <div className="session-list-empty">
          <p>No sessions found</p>
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
    <div className="session-list-view">
      <List<Record<string, never>>
        rowComponent={RowComponent}
        rowCount={sessions.length}
        rowHeight={ITEM_SIZE}
        rowProps={{} as Record<string, never>}
        style={{ height: LIST_HEIGHT, width: '100%' }}
      />
    </div>
  );
}
