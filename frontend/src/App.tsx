import { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { Toaster } from 'react-hot-toast';
import toast from 'react-hot-toast';
import './App.css';
import { SessionBrowser } from './components/SessionBrowser';
import { SyncControl } from './components/SyncControl';
import { useI18n } from './i18n';
import type { Locale } from './i18n';
import {
  useFrontendPreferencesQuery,
  useRunSyncMutation,
  useSyncStatusQuery,
  useUpdateFrontendPreferencesMutation,
} from './hooks/useSessionsQuery';
import type {
  DensityMode,
  FrontendPreferencesUpdate,
  SessionSummary,
  SessionAggregationMode,
  ThemeMode,
} from './types/session';

// Lazy load heavy components for code splitting
const MessageTimeline = lazy(() => import('./components/MessageTimeline').then(m => ({ default: m.MessageTimeline })));
const SessionMetadataSidebar = lazy(() => import('./components/SessionMetadataSidebar').then(m => ({ default: m.SessionMetadataSidebar })));
const StatisticsDashboard = lazy(() => import('./components/StatisticsDashboard').then(m => ({ default: m.StatisticsDashboard })));
const AdvancedAnalytics = lazy(() => import('./components/AdvancedAnalytics').then(m => ({ default: m.AdvancedAnalytics })));

type PrimaryView = 'session-detail' | 'cross-session';
type SessionDetailTab = 'timeline' | 'statistics';
type ResolvedTheme = 'light' | 'dark';

interface RouteState {
  view: PrimaryView;
  sessionId: string | null;
  tab: SessionDetailTab;
}

const LEGACY_LOCALE_STORAGE_KEY = 'agent-vis:locale';
const LEGACY_THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';
const LEGACY_DENSITY_MODE_STORAGE_KEY = 'agent-vis:density-mode';
const LEGACY_SESSION_VIEW_MODE_STORAGE_KEY = 'agent-vis:session-browser:view-mode';
const LEGACY_SESSION_AGGREGATION_MODE_STORAGE_KEY = 'agent-vis:session-browser:aggregation-mode';

function readSystemThemePreference(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

interface LegacyPreferences {
  locale?: Locale;
  theme_mode?: ThemeMode;
  density_mode?: DensityMode;
  legacy_session_view_mode?: 'cards' | 'table';
  session_aggregation_mode?: SessionAggregationMode;
}

function readLegacyPreferences(): LegacyPreferences {
  if (typeof window === 'undefined') {
    return {};
  }

  const locale = window.localStorage.getItem(LEGACY_LOCALE_STORAGE_KEY);
  const themeMode = window.localStorage.getItem(LEGACY_THEME_MODE_STORAGE_KEY);
  const densityMode = window.localStorage.getItem(LEGACY_DENSITY_MODE_STORAGE_KEY);
  const sessionViewMode = window.localStorage.getItem(LEGACY_SESSION_VIEW_MODE_STORAGE_KEY);
  const sessionAggregationMode = window.localStorage.getItem(
    LEGACY_SESSION_AGGREGATION_MODE_STORAGE_KEY
  );

  return {
    locale: locale === 'en' || locale === 'zh-CN' ? locale : undefined,
    theme_mode:
      themeMode === 'system' || themeMode === 'light' || themeMode === 'dark'
        ? themeMode
        : undefined,
    density_mode:
      densityMode === 'comfortable' || densityMode === 'compact'
        ? densityMode
        : undefined,
    legacy_session_view_mode:
      sessionViewMode === 'cards' || sessionViewMode === 'table'
        ? sessionViewMode
        : undefined,
    session_aggregation_mode:
      sessionAggregationMode === 'logical' || sessionAggregationMode === 'physical'
        ? sessionAggregationMode
        : undefined,
  };
}

function clearLegacyPreferenceKeys(): void {
  if (typeof window === 'undefined') {
    return;
  }
  [
    LEGACY_LOCALE_STORAGE_KEY,
    LEGACY_THEME_MODE_STORAGE_KEY,
    LEGACY_DENSITY_MODE_STORAGE_KEY,
    LEGACY_SESSION_VIEW_MODE_STORAGE_KEY,
    LEGACY_SESSION_AGGREGATION_MODE_STORAGE_KEY,
  ].forEach((key) => window.localStorage.removeItem(key));
}

function normalizeDetailTab(value: string | null): SessionDetailTab {
  if (value === 'statistics') {
    return 'statistics';
  }
  return 'timeline';
}

function readRouteState(): RouteState {
  if (typeof window === 'undefined') {
    return {
      view: 'cross-session',
      sessionId: null,
      tab: 'timeline',
    };
  }

  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get('session');
  const tab = normalizeDetailTab(params.get('tab'));

  if (sessionId) {
    return {
      view: 'session-detail',
      sessionId,
      tab,
    };
  }

  return {
    view: 'cross-session',
    sessionId: null,
    tab,
  };
}

function buildRouteUrl(route: RouteState): string {
  if (typeof window === 'undefined') {
    return '/';
  }

  const params = new URLSearchParams();

  if (route.view === 'session-detail' && route.sessionId) {
    params.set('session', route.sessionId);
    if (route.tab !== 'timeline') {
      params.set('tab', route.tab);
    }
  } else {
    params.set('view', 'overview');
  }

  const query = params.toString();
  return query ? `${window.location.pathname}?${query}` : window.location.pathname;
}

function App() {
  const { locale, setLocale, t } = useI18n();
  const preferencesQuery = useFrontendPreferencesQuery();
  const syncStatusQuery = useSyncStatusQuery();
  const runSyncMutation = useRunSyncMutation();
  const updatePreferencesMutation = useUpdateFrontendPreferencesMutation();
  const hasHydratedPreferencesRef = useRef(false);
  const initialRoute = readRouteState();
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(initialRoute.sessionId);
  const [selectedSessionEcosystem, setSelectedSessionEcosystem] = useState<string | null>(null);
  const [primaryView, setPrimaryView] = useState<PrimaryView>(initialRoute.view);
  const [sessionDetailTab, setSessionDetailTab] = useState<SessionDetailTab>(initialRoute.tab);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>('system');
  const [densityMode, setDensityMode] = useState<DensityMode>('comfortable');
  const [sessionAggregationMode, setSessionAggregationMode] =
    useState<SessionAggregationMode>('logical');
  const [systemPrefersDark, setSystemPrefersDark] = useState(readSystemThemePreference);

  const resolvedTheme: ResolvedTheme =
    themeMode === 'system' ? (systemPrefersDark ? 'dark' : 'light') : themeMode;

  const persistPreferencesPatch = (patch: FrontendPreferencesUpdate): void => {
    updatePreferencesMutation.mutate(patch, {
      onSuccess: (saved) => {
        setLocale(saved.locale);
        setThemeMode(saved.theme_mode);
        setDensityMode(saved.density_mode);
        setSessionAggregationMode(saved.session_aggregation_mode);
      },
    });
  };

  const handleRunSync = () => {
    runSyncMutation.mutate(
      { force: false },
      {
        onSuccess: (result) => {
          if (result.status === 'already_running') {
            toast(t('session.sync.alreadyRunning'));
            return;
          }
          toast.success(
            t('session.sync.success', {
              values: {
                parsed: result.parsed,
                skipped: result.skipped,
                errors: result.errors,
              },
            })
          );
        },
        onError: (err) => {
          toast.error(t('session.sync.failed', { values: { message: err.message } }));
        },
      }
    );
  };

  const applyRouteState = (next: RouteState, mode: 'push' | 'replace' = 'push') => {
    const shouldResetScroll =
      primaryView !== next.view || selectedSessionId !== next.sessionId;

    setPrimaryView(next.view);
    setSelectedSessionId(next.sessionId);
    setSessionDetailTab(next.tab);

    if (next.view !== 'session-detail' || next.tab !== 'timeline') {
      setIsMobileSidebarOpen(false);
    }

    if (typeof window !== 'undefined') {
      const nextUrl = buildRouteUrl(next);
      if (mode === 'replace') {
        window.history.replaceState(null, '', nextUrl);
      } else {
        window.history.pushState(null, '', nextUrl);
      }

      if (shouldResetScroll) {
        window.scrollTo({ top: 0, left: 0, behavior: 'auto' });
      }
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }

    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const handleChange = (event: MediaQueryListEvent) => {
      setSystemPrefersDark(event.matches);
    };

    media.addEventListener('change', handleChange);

    return () => media.removeEventListener('change', handleChange);
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
  }, [resolvedTheme]);

  useEffect(() => {
    document.documentElement.dataset.density = densityMode;
  }, [densityMode]);

  useEffect(() => {
    if (!preferencesQuery.data || hasHydratedPreferencesRef.current) {
      return;
    }

    const apply = (next: {
      locale: Locale;
      theme_mode: ThemeMode;
      density_mode: DensityMode;
      session_aggregation_mode: SessionAggregationMode;
    }) => {
      setLocale(next.locale);
      setThemeMode(next.theme_mode);
      setDensityMode(next.density_mode);
      setSessionAggregationMode(next.session_aggregation_mode);
    };

    const server = preferencesQuery.data;
    const legacy = readLegacyPreferences();
    const hasLegacy = Object.values(legacy).some((value) => value !== undefined);

    if (server.updated_at === null && hasLegacy) {
      const patch: FrontendPreferencesUpdate = {};
      if (legacy.locale) patch.locale = legacy.locale;
      if (legacy.theme_mode) patch.theme_mode = legacy.theme_mode;
      if (legacy.density_mode) patch.density_mode = legacy.density_mode;
      if (legacy.session_aggregation_mode) {
        patch.session_aggregation_mode = legacy.session_aggregation_mode;
      }

      updatePreferencesMutation.mutate(patch, {
        onSuccess: (saved) => {
          apply(saved);
          clearLegacyPreferenceKeys();
          hasHydratedPreferencesRef.current = true;
        },
        onError: () => {
          apply({
            locale: patch.locale ?? server.locale,
            theme_mode: patch.theme_mode ?? server.theme_mode,
            density_mode: patch.density_mode ?? server.density_mode,
            session_aggregation_mode:
              patch.session_aggregation_mode ?? server.session_aggregation_mode,
          });
          clearLegacyPreferenceKeys();
          hasHydratedPreferencesRef.current = true;
        },
      });
      return;
    }

    apply(server);
    hasHydratedPreferencesRef.current = true;
  }, [preferencesQuery.data, setLocale, updatePreferencesMutation]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }

    const normalized = readRouteState();
    const normalizedUrl = buildRouteUrl(normalized);
    const currentUrl = `${window.location.pathname}${window.location.search}`;
    if (normalizedUrl !== currentUrl) {
      window.history.replaceState(null, '', normalizedUrl);
    }

    const handlePopState = () => {
      const next = readRouteState();
      setPrimaryView(next.view);
      setSelectedSessionId(next.sessionId);
      setSessionDetailTab(next.tab);
      setIsMobileSidebarOpen(false);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);

    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  const handleSessionOpenFromOverview = (
    sessionId: string | null,
    session?: SessionSummary | null
  ) => {
    if (!sessionId) {
      return;
    }

    setSelectedSessionEcosystem(session?.ecosystem || null);
    applyRouteState({
      view: 'session-detail',
      sessionId,
      tab: 'timeline',
    });
  };

  const handlePrimaryViewChange = (view: PrimaryView) => {
    if (view === 'cross-session') {
      applyRouteState(
        {
          view: 'cross-session',
          sessionId: selectedSessionId,
          tab: sessionDetailTab,
        },
      );
      return;
    }

    if (selectedSessionId) {
      applyRouteState({
        view: 'session-detail',
        sessionId: selectedSessionId,
        tab: sessionDetailTab,
      });
    }
  };

  const handleSessionDetailTabChange = (tab: SessionDetailTab) => {
    setSessionDetailTab(tab);
    if (tab !== 'timeline') {
      setIsMobileSidebarOpen(false);
    }

    if (primaryView === 'session-detail' && selectedSessionId && typeof window !== 'undefined') {
      const url = buildRouteUrl({
        view: 'session-detail',
        sessionId: selectedSessionId,
        tab,
      });
      window.history.replaceState(null, '', url);
    }
  };

  const handleBackToOverview = () => {
    applyRouteState({
      view: 'cross-session',
      sessionId: selectedSessionId,
      tab: sessionDetailTab,
    });
  };

  const showSessionDetail = primaryView === 'session-detail';
  const showTimeline = showSessionDetail && sessionDetailTab === 'timeline';
  const showStatistics = showSessionDetail && sessionDetailTab === 'statistics';
  const showCrossSession = primaryView === 'cross-session';

  return (
    <div className="app">
      <Toaster
        position="top-right"
        toastOptions={{
          duration: 4000,
          style: {
            background: 'var(--color-surface)',
            color: 'var(--color-text-primary)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-medium)',
          },
          success: {
            duration: 3000,
            iconTheme: {
              primary: '#16a34a',
              secondary: '#ffffff',
            },
          },
          error: {
            duration: 5000,
            iconTheme: {
              primary: '#dc2626',
              secondary: '#ffffff',
            },
          },
        }}
      />
      <header>
        <h1>{t('header.title')}</h1>
        <div className="header-controls" role="group" aria-label={t('header.group.display')}>
          <div className="header-control-group">
            <label htmlFor="language-mode-select">{t('language.label')}</label>
            <select
              id="language-mode-select"
              value={locale}
              onChange={(event) => {
                const next = event.target.value as Locale;
                setLocale(next);
                persistPreferencesPatch({ locale: next });
              }}
              aria-label={t('language.label')}
            >
              <option value="en">{t('language.english')}</option>
              <option value="zh-CN">{t('language.chinese')}</option>
            </select>
          </div>
          <div className="header-control-group">
            <label htmlFor="theme-mode-select">{t('theme.label')}</label>
            <select
              id="theme-mode-select"
              value={themeMode}
              onChange={(event) => {
                const next = event.target.value as ThemeMode;
                setThemeMode(next);
                persistPreferencesPatch({ theme_mode: next });
              }}
              aria-label={t('theme.label')}
            >
              <option value="system">{t('theme.system')}</option>
              <option value="light">{t('theme.light')}</option>
              <option value="dark">{t('theme.dark')}</option>
            </select>
          </div>
          <div className="header-control-group">
            <label htmlFor="density-mode-select">{t('density.label')}</label>
            <select
              id="density-mode-select"
              value={densityMode}
              onChange={(event) => {
                const next = event.target.value as DensityMode;
                setDensityMode(next);
                persistPreferencesPatch({ density_mode: next });
              }}
              aria-label={t('density.label')}
            >
              <option value="comfortable">{t('density.comfortable')}</option>
              <option value="compact">{t('density.compact')}</option>
            </select>
          </div>
        </div>
      </header>
      <main>
        <div className="global-sync-strip">
          <SyncControl
            status={syncStatusQuery.data}
            isLoading={syncStatusQuery.isLoading}
            isSyncing={runSyncMutation.isPending}
            onRunSync={handleRunSync}
            compact
          />
        </div>
        <div className="view-tabs view-tabs--primary">
          <button
            className={`tab-button ${showCrossSession ? 'active' : ''}`}
            onClick={() => handlePrimaryViewChange('cross-session')}
          >
            {t('tabs.crossSession')}
          </button>
          <button
            className={`tab-button ${showSessionDetail ? 'active' : ''}`}
            onClick={() => handlePrimaryViewChange('session-detail')}
            disabled={!selectedSessionId}
          >
            {t('tabs.sessionDetail')}
          </button>
        </div>

        {showCrossSession && (
          <div className="main-content main-content--overview">
            <Suspense fallback={<div className="loading-spinner">{t('loading.default')}</div>}>
              <div className="session-content overview-analytics-block">
                <AdvancedAnalytics sessionId={null} />
              </div>
            </Suspense>

            <div className="overview-sessions-block">
              <SessionBrowser
                onSessionChange={handleSessionOpenFromOverview}
                selectedSessionId={selectedSessionId}
                autoSelectFirst={false}
                aggregationMode={sessionAggregationMode}
                onAggregationModeChange={(next) => {
                  setSessionAggregationMode(next);
                  persistPreferencesPatch({ session_aggregation_mode: next });
                }}
              />
            </div>
          </div>
        )}

        {showSessionDetail && (
          <>
            <div className="detail-toolbar">
              <button
                type="button"
                className="detail-back-button"
                onClick={handleBackToOverview}
              >
                {t('session.backToOverview')}
              </button>
              {selectedSessionId && (
                <p className="detail-session-caption">
                  {t('session.label')}
                  : <code>{selectedSessionId}</code>
                </p>
              )}
            </div>

            <div className="view-tabs view-tabs--secondary">
              <button
                className={`tab-button ${sessionDetailTab === 'timeline' ? 'active' : ''}`}
                onClick={() => handleSessionDetailTabChange('timeline')}
              >
                {t('tabs.timeline')}
              </button>
              <button
                className={`tab-button ${sessionDetailTab === 'statistics' ? 'active' : ''}`}
                onClick={() => handleSessionDetailTabChange('statistics')}
              >
                {t('tabs.statistics')}
              </button>
              {isMobile && showTimeline && selectedSessionId && (
                <button
                  className="tab-button mobile-sidebar-toggle"
                  onClick={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
                  aria-label="Toggle sidebar"
                >
                  {isMobileSidebarOpen
                    ? `✕ ${t('session.sidebar.close')}`
                    : `☰ ${t('session.sidebar.info')}`}
                </button>
              )}
            </div>

            <div className="main-content">
              {selectedSessionId ? (
                <Suspense fallback={<div className="loading-spinner">{t('loading.default')}</div>}>
                  {showTimeline && (
                    <div className="session-content">
                      <MessageTimeline sessionId={selectedSessionId} autoScrollToBottom={false} />
                    </div>
                  )}
                  {showStatistics && (
                    <div className="session-content">
                      <StatisticsDashboard
                        sessionId={selectedSessionId}
                        ecosystem={selectedSessionEcosystem}
                      />
                    </div>
                  )}
                  {showTimeline && (
                    <div className={`sidebar-container ${isMobileSidebarOpen ? 'mobile-open' : ''}`}>
                      {isMobile && isMobileSidebarOpen && (
                        <div
                          className="sidebar-overlay"
                          onClick={() => setIsMobileSidebarOpen(false)}
                          aria-hidden="true"
                        />
                      )}
                      <SessionMetadataSidebar sessionId={selectedSessionId} />
                    </div>
                  )}
                </Suspense>
              ) : (
                <div className="no-session">
                  <div>
                    <p>{t('session.noSelection')}</p>
                    <button type="button" onClick={handleBackToOverview}>
                      {t('session.returnToOverview')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
