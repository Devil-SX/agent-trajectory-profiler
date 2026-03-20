import type { PersistedSessionSummary } from '../types/session';

interface SessionSummaryCardProps {
  summary?: PersistedSessionSummary | null;
}

function formatGeneratedAt(timestamp: string | null | undefined): string {
  if (!timestamp) {
    return 'Not available';
  }

  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) {
    return timestamp;
  }

  return parsed.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function normalizeStatus(status: string | null | undefined): 'completed' | 'failed' | 'other' {
  const normalized = (status || '').trim().toLowerCase();
  if (normalized === 'completed') {
    return 'completed';
  }
  if (normalized === 'failed') {
    return 'failed';
  }
  return 'other';
}

export function SessionSummaryCard({ summary }: SessionSummaryCardProps) {
  if (!summary) {
    return (
      <section className="metadata-section session-summary-card">
        <h3 className="section-title">AI Summary</h3>
        <p className="no-data">No persisted summary available yet.</p>
      </section>
    );
  }

  const status = normalizeStatus(summary.generation_status);
  const statusLabel =
    status === 'completed' ? 'Completed' : status === 'failed' ? 'Failed' : summary.generation_status;

  return (
    <section className="metadata-section session-summary-card">
      <div className="session-summary-card__header">
        <h3 className="section-title">AI Summary</h3>
        <span className={`session-summary-card__status session-summary-card__status--${status}`}>
          {statusLabel}
        </span>
      </div>

      {summary.summary_text ? (
        <p className="session-summary-card__body">{summary.summary_text}</p>
      ) : status === 'failed' ? (
        <p className="session-summary-card__body session-summary-card__body--error">
          {summary.error_message || 'Summary generation failed.'}
        </p>
      ) : (
        <p className="no-data">Summary is not available for this session.</p>
      )}

      <dl className="session-summary-card__meta">
        <div className="session-summary-card__meta-row">
          <dt className="label">Model</dt>
          <dd className="value session-summary-card__model">{summary.model_id}</dd>
        </div>
        <div className="session-summary-card__meta-row">
          <dt className="label">Generated</dt>
          <dd className="value">{formatGeneratedAt(summary.generated_at)}</dd>
        </div>
        {summary.summary_chars !== null && summary.summary_chars !== undefined && (
          <div className="session-summary-card__meta-row">
            <dt className="label">Characters</dt>
            <dd className="value">{summary.summary_chars}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}
