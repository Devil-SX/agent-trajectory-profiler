import { useState } from 'react';
import './App.css';
import { SessionSelector } from './components/SessionSelector';

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
            <p>Selected Session: {selectedSessionId}</p>
            <p className="placeholder-text">Session visualization components will be added here.</p>
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
