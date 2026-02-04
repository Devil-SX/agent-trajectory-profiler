import { useState } from 'react';
import './App.css';
import { SessionSelector } from './components/SessionSelector';
import { MessageTimeline } from './components/MessageTimeline';
import { SessionMetadataSidebar } from './components/SessionMetadataSidebar';
import { StatisticsDashboard } from './components/StatisticsDashboard';
import { AdvancedAnalytics } from './components/AdvancedAnalytics';

type ViewTab = 'timeline' | 'statistics' | 'analytics';

function App() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [comparisonSessionId, setComparisonSessionId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<ViewTab>('timeline');

  const handleSessionChange = (sessionId: string | null) => {
    setSelectedSessionId(sessionId);
  };

  const handleComparisonSessionChange = (sessionId: string | null) => {
    setComparisonSessionId(sessionId);
  };

  return (
    <div className="app">
      <header>
        <h1>Claude Code Session Visualizer</h1>
      </header>
      <main>
        <SessionSelector
          onSessionChange={handleSessionChange}
          onComparisonSessionChange={activeView === 'analytics' ? handleComparisonSessionChange : undefined}
          selectedSessionId={selectedSessionId}
          comparisonSessionId={comparisonSessionId}
        />

        {selectedSessionId && (
          <div className="view-tabs">
            <button
              className={`tab-button ${activeView === 'timeline' ? 'active' : ''}`}
              onClick={() => setActiveView('timeline')}
            >
              Timeline
            </button>
            <button
              className={`tab-button ${activeView === 'statistics' ? 'active' : ''}`}
              onClick={() => setActiveView('statistics')}
            >
              Statistics
            </button>
            <button
              className={`tab-button ${activeView === 'analytics' ? 'active' : ''}`}
              onClick={() => setActiveView('analytics')}
            >
              Advanced Analytics
            </button>
          </div>
        )}

        <div className="main-content">
          {selectedSessionId ? (
            <>
              {activeView === 'timeline' && (
                <div className="session-content">
                  <MessageTimeline sessionId={selectedSessionId} autoScrollToBottom={true} />
                </div>
              )}
              {activeView === 'statistics' && (
                <div className="session-content">
                  <StatisticsDashboard sessionId={selectedSessionId} />
                </div>
              )}
              {activeView === 'analytics' && (
                <div className="session-content">
                  <AdvancedAnalytics
                    sessionId={selectedSessionId}
                    comparisonSessionId={comparisonSessionId}
                  />
                </div>
              )}
              {activeView === 'timeline' && <SessionMetadataSidebar sessionId={selectedSessionId} />}
            </>
          ) : (
            <div className="no-session">
              <p>No session selected. Please select a session above.</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
