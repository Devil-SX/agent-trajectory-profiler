/**
 * SessionBrowser component for browsing Claude Code sessions.
 *
 * Features:
 * - SessionFilter component for search, sorting, and bottleneck filtering
 * - SessionListView component with virtual scrolling for efficient rendering
 * - Filtering logic (search query + bottleneck filter)
 * - Sorting logic (updated, created, tokens, duration, automation)
 * - Optional comparison picker mode for analytics view
 * - Handles URL parameter ?session= for initial selection
 * - Error and loading states
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import { useRunSyncMutation, useSessionsQuery, useSyncStatusQuery } from '../hooks/useSessionsQuery';
import type { SessionSummary } from '../types/session';
import {
  SessionFilter,
  type SortOption,
  type BottleneckFilter,
} from './SessionFilter';
import type { DateRange } from './DateRangePicker';
import { SessionListView } from './SessionListView';
import { SyncControl } from './SyncControl';
import './SessionBrowser.css';

interface SessionBrowserProps {
  onSessionChange?: (sessionId: string | null) => void;
  onComparisonSessionChange?: (sessionId: string | null) => void;
  selectedSessionId?: string | null;
  comparisonSessionId?: string | null;
  autoSelectFirst?: boolean;
}

type SessionViewMode = 'cards' | 'table';
const SESSION_VIEW_MODE_STORAGE_KEY = 'agent-vis:session-browser:view-mode';

const EMPTY_SESSIONS: SessionSummary[] = [];

function shortId(sessionId: string | null | undefined): string {
  if (!sessionId) return 'none';
  return sessionId.slice(0, 8);
}

export function SessionBrowser({
  onSessionChange,
  onComparisonSessionChange,
  selectedSessionId: controlledSelectedSessionId = null,
  comparisonSessionId,
  autoSelectFirst = true,
}: SessionBrowserProps) {
  const [page] = useState(1);
  const [pageSize] = useState(200);

  // Date range filter state
  const [dateRange, setDateRange] = useState<DateRange>({
    start_date: null,
    end_date: null,
  });

  const { data, isLoading, error: queryError } = useSessionsQuery(
    page,
    pageSize,
    dateRange.start_date,
    dateRange.end_date
  );
  const syncStatusQuery = useSyncStatusQuery();
  const runSyncMutation = useRunSyncMutation();

  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    controlledSelectedSessionId
  );

  const [isPickingComparison, setIsPickingComparison] = useState(false);
  const [viewMode, setViewMode] = useState<SessionViewMode>(() => {
    if (typeof window === 'undefined') {
      return 'table';
    }
    const stored = window.localStorage.getItem(SESSION_VIEW_MODE_STORAGE_KEY);
    if (stored === 'cards' || stored === 'table') {
      return stored;
    }
    return 'table';
  });

  // Filter and sort state
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [sortBy, setSortBy] = useState<SortOption>('updated');
  const [bottleneckFilter, setBottleneckFilter] = useState<BottleneckFilter>(
    'all'
  );

  const sessions: SessionSummary[] = data?.sessions ?? EMPTY_SESSIONS;
  const loading = isLoading && !data;
  const error = queryError?.message || null;

  const initRef = useRef(false);

  useEffect(() => {
    setActiveSessionId(controlledSelectedSessionId);
  }, [controlledSelectedSessionId]);

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(SESSION_VIEW_MODE_STORAGE_KEY, viewMode);
    }
  }, [viewMode]);

  // Initialize selection on first load
  useEffect(() => {
    if (!sessions.length || initRef.current) {
      return;
    }

    if (!autoSelectFirst) {
      if (controlledSelectedSessionId) {
        const sessionExists = sessions.some(
          (s) => s.session_id === controlledSelectedSessionId
        );
        if (sessionExists) {
          setActiveSessionId(controlledSelectedSessionId);
        }
      }
      initRef.current = true;
      return;
    }

    const urlParams = new URLSearchParams(window.location.search);
    const sessionIdParam = urlParams.get('session');

    let initialSessionId = controlledSelectedSessionId;

    if (sessionIdParam) {
      const sessionExists = sessions.some((s) => s.session_id === sessionIdParam);
      if (sessionExists) {
        initialSessionId = sessionIdParam;
      } else {
        toast.error(`Session not found: ${sessionIdParam}`);
      }
    }

    if (!initialSessionId) {
      initialSessionId = sessions[0].session_id;
    }

    setActiveSessionId(initialSessionId);
    onSessionChange?.(initialSessionId);
    initRef.current = true;
  }, [autoSelectFirst, controlledSelectedSessionId, onSessionChange, sessions]);

  // Filter and sort sessions
  const filteredAndSortedSessions = useMemo(() => {
    let filtered = sessions;

    if (searchQuery.trim()) {
      filtered = filtered.filter((s) =>
        s.project_path.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.session_id.toLowerCase().includes(searchQuery.toLowerCase())
      );
    }

    if (bottleneckFilter !== 'all') {
      filtered = filtered.filter(
        (s) => s.bottleneck?.toLowerCase() === bottleneckFilter.toLowerCase()
      );
    }

    return [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'updated':
          return (
            new Date(b.updated_at || b.created_at).getTime() -
            new Date(a.updated_at || a.created_at).getTime()
          );
        case 'created':
          return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
        case 'tokens':
          return b.total_tokens - a.total_tokens;
        case 'duration':
          return (b.duration_seconds || 0) - (a.duration_seconds || 0);
        case 'automation':
          return (b.automation_ratio || 0) - (a.automation_ratio || 0);
        default:
          return 0;
      }
    });
  }, [sessions, searchQuery, bottleneckFilter, sortBy]);

  useEffect(() => {
    if (filteredAndSortedSessions.length === 0) {
      if (activeSessionId) {
        setActiveSessionId(null);
        if (autoSelectFirst) {
          onSessionChange?.(null);
        }
      }
      return;
    }

    const activeStillVisible = filteredAndSortedSessions.some(
      (s) => s.session_id === activeSessionId
    );

    if (!activeStillVisible) {
      if (autoSelectFirst) {
        const nextSessionId = filteredAndSortedSessions[0].session_id;
        setActiveSessionId(nextSessionId);
        onSessionChange?.(nextSessionId);
        if (initRef.current) {
          toast('Selection adjusted to visible results after filtering.');
        }
      } else {
        setActiveSessionId(null);
      }
    }
  }, [activeSessionId, autoSelectFirst, filteredAndSortedSessions, onSessionChange]);

  const handleSessionSelect = (sessionId: string) => {
    const showComparison = onComparisonSessionChange !== undefined;

    if (showComparison && isPickingComparison) {
      if (sessionId === activeSessionId) {
        toast.error('Choose a different session for comparison.');
        return;
      }

      onComparisonSessionChange?.(sessionId);
      setIsPickingComparison(false);
      toast.success(`Comparison session set to ${shortId(sessionId)}.`);
      return;
    }

    setActiveSessionId(sessionId);
    onSessionChange?.(sessionId);
  };

  const showComparison = onComparisonSessionChange !== undefined;

  const handleRunSync = () => {
    runSyncMutation.mutate(
      { force: false },
      {
        onSuccess: (result) => {
          if (result.status === 'already_running') {
            toast('Sync is already running. Please wait for completion.');
            return;
          }
          toast.success(
            `Sync complete: parsed ${result.parsed}, skipped ${result.skipped}, errors ${result.errors}.`
          );
        },
        onError: (err) => {
          toast.error(`Failed to run sync: ${err.message}`);
        },
      }
    );
  };

  const browserStateClass = loading
    ? 'loading'
    : error
      ? 'error'
      : sessions.length === 0
        ? 'empty'
        : '';

  return (
    <div className={`session-browser ${browserStateClass}`.trim()}>
      <div className="session-browser-container">
        <SyncControl
          status={syncStatusQuery.data}
          isLoading={syncStatusQuery.isLoading}
          isSyncing={runSyncMutation.isPending}
          onRunSync={handleRunSync}
        />
        {loading && (
          <div className="loading-container">
            <p>Loading sessions...</p>
          </div>
        )}

        {!loading && error && (
          <div className="error-container">
            <p className="error-message">Error: {error}</p>
          </div>
        )}

        {!loading && !error && sessions.length === 0 && (
          <div className="empty-container">
            <p>No sessions available</p>
          </div>
        )}

        {!loading && !error && sessions.length > 0 && (
          <>
            <div className="session-browser-filter">
              <SessionFilter
                onSearchChange={setSearchQuery}
                onSortChange={setSortBy}
                onBottleneckFilterChange={setBottleneckFilter}
                onDateRangeChange={setDateRange}
                searchQuery={searchQuery}
                sortBy={sortBy}
                bottleneckFilter={bottleneckFilter}
                dateRange={dateRange}
              />
            </div>

            <div className="session-browser-list">
              <SessionListView
                sessions={filteredAndSortedSessions}
                selectedId={activeSessionId}
                onSelect={handleSessionSelect}
                viewMode={viewMode}
              />
            </div>

            <div className="session-browser-actions">
              <div className="session-browser-meta">
                <div className="session-view-toggle" role="group" aria-label="Session view mode">
                  <button
                    className={`session-view-toggle__button ${viewMode === 'cards' ? 'active' : ''}`}
                    type="button"
                    onClick={() => setViewMode('cards')}
                    aria-pressed={viewMode === 'cards'}
                  >
                    Card View
                  </button>
                  <button
                    className={`session-view-toggle__button ${viewMode === 'table' ? 'active' : ''}`}
                    type="button"
                    onClick={() => setViewMode('table')}
                    aria-pressed={viewMode === 'table'}
                  >
                    Table View
                  </button>
                </div>
                <div className="session-count">
                  {filteredAndSortedSessions.length} of {sessions.length} sessions
                </div>
              </div>

              {showComparison && (
                <div className="comparison-actions">
                  <button
                    className={`compare-button ${isPickingComparison ? 'compare-button--active' : ''}`}
                    type="button"
                    onClick={() => setIsPickingComparison((prev) => !prev)}
                  >
                    {isPickingComparison ? 'Cancel Compare Pick' : 'Pick Comparison Session'}
                  </button>

                  <button
                    className="compare-button compare-button--secondary"
                    type="button"
                    onClick={() => onComparisonSessionChange?.(null)}
                    disabled={!comparisonSessionId}
                  >
                    Clear Comparison
                  </button>

                  <span className="comparison-state">
                    Compare: {shortId(comparisonSessionId)}
                  </span>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
