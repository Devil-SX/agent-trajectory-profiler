import type { SyncEcosystemDetail, SyncStatusResponse } from '../types/session';
import { useI18n } from '../i18n';
import './SyncControl.css';

interface SyncControlProps {
  status?: SyncStatusResponse;
  isLoading: boolean;
  isSyncing: boolean;
  onRunSync: () => void;
  compact?: boolean;
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

function getEcoRecord(
  ecosystems: SyncEcosystemDetail[] | undefined,
  target: 'claude_code' | 'codex'
): SyncEcosystemDetail {
  return (
    ecosystems?.find((entry) => entry.ecosystem === target) ?? {
      ecosystem: target,
      files_scanned: 0,
      file_size_bytes: 0,
      parsed: 0,
      skipped: 0,
      errors: 0,
    }
  );
}

export function SyncControl({
  status,
  isLoading,
  isSyncing,
  onRunSync,
  compact = false,
}: SyncControlProps) {
  const { t, formatDateTime, formatNumber } = useI18n();
  const detail = status?.last_sync;
  const claude = getEcoRecord(detail?.ecosystems, 'claude_code');
  const codex = getEcoRecord(detail?.ecosystems, 'codex');
  const formatTime = (timestamp: string | null | undefined): string => {
    if (!timestamp) return t('sync.never');
    const date = new Date(timestamp);
    if (Number.isNaN(date.getTime())) return t('sync.unknown');
    return formatDateTime(date);
  };

  return (
    <section
      className={`sync-control ${compact ? 'sync-control--compact' : ''}`.trim()}
      aria-label={t('sync.aria')}
    >
      <div className="sync-control__header">
        <div>
          <h3>{t('sync.title')}</h3>
          <p>
            {t('sync.lastSync')}
            : <strong>{formatTime(detail?.finished_at)}</strong>
          </p>
        </div>
        <span className="sync-control__status-pill">
          {status?.sync_running ? 'running' : detail?.status ?? 'idle'}
        </span>
        <button
          type="button"
          className="sync-control__button"
          onClick={onRunSync}
          disabled={isLoading || isSyncing || status?.sync_running}
        >
          {isSyncing || status?.sync_running ? t('sync.syncing') : t('sync.syncNow')}
        </button>
      </div>

      <div className="sync-control__summary">
        <span>
          {t('sync.summary.parsed')}
          : {formatNumber(detail?.parsed ?? 0)}
        </span>
        <span>
          {t('sync.summary.skipped')}
          : {formatNumber(detail?.skipped ?? 0)}
        </span>
        <span>
          {t('sync.summary.errors')}
          : {formatNumber(detail?.errors ?? 0)}
        </span>
        <span>
          {t('sync.summary.files')}
          : {formatNumber(detail?.total_files_scanned ?? status?.total_files ?? 0)}
        </span>
        <span>
          {t('sync.summary.size')}
          : {formatBytes(detail?.total_file_size_bytes ?? 0)}
        </span>
      </div>

      <div className="sync-control__ecosystems">
        <div className="sync-control__eco-row">
          <span className="sync-control__eco-name">Claude Code</span>
          <span>
            {formatNumber(claude.files_scanned)}
            {' '}
            {t('sync.filesSuffix')}
          </span>
          <span>{formatBytes(claude.file_size_bytes)}</span>
          <span>
            {formatNumber(claude.parsed)}/{formatNumber(claude.skipped)}/{formatNumber(claude.errors)}
          </span>
        </div>
        <div className="sync-control__eco-row">
          <span className="sync-control__eco-name">Codex</span>
          <span>
            {formatNumber(codex.files_scanned)}
            {' '}
            {t('sync.filesSuffix')}
          </span>
          <span>{formatBytes(codex.file_size_bytes)}</span>
          <span>
            {formatNumber(codex.parsed)}/{formatNumber(codex.skipped)}/{formatNumber(codex.errors)}
          </span>
        </div>
      </div>

      {detail?.error_samples && detail.error_samples.length > 0 && (
        <details className="sync-control__errors">
          <summary>{t('sync.errors', { values: { count: detail.error_samples.length } })}</summary>
          <ul>
            {detail.error_samples.slice(0, 5).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
