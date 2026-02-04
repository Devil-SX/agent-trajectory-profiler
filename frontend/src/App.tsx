import { useState } from 'react';
import './App.css';
import { SessionSelector } from './components/SessionSelector';
import { MessageTimeline } from './components/MessageTimeline';

function App() {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const handleSessionChange = (sessionId: string | null) => {
    setSelectedSessionId(sessionId);
  };

  return (
    <div className="app">
      <header>
        <h1>Claude Code Session Visualizer</h1>
      </header>
      <main>
        <SessionSelector onSessionChange={handleSessionChange} />
        {selectedSessionId ? (
          <div className="session-content">
            <MessageTimeline sessionId={selectedSessionId} autoScrollToBottom={true} />
          </div>
        ) : (
          <div className="no-session">
            <p>No session selected. Please select a session above.</p>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
