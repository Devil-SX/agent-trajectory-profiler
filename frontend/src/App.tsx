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

function App() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [comparisonSessionId, setComparisonSessionId] = useState<string | null>(null);
  const [primaryView, setPrimaryView] = useState<PrimaryView>('session-detail');
  const [sessionDetailTab, setSessionDetailTab] = useState<SessionDetailTab>('timeline');
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);

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
            background: '#333',
            color: '#fff',
          },
          success: {
            duration: 3000,
            iconTheme: {
              primary: '#10b981',
              secondary: '#fff',
            },
          },
          error: {
            duration: 5000,
            iconTheme: {
              primary: '#ef4444',
              secondary: '#fff',
            },
          },
        }}
      />
      <header>
        <h1>Claude Code Session Visualizer</h1>
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
