/**
 * SessionBrowser component for browsing Claude Code sessions.
 *
 * Refactored from SessionSelector to replace dropdown UI with card-list browsing.
 * Features:
 * - SessionFilter component for search, sorting, and bottleneck filtering
 * - SessionListView component with virtual scrolling for efficient rendering
 * - Filtering logic (search query + bottleneck filter)
 * - Sorting logic (5 options: updated, created, tokens, duration, automation)
 * - Compare button (disabled for Phase 3 preparation)
 * - Preserves existing props interface for backward compatibility
 * - Handles URL parameter ?session= for initial selection
 * - Error and loading states
 */

import { useEffect, useState, useRef, useMemo } from 'react';
import toast from 'react-hot-toast';
import { useSessionsQuery } from '../hooks/useSessionsQuery';
import type { SessionSummary } from '../types/session';
import {
  SessionFilter,
  type SortOption,
  type BottleneckFilter,
} from './SessionFilter';
import type { DateRange } from './DateRangePicker';
import { SessionListView } from './SessionListView';
import './SessionBrowser.css';

interface SessionBrowserProps {
  onSessionChange?: (sessionId: string | null) => void;
  onComparisonSessionChange?: (sessionId: string | null) => void;
  selectedSessionId?: string | null;
  comparisonSessionId?: string | null;
}

export function SessionBrowser({
  onSessionChange,
  onComparisonSessionChange,
}: SessionBrowserProps) {
  const [page] = useState(1);
  const [pageSize] = useState(200); // Fetch more sessions for list

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

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  // Filter and sort state
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [sortBy, setSortBy] = useState<SortOption>('updated');
  const [bottleneckFilter, setBottleneckFilter] = useState<BottleneckFilter>(
    'all'
  );

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

  // Filter and sort sessions
  const filteredAndSortedSessions = useMemo(() => {
    let filtered = sessions;

    // Apply search filter
    if (searchQuery.trim()) {
      filtered = filtered.filter((s) =>
        s.project_path.toLowerCase().includes(searchQuery.toLowerCase()) ||
        s.session_id.toLowerCase().includes(searchQuery.toLowerCase())
      );
    }

    // Apply bottleneck filter
    if (bottleneckFilter !== 'all') {
      filtered = filtered.filter(
        (s) =>
          s.bottleneck?.toLowerCase() === bottleneckFilter.toLowerCase()
      );
    }

    // Apply sorting
    const sorted = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case 'updated':
          return (
            new Date(b.updated_at || b.created_at).getTime() -
            new Date(a.updated_at || a.created_at).getTime()
          );
        case 'created':
          return (
            new Date(b.created_at).getTime() -
            new Date(a.created_at).getTime()
          );
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

    return sorted;
  }, [sessions, searchQuery, bottleneckFilter, sortBy]);

  const handleSessionSelect = (sessionId: string) => {
    setSelectedSessionId(sessionId);
    onSessionChange?.(sessionId);
  };



  const showComparison = onComparisonSessionChange !== undefined;

  // Loading state
  if (loading) {
    return (
      <div className="session-browser loading">
        <div className="loading-container">
          <p>Loading sessions...</p>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="session-browser error">
        <div className="error-container">
          <p className="error-message">Error: {error}</p>
        </div>
      </div>
    );
  }

  // Empty state
  if (sessions.length === 0) {
    return (
      <div className="session-browser empty">
        <div className="empty-container">
          <p>No sessions available</p>
        </div>
      </div>
    );
  }

  return (
    <div className="session-browser">
      <div className="session-browser-container">
        {/* Filter section */}
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

        {/* List section */}
        <div className="session-browser-list">
          <SessionListView
            sessions={filteredAndSortedSessions}
            selectedId={selectedSessionId}
            onSelect={handleSessionSelect}
          />
        </div>

        {/* Action buttons section */}
        <div className="session-browser-actions">
          <div className="session-count">
            {filteredAndSortedSessions.length} of {sessions.length} sessions
          </div>
          {showComparison && (
            <button
              className="compare-button"
              disabled
              title="Comparison feature coming in Phase 3"
            >
              Compare Sessions
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
