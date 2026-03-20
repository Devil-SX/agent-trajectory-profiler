import type { SessionSectionDetail, SessionSummary } from '../types/session';
import { getProjectName, truncateMiddle } from '../utils/display';

interface SessionHierarchyViewProps {
  sessions: SessionSummary[];
  selectedSessionId?: string | null;
  selectedSectionIndex?: number | null;
  sectionCache: Record<string, SessionSectionDetail[]>;
  loadingSectionsForSessionId?: string | null;
  expandedSessionIds: string[];
  onToggleSessionExpansion: (sessionId: string) => void;
  onSelectSession: (sessionId: string) => void;
  onSelectSection: (sessionId: string, sectionIndex: number) => void;
}

interface ProjectGroup {
  projectPath: string;
  projectName: string;
  sessions: SessionSummary[];
}

function groupByProject(sessions: SessionSummary[]): ProjectGroup[] {
  const projectMap = new Map<string, SessionSummary[]>();
  for (const session of sessions) {
    const key = session.project_path || '(unknown)';
    const existing = projectMap.get(key) || [];
    existing.push(session);
    projectMap.set(key, existing);
  }
  return Array.from(projectMap.entries()).map(([projectPath, groupedSessions]) => ({
    projectPath,
    projectName: getProjectName(projectPath),
    sessions: groupedSessions,
  }));
}

export function SessionHierarchyView({
  sessions,
  selectedSessionId = null,
  selectedSectionIndex = null,
  sectionCache,
  loadingSectionsForSessionId = null,
  expandedSessionIds,
  onToggleSessionExpansion,
  onSelectSession,
  onSelectSection,
}: SessionHierarchyViewProps) {
  const projectGroups = groupByProject(sessions);

  if (sessions.length === 0) {
    return (
      <div className="session-hierarchy session-hierarchy--empty">
        <p className="session-hierarchy__empty">No sessions found.</p>
      </div>
    );
  }

  return (
    <div className="session-hierarchy">
      {projectGroups.map((group) => (
        <section key={group.projectPath} className="session-tree__project">
          <header className="session-tree__project-header">
            <div className="session-tree__project-name">{group.projectName}</div>
            <div className="session-tree__project-path" title={group.projectPath}>
              {group.projectPath}
            </div>
          </header>
          <div className="session-tree__project-body">
            {group.sessions.map((session) => {
              const isExpanded =
                expandedSessionIds.includes(session.session_id) || session.session_id === selectedSessionId;
              const sections = sectionCache[session.session_id] || [];
              return (
                <div key={session.session_id} className="session-tree__session">
                  <button
                    type="button"
                    className={`session-tree__session-button ${
                      session.session_id === selectedSessionId ? 'session-tree__session-button--active' : ''
                    }`}
                    onClick={() => onSelectSession(session.session_id)}
                  >
                    <span className="session-tree__session-title">
                      {truncateMiddle(session.session_id, 8, 6)}
                    </span>
                    <span className="session-tree__session-meta">
                      {session.total_messages} msg · {session.total_tokens} tok
                    </span>
                  </button>
                  <button
                    type="button"
                    className="session-tree__toggle"
                    onClick={() => onToggleSessionExpansion(session.session_id)}
                    aria-expanded={isExpanded}
                  >
                    {isExpanded ? 'Hide sections' : 'Show sections'}
                  </button>
                  {isExpanded && (
                    <div className="session-tree__sections">
                      {loadingSectionsForSessionId === session.session_id && sections.length === 0 && (
                        <div className="session-tree__section-hint">Loading sections...</div>
                      )}
                      {loadingSectionsForSessionId !== session.session_id && sections.length === 0 && (
                        <div className="session-tree__section-hint">No sections available.</div>
                      )}
                      {sections.map((section) => (
                        <button
                          key={section.section_id}
                          type="button"
                          className={`session-tree__section-button ${
                            session.session_id === selectedSessionId &&
                            section.section_index === selectedSectionIndex
                              ? 'session-tree__section-button--active'
                              : ''
                          }`}
                          onClick={() => onSelectSection(session.session_id, section.section_index)}
                        >
                          <span className="session-tree__section-index">
                            S{section.section_index}
                          </span>
                          <span className="session-tree__section-title">{section.title}</span>
                          <span
                            className={`session-tree__section-status session-tree__section-status--${section.generation_status}`}
                          >
                            {section.generation_status}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}
