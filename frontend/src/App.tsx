import { useState, useEffect, lazy, Suspense } from 'react';
import { Toaster } from 'react-hot-toast';
import './App.css';
import { SessionBrowser } from './components/SessionBrowser';

// Lazy load heavy components for code splitting
const MessageTimeline = lazy(() => import('./components/MessageTimeline').then(m => ({ default: m.MessageTimeline })));
const SessionMetadataSidebar = lazy(() => import('./components/SessionMetadataSidebar').then(m => ({ default: m.SessionMetadataSidebar })));
const StatisticsDashboard = lazy(() => import('./components/StatisticsDashboard').then(m => ({ default: m.StatisticsDashboard })));
const AdvancedAnalytics = lazy(() => import('./components/AdvancedAnalytics').then(m => ({ default: m.AdvancedAnalytics })));

type PrimaryView = 'session-detail' | 'cross-session';
type SessionDetailTab = 'timeline' | 'statistics';
type ThemeMode = 'system' | 'light' | 'dark';
type ResolvedTheme = 'light' | 'dark';
type DensityMode = 'comfortable' | 'compact';

interface RouteState {
  view: PrimaryView;
  sessionId: string | null;
  tab: SessionDetailTab;
}

const THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';
const DENSITY_MODE_STORAGE_KEY = 'agent-vis:density-mode';

function readInitialThemeMode(): ThemeMode {
  if (typeof window === 'undefined') {
    return 'system';
  }
  const saved = window.localStorage.getItem(THEME_MODE_STORAGE_KEY);
  if (saved === 'light' || saved === 'dark' || saved === 'system') {
    return saved;
  }
  return 'system';
}

function readInitialDensityMode(): DensityMode {
  if (typeof window === 'undefined') {
    return 'comfortable';
  }
  const saved = window.localStorage.getItem(DENSITY_MODE_STORAGE_KEY);
  if (saved === 'compact' || saved === 'comfortable') {
    return saved;
  }
  return 'comfortable';
}

function readSystemThemePreference(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
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
  const initialRoute = readRouteState();
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(initialRoute.sessionId);
  const [primaryView, setPrimaryView] = useState<PrimaryView>(initialRoute.view);
  const [sessionDetailTab, setSessionDetailTab] = useState<SessionDetailTab>(initialRoute.tab);
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>(readInitialThemeMode);
  const [densityMode, setDensityMode] = useState<DensityMode>(readInitialDensityMode);
  const [systemPrefersDark, setSystemPrefersDark] = useState(readSystemThemePreference);

  const resolvedTheme: ResolvedTheme =
    themeMode === 'system' ? (systemPrefersDark ? 'dark' : 'light') : themeMode;

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
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, themeMode);
  }, [themeMode]);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem(DENSITY_MODE_STORAGE_KEY, densityMode);
  }, [densityMode]);

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

  const handleSessionOpenFromOverview = (sessionId: string | null) => {
    if (!sessionId) {
      return;
    }

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
        <h1>Agent Trajectory Visualizer</h1>
        <div className="header-controls" role="group" aria-label="Display preferences">
          <div className="header-control-group">
            <label htmlFor="theme-mode-select">Theme</label>
            <select
              id="theme-mode-select"
              value={themeMode}
              onChange={(event) => setThemeMode(event.target.value as ThemeMode)}
              aria-label="Theme mode"
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </div>
          <div className="header-control-group">
            <label htmlFor="density-mode-select">Density</label>
            <select
              id="density-mode-select"
              value={densityMode}
              onChange={(event) => setDensityMode(event.target.value as DensityMode)}
              aria-label="Density mode"
            >
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </div>
        </div>
      </header>
      <main>
        <div className="view-tabs view-tabs--primary">
          <button
            className={`tab-button ${showCrossSession ? 'active' : ''}`}
            onClick={() => handlePrimaryViewChange('cross-session')}
          >
            Cross-Session Analytics
          </button>
          <button
            className={`tab-button ${showSessionDetail ? 'active' : ''}`}
            onClick={() => handlePrimaryViewChange('session-detail')}
            disabled={!selectedSessionId}
          >
            Session Detail
          </button>
        </div>

        {showCrossSession && (
          <div className="main-content main-content--overview">
            <Suspense fallback={<div className="loading-spinner">Loading...</div>}>
              <div className="session-content overview-analytics-block">
                <AdvancedAnalytics sessionId={null} />
              </div>
            </Suspense>

            <div className="overview-sessions-block">
              <SessionBrowser
                onSessionChange={handleSessionOpenFromOverview}
                selectedSessionId={selectedSessionId}
                autoSelectFirst={false}
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
                Back to Overview
              </button>
              {selectedSessionId && (
                <p className="detail-session-caption">
                  Session: <code>{selectedSessionId}</code>
                </p>
              )}
            </div>

            <div className="view-tabs view-tabs--secondary">
              <button
                className={`tab-button ${sessionDetailTab === 'timeline' ? 'active' : ''}`}
                onClick={() => handleSessionDetailTabChange('timeline')}
              >
                Timeline
              </button>
              <button
                className={`tab-button ${sessionDetailTab === 'statistics' ? 'active' : ''}`}
                onClick={() => handleSessionDetailTabChange('statistics')}
              >
                Statistics
              </button>
              {isMobile && showTimeline && selectedSessionId && (
                <button
                  className="tab-button mobile-sidebar-toggle"
                  onClick={() => setIsMobileSidebarOpen(!isMobileSidebarOpen)}
                  aria-label="Toggle sidebar"
                >
                  {isMobileSidebarOpen ? '✕ Close' : '☰ Info'}
                </button>
              )}
            </div>

            <div className="main-content">
              {selectedSessionId ? (
                <Suspense fallback={<div className="loading-spinner">Loading...</div>}>
                  {showTimeline && (
                    <div className="session-content">
                      <MessageTimeline sessionId={selectedSessionId} autoScrollToBottom={false} />
                    </div>
                  )}
                  {showStatistics && (
                    <div className="session-content">
                      <StatisticsDashboard sessionId={selectedSessionId} />
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
                    <p>No session selected.</p>
                    <button type="button" onClick={handleBackToOverview}>
                      Return to Overview
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
