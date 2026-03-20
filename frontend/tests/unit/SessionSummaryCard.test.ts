import React from 'react';
import { render, screen } from '@testing-library/react';

import { SessionSummaryCard } from '../../src/components/SessionSummaryCard';

describe('SessionSummaryCard', () => {
  test('renders completed persisted summary content and metadata', () => {
    render(
      React.createElement(SessionSummaryCard, {
        summary: {
          generation_status: 'completed',
          summary_text: 'Investigated the sync hot path and isolated JSON decoding cost.',
          summary_chars: 63,
          model_id: 'codex:gpt-5.4',
          generated_at: '2026-03-18T00:00:00Z',
          error_message: null,
        },
      })
    );

    expect(screen.getByText('AI Summary')).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(
      screen.getByText('Investigated the sync hot path and isolated JSON decoding cost.')
    ).toBeInTheDocument();
    expect(screen.getByText('codex:gpt-5.4')).toBeInTheDocument();
    expect(screen.getByText('63')).toBeInTheDocument();
  });

  test('renders failure state when summary generation failed', () => {
    render(
      React.createElement(SessionSummaryCard, {
        summary: {
          generation_status: 'failed',
          summary_text: null,
          summary_chars: null,
          model_id: 'claude:sonnet',
          generated_at: null,
          error_message: 'CLI timed out before returning a summary.',
        },
      })
    );

    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText('CLI timed out before returning a summary.')).toBeInTheDocument();
  });

  test('renders empty placeholder when no persisted summary exists', () => {
    render(React.createElement(SessionSummaryCard, { summary: null }));

    expect(screen.getByText('AI Summary')).toBeInTheDocument();
    expect(screen.getByText('No persisted summary available yet.')).toBeInTheDocument();
  });
});
