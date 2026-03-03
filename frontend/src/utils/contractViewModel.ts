import type {
  CapabilityListResponse,
  EcosystemCapability,
  SessionStatistics,
} from '../types/session';

const SOURCE_COLORS = [
  '#2563eb',
  '#16a34a',
  '#7c3aed',
  '#ea580c',
  '#0891b2',
  '#dc2626',
  '#9333ea',
  '#0284c7',
];

const DEFAULT_ECOSYSTEM_LABELS: Record<string, string> = {
  claude_code: 'Claude Code',
  codex: 'Codex',
};

export interface EcosystemPresentation {
  ecosystem: string;
  label: string;
  color: string;
}

export interface CapabilityNotice {
  id: string;
  severity: 'info' | 'warning';
  label: string;
  reason: string;
}

export interface SessionStatisticsViewModel {
  automationRatio: number | null;
  tokenYieldRatio: number | null;
  charYieldRatio: number | null;
  capabilityNotices: CapabilityNotice[];
}

export function buildCapabilityIndex(
  payload: CapabilityListResponse | null | undefined
): Record<string, EcosystemCapability> {
  const index: Record<string, EcosystemCapability> = {};
  for (const item of payload?.capabilities ?? []) {
    index[item.ecosystem] = item;
  }
  return index;
}

function colorFromKey(key: string): string {
  if (!key) {
    return '#94a3b8';
  }
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) {
    hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  }
  return SOURCE_COLORS[hash % SOURCE_COLORS.length];
}

export function getEcosystemPresentation(
  ecosystem: string | null | undefined,
  capabilityIndex: Record<string, EcosystemCapability>
): EcosystemPresentation {
  const normalized = (ecosystem ?? '').trim();
  const capability = normalized ? capabilityIndex[normalized] : undefined;
  return {
    ecosystem: normalized || 'unknown',
    label:
      capability?.display_name ||
      (normalized ? DEFAULT_ECOSYSTEM_LABELS[normalized] || normalized : 'Unknown'),
    color: colorFromKey(normalized),
  };
}

export function deriveCapabilityNotices(
  capability: EcosystemCapability | null | undefined
): CapabilityNotice[] {
  if (!capability) {
    return [];
  }

  const notices: CapabilityNotice[] = [];

  if (!capability.token_field_support.reasoning_tokens) {
    notices.push({
      id: 'reasoning_tokens',
      severity: 'info',
      label: 'Reasoning tokens',
      reason: 'Not exposed by this ecosystem; related metrics should render as N/A.',
    });
  }

  if (!capability.event_shape_support.parent_child_session_links) {
    notices.push({
      id: 'lineage_links',
      severity: 'info',
      label: 'Parent/child lineage',
      reason: 'Physical parent-child session links are not available.',
    });
  }

  if (capability.fallback_behavior.missing_timestamps === 'infer_best_effort') {
    notices.push({
      id: 'timestamp_inference',
      severity: 'warning',
      label: 'Time-based metrics',
      reason: 'Missing timestamps are inferred best-effort; latency/time metrics are approximate.',
    });
  }

  if (!capability.tool_error_taxonomy_support.categorization_available) {
    notices.push({
      id: 'tool_error_taxonomy',
      severity: 'warning',
      label: 'Tool error taxonomy',
      reason: 'Tool errors cannot be fully categorized in this ecosystem.',
    });
  }

  return notices;
}

export function buildSessionStatisticsViewModel(
  statistics: SessionStatistics,
  capability: EcosystemCapability | null | undefined
): SessionStatisticsViewModel {
  const interactions = statistics.time_breakdown?.user_interaction_count || 0;
  const automationRatio = interactions > 0 ? statistics.total_tool_calls / interactions : null;
  const tokenYieldRatio =
    typeof statistics.leverage_ratio_tokens === 'number'
      ? statistics.leverage_ratio_tokens
      : typeof statistics.user_yield_ratio_tokens === 'number'
        ? statistics.user_yield_ratio_tokens
        : null;
  const charYieldRatio =
    typeof statistics.leverage_ratio_chars === 'number'
      ? statistics.leverage_ratio_chars
      : typeof statistics.user_yield_ratio_chars === 'number'
        ? statistics.user_yield_ratio_chars
        : null;

  return {
    automationRatio,
    tokenYieldRatio,
    charYieldRatio,
    capabilityNotices: deriveCapabilityNotices(capability),
  };
}
