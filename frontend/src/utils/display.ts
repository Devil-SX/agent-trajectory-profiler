/**
 * Shared display format helpers for session/project metadata.
 */

export function getProjectName(projectPath: string): string {
  const segments = projectPath.split('/').filter(Boolean);
  return segments[segments.length - 1] || projectPath;
}

export function getRelativeTime(timestamp: string): string {
  const now = new Date();
  const past = new Date(timestamp);
  const diffMs = now.getTime() - past.getTime();
  if (diffMs < 60_000) return 'just now';
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 60) return `${diffMins} min ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return past.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function formatAbsoluteTime(timestamp: string): string {
  return new Date(timestamp).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function formatRelativeWithAbsolute(timestamp: string): string {
  return `${getRelativeTime(timestamp)} (${formatAbsoluteTime(timestamp)})`;
}

export function truncateMiddle(value: string, head: number = 6, tail: number = 4): string {
  if (value.length <= head + tail + 1) {
    return value;
  }
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}
