/**
 * SessionBrowser component for browsing Claude Code sessions.
 *
 * Features:
 * - SessionFilter component for composable multi-dimensional filtering
 * - SessionListView component for table-only session browsing
 * - Optional comparison picker mode for analytics view
 * - Handles URL parameter ?session= for initial selection
 * - Error and loading states
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import {
  useFrontendPreferencesQuery,
  useSessionsQuery,
  useUpdateFrontendPreferencesMutation,
} from '../hooks/useSessionsQuery';
import type { SessionSummary } from '../types/session';
import { SessionFilter } from './SessionFilter';
import { SessionListView } from './SessionListView';
import { useI18n } from '../i18n';
import {
  DEFAULT_SESSION_FILTERS,
  buildSessionQueryFilters,
  filterAndSortSessions,
  type SessionBrowserFilters,
} from '../utils/sessionFilters';
import './SessionBrowser.css';

interface SessionBrowserProps {
  onSessionChange?: (sessionId: string | null, session?: SessionSummary | null) => void;
  onComparisonSessionChange?: (sessionId: string | null) => void;
  selectedSessionId?: string | null;
  comparisonSessionId?: string | null;
  autoSelectFirst?: boolean;
  aggregationMode?: SessionAggregationMode;
  onAggregationModeChange?: (mode: SessionAggregationMode) => void;
}

type SessionAggregationMode = 'logical' | 'physical';

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
  aggregationMode: controlledAggregationMode,
  onAggregationModeChange,
}: SessionBrowserProps) {
  const { t, formatNumber } = useI18n();
  const [page] = useState(1);
  const [pageSize] = useState(200);
  const [filters, setFilters] = useState<SessionBrowserFilters>({ ...DEFAULT_SESSION_FILTERS });
  const filterHydrationRef = useRef(false);
  const skipNextFilterPersistRef = useRef(true);

  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    controlledSelectedSessionId
  );

  const [isPickingComparison, setIsPickingComparison] = useState(false);
  const [aggregationModeState, setAggregationModeState] = useState<SessionAggregationMode>('logical');
  const aggregationMode = controlledAggregationMode ?? aggregationModeState;

  const frontendPreferencesQuery = useFrontendPreferencesQuery();
  const updateFrontendPreferencesMutation = useUpdateFrontendPreferencesMutation();
  const serverQueryFilters = useMemo(
    () => buildSessionQueryFilters(filters),
    [filters]
  );

  const { data, isLoading, isFetching, error: queryError, refetch } = useSessionsQuery(
    page,
    pageSize,
    filters.start_date,
    filters.end_date,
    aggregationMode,
    serverQueryFilters,
  );

  const sessions: SessionSummary[] = data?.sessions ?? EMPTY_SESSIONS;
  const loading = isLoading && !data;
  const refreshing = isFetching && !!data;
  const error = queryError?.message || null;
  const blockingError = Boolean(error && !data);
  const nonBlockingError = Boolean(error && data);

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
    if (filterHydrationRef.current) {
      return;
    }
    if (frontendPreferencesQuery.data) {
      const hydrated = {
        ...DEFAULT_SESSION_FILTERS,
        ...(frontendPreferencesQuery.data.session_browser_filters || {}),
      };
      setFilters(hydrated);
      filterHydrationRef.current = true;
      return;
    }
    if (frontendPreferencesQuery.isError) {
      filterHydrationRef.current = true;
    }
  }, [frontendPreferencesQuery.data, frontendPreferencesQuery.isError]);

  useEffect(() => {
    if (!filterHydrationRef.current) {
      return;
    }
    if (skipNextFilterPersistRef.current) {
      skipNextFilterPersistRef.current = false;
      return;
    }

    const timer = window.setTimeout(() => {
      updateFrontendPreferencesMutation.mutate({
        session_browser_filters: filters,
      });
    }, 400);

    return () => window.clearTimeout(timer);
  }, [filters, updateFrontendPreferencesMutation]);

  useEffect(() => {
    if (controlledAggregationMode !== undefined) {
      setAggregationModeState(controlledAggregationMode);
    }
  }, [controlledAggregationMode]);

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
          toast.error(t('session.notFound', { values: { sessionId: sessionIdParam } }));
        }
      }

    if (!initialSessionId) {
      initialSessionId = sessions[0].session_id;
    }

    setActiveSessionId(initialSessionId);
    const initialSession = sessions.find((item) => item.session_id === initialSessionId) || null;
    onSessionChange?.(initialSessionId, initialSession);
    initRef.current = true;
  }, [autoSelectFirst, controlledSelectedSessionId, onSessionChange, sessions, t]);

  // Filter and sort sessions
  const filteredAndSortedSessions = useMemo(() => {
    return filterAndSortSessions(sessions, filters);
  }, [sessions, filters]);

  useEffect(() => {
    if (filteredAndSortedSessions.length === 0) {
      if (activeSessionId) {
        setActiveSessionId(null);
        if (autoSelectFirst) {
          onSessionChange?.(null, null);
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
        const nextSession =
          filteredAndSortedSessions.find((item) => item.session_id === nextSessionId) || null;
        onSessionChange?.(nextSessionId, nextSession);
        if (initRef.current) {
          toast(t('session.search.adjusted'));
        }
      } else {
        setActiveSessionId(null);
      }
    }
  }, [activeSessionId, autoSelectFirst, filteredAndSortedSessions, onSessionChange, t]);

  const handleSessionSelect = (sessionId: string) => {
    const showComparison = onComparisonSessionChange !== undefined;

    if (showComparison && isPickingComparison) {
      if (sessionId === activeSessionId) {
        toast.error(t('session.compare.chooseDifferent'));
        return;
      }

      onComparisonSessionChange?.(sessionId);
      setIsPickingComparison(false);
      toast.success(t('session.compare.setSuccess', { values: { sessionId: shortId(sessionId) } }));
      return;
    }

    setActiveSessionId(sessionId);
    const session = sessions.find((item) => item.session_id === sessionId) || null;
    onSessionChange?.(sessionId, session);
  };

  const showComparison = onComparisonSessionChange !== undefined;
  const handleAggregationModeChange = (next: SessionAggregationMode) => {
    if (controlledAggregationMode === undefined) {
      setAggregationModeState(next);
    }
    onAggregationModeChange?.(next);
  };

  const browserStateClass = loading
    ? 'loading'
    : blockingError
      ? 'error'
      : sessions.length === 0
        ? 'empty'
        : '';

  return (
    <div className={`session-browser ${browserStateClass}`.trim()}>
      <div className="session-browser-container">
        {loading && (
          <div className="loading-container" role="status" aria-live="polite">
            <div className="loading-indicator-row">
              <span className="loading-dot loading-dot--one" aria-hidden="true" />
              <span className="loading-dot loading-dot--two" aria-hidden="true" />
              <span className="loading-dot loading-dot--three" aria-hidden="true" />
              <span className="loading-label">{t('session.loadingInitial')}</span>
            </div>
            <p>{t('session.loadingHint')}</p>
            <div className="session-loading-skeleton" aria-hidden="true">
              {Array.from({ length: 6 }, (_, index) => (
                <div key={index} className="session-skeleton-row" />
              ))}
            </div>
          </div>
        )}

        {!loading && blockingError && (
          <div className="error-container">
            <p className="error-message">
              {t('session.errorPrefix')}
              : {error}
            </p>
            <button
              type="button"
              className="session-retry-button"
              onClick={() => {
                void refetch();
              }}
            >
              {t('session.retry')}
            </button>
          </div>
        )}

        {!loading && !blockingError && sessions.length === 0 && (
          <div className="empty-container">
            <p>{t('session.empty')}</p>
          </div>
        )}

        {!loading && !blockingError && sessions.length > 0 && (
          <>
            {(refreshing || nonBlockingError) && (
              <div className="session-refresh-indicator" role="status" aria-live="polite">
                <span className="session-refresh-pill">
                  {refreshing ? t('session.refreshing') : t('session.errorRecoverable')}
                </span>
              </div>
            )}
            <div className="session-browser-filter">
              <SessionFilter
                value={filters}
                onChange={setFilters}
              />
            </div>

            <div className="session-browser-list">
              <SessionListView
                sessions={filteredAndSortedSessions}
                selectedId={activeSessionId}
                onSelect={handleSessionSelect}
              />
            </div>

            <div className="session-browser-actions">
              <div className="session-browser-meta">
                <div className="session-view-toggle" role="group" aria-label={t('session.aggregationMode.aria')}>
                  <button
                    className={`session-view-toggle__button ${aggregationMode === 'logical' ? 'active' : ''}`}
                    type="button"
                    onClick={() => handleAggregationModeChange('logical')}
                    aria-pressed={aggregationMode === 'logical'}
                  >
                    {t('session.aggregationMode.logical')}
                  </button>
                  <button
                    className={`session-view-toggle__button ${aggregationMode === 'physical' ? 'active' : ''}`}
                    type="button"
                    onClick={() => handleAggregationModeChange('physical')}
                    aria-pressed={aggregationMode === 'physical'}
                  >
                    {t('session.aggregationMode.physical')}
                  </button>
                </div>
                <div className="session-count">
                  {t('session.countSummary', {
                    values: {
                      visible: formatNumber(filteredAndSortedSessions.length),
                      total: formatNumber(sessions.length),
                    },
                  })}
                </div>
              </div>

              {showComparison && (
                <div className="comparison-actions">
                  <button
                    className={`compare-button ${isPickingComparison ? 'compare-button--active' : ''}`}
                    type="button"
                    onClick={() => setIsPickingComparison((prev) => !prev)}
                  >
                    {isPickingComparison
                      ? t('session.compare.cancelPick')
                      : t('session.compare.pick')}
                  </button>

                  <button
                    className="compare-button compare-button--secondary"
                    type="button"
                    onClick={() => onComparisonSessionChange?.(null)}
                    disabled={!comparisonSessionId}
                  >
                    {t('session.compare.clear')}
                  </button>

                  <span className="comparison-state">
                    {t('session.compare.state')}
                    : {shortId(comparisonSessionId)}
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
