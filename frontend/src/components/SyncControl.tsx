import type { SyncEcosystemDetail, SyncStatusResponse } from '../types/session';
import './SyncControl.css';

interface SyncControlProps {
  status?: SyncStatusResponse;
  isLoading: boolean;
  isSyncing: boolean;
  onRunSync: () => void;
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

function formatTime(timestamp: string | null | undefined): string {
  if (!timestamp) return 'Never';
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return 'Unknown';
  return date.toLocaleString();
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
}: SyncControlProps) {
  const detail = status?.last_sync;
  const claude = getEcoRecord(detail?.ecosystems, 'claude_code');
  const codex = getEcoRecord(detail?.ecosystems, 'codex');

  return (
    <section className="sync-control" aria-label="Synchronization control">
      <div className="sync-control__header">
        <div>
          <h3>DB Sync</h3>
          <p>
            Last sync: <strong>{formatTime(detail?.finished_at)}</strong>
          </p>
        </div>
        <button
          type="button"
          className="sync-control__button"
          onClick={onRunSync}
          disabled={isLoading || isSyncing || status?.sync_running}
        >
          {isSyncing || status?.sync_running ? 'Syncing...' : 'Sync Now'}
        </button>
      </div>

      <div className="sync-control__summary">
        <span>Parsed: {detail?.parsed ?? 0}</span>
        <span>Skipped: {detail?.skipped ?? 0}</span>
        <span>Errors: {detail?.errors ?? 0}</span>
        <span>Files: {detail?.total_files_scanned ?? status?.total_files ?? 0}</span>
        <span>Size: {formatBytes(detail?.total_file_size_bytes ?? 0)}</span>
      </div>

      <div className="sync-control__ecosystems">
        <div className="sync-control__eco-row">
          <span className="sync-control__eco-name">Claude Code</span>
          <span>{claude.files_scanned} files</span>
          <span>{formatBytes(claude.file_size_bytes)}</span>
          <span>
            {claude.parsed}/{claude.skipped}/{claude.errors}
          </span>
        </div>
        <div className="sync-control__eco-row">
          <span className="sync-control__eco-name">Codex</span>
          <span>{codex.files_scanned} files</span>
          <span>{formatBytes(codex.file_size_bytes)}</span>
          <span>
            {codex.parsed}/{codex.skipped}/{codex.errors}
          </span>
        </div>
      </div>

      {detail?.error_samples && detail.error_samples.length > 0 && (
        <details className="sync-control__errors">
          <summary>Sync errors ({detail.error_samples.length})</summary>
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
