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

const THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';

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

function readSystemThemePreference(): boolean {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function App() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [comparisonSessionId, setComparisonSessionId] = useState<string | null>(null);
  const [primaryView, setPrimaryView] = useState<PrimaryView>('session-detail');
  const [sessionDetailTab, setSessionDetailTab] = useState<SessionDetailTab>('timeline');
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [themeMode, setThemeMode] = useState<ThemeMode>(readInitialThemeMode);
  const [systemPrefersDark, setSystemPrefersDark] = useState(readSystemThemePreference);

  const resolvedTheme: ResolvedTheme =
    themeMode === 'system' ? (systemPrefersDark ? 'dark' : 'light') : themeMode;

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
    if (typeof window === 'undefined') {
      return;
    }
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, themeMode);
  }, [themeMode]);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth <= 768);
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);

    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  const handleSessionChange = (sessionId: string | null) => {
    setSelectedSessionId(sessionId);
  };

  const handleComparisonSessionChange = (sessionId: string | null) => {
    setComparisonSessionId(sessionId);
  };

  const handlePrimaryViewChange = (view: PrimaryView) => {
    setPrimaryView(view);
    if (view !== 'session-detail') {
      setIsMobileSidebarOpen(false);
    }
  };

  const handleSessionDetailTabChange = (tab: SessionDetailTab) => {
    setSessionDetailTab(tab);
    if (tab !== 'timeline') {
      setIsMobileSidebarOpen(false);
    }
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
        <h1>Claude Code Session Visualizer</h1>
        <div className="header-controls">
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
      </header>
      <main>
        <SessionBrowser
          onSessionChange={handleSessionChange}
          onComparisonSessionChange={showCrossSession ? handleComparisonSessionChange : undefined}
          selectedSessionId={selectedSessionId}
          comparisonSessionId={comparisonSessionId}
        />

        <div className="view-tabs view-tabs--primary">
          <button
            className={`tab-button ${showSessionDetail ? 'active' : ''}`}
            onClick={() => handlePrimaryViewChange('session-detail')}
          >
            Session Detail
          </button>
          <button
            className={`tab-button ${showCrossSession ? 'active' : ''}`}
            onClick={() => handlePrimaryViewChange('cross-session')}
          >
            Cross-Session Analytics
          </button>
        </div>

        {showSessionDetail && (
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
        )}

        <div className="main-content">
          {showCrossSession ? (
            <Suspense fallback={<div className="loading-spinner">Loading...</div>}>
              <div className="session-content">
                <AdvancedAnalytics
                  sessionId={selectedSessionId}
                  comparisonSessionId={comparisonSessionId}
                />
              </div>
            </Suspense>
          ) : selectedSessionId ? (
            <Suspense fallback={<div className="loading-spinner">Loading...</div>}>
              {showTimeline && (
                <div className="session-content">
                  <MessageTimeline sessionId={selectedSessionId} autoScrollToBottom={true} />
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
              <p>No session selected for Session Detail. Cross-Session Analytics is still available.</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
