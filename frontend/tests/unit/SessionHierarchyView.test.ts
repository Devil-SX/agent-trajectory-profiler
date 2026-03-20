import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { SessionHierarchyView } from '../../src/components/SessionHierarchyView';
import type { SessionSectionDetail, SessionSummary } from '../../src/types/session';

const sessions: SessionSummary[] = [
  {
    session_id: 'session-alpha',
    ecosystem: 'codex',
    project_path: '/workspace/alpha',
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-01T11:00:00Z',
    total_messages: 12,
    total_tokens: 4000,
    git_branch: 'main',
    version: '1.0.0',
    parsed_at: null,
    duration_seconds: 1200,
    bottleneck: 'model',
    automation_ratio: 1.8,
  },
];

const sections: SessionSectionDetail[] = [
  {
    section_id: 'session-alpha:section:1',
    section_index: 1,
    title: 'Investigate parser failure',
    start_message_uuid: 'u1',
    end_message_uuid: 'a2',
    start_timestamp: '2026-03-01T10:00:00Z',
    end_timestamp: '2026-03-01T10:10:00Z',
    total_messages: 4,
    user_message_count: 1,
    assistant_message_count: 2,
    tool_call_count: 1,
    input_tokens: 120,
    output_tokens: 80,
    total_tokens: 200,
    char_count: 500,
    duration_seconds: 600,
    generation_status: 'completed',
    model_id: 'codex:gpt-5.4',
    prompt_version: 'session-section-summary-v1',
    generated_at: '2026-03-01T10:11:00Z',
    error_message: null,
    summary_text: 'Pinned the failure to a malformed event.',
    summary_chars: 39,
    structured_summary: {
      title: 'Parser failure',
      summary: 'Pinned the failure to a malformed event.',
      goal: 'Find the parser regression',
      actions: ['Inspect fixture', 'Re-run parser'],
      outcome: 'Malformed event identified',
      tool_patterns: ['Read', 'Bash'],
      risk_or_blocker: null,
      keywords: ['parser', 'fixture'],
    },
  },
];

describe('SessionHierarchyView', () => {
  test('renders project, session, and section status', () => {
    render(
      React.createElement(SessionHierarchyView, {
        sessions,
        selectedSessionId: 'session-alpha',
        selectedSectionIndex: 1,
        sectionCache: { 'session-alpha': sections },
        loadingSectionsForSessionId: null,
        expandedSessionIds: ['session-alpha'],
        onToggleSessionExpansion: () => undefined,
        onSelectSession: () => undefined,
        onSelectSection: () => undefined,
      })
    );

    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByText('/workspace/alpha')).toBeInTheDocument();
    expect(screen.getByText('Investigate parser failure')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  test('invokes callbacks for session toggle and section select', async () => {
    const onToggleSessionExpansion = vi.fn();
    const onSelectSection = vi.fn();

    render(
      React.createElement(SessionHierarchyView, {
        sessions,
        selectedSessionId: 'session-alpha',
        selectedSectionIndex: null,
        sectionCache: { 'session-alpha': sections },
        loadingSectionsForSessionId: null,
        expandedSessionIds: ['session-alpha'],
        onToggleSessionExpansion,
        onSelectSession: () => undefined,
        onSelectSection,
      })
    );

    fireEvent.click(screen.getByRole('button', { name: 'Hide sections' }));
    expect(onToggleSessionExpansion).toHaveBeenCalledWith('session-alpha');

    fireEvent.click(screen.getByRole('button', { name: /Investigate parser failure/i }));
    expect(onSelectSection).toHaveBeenCalledWith('session-alpha', 1);
  });
});
