import { useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  useAnalyticsDistributionQuery,
  useAnalyticsOverviewQuery,
  useAnalyticsTimeseriesQuery,
  useCapabilitiesQuery,
  useProjectComparisonQuery,
  useProjectSwimlaneQuery,
} from '../hooks/useSessionsQuery';
import type { AnalyticsBucket, RoleSourceAggregate } from '../types/session';
import {
  buildCapabilityIndex,
  deriveCapabilityNotices,
  getEcosystemPresentation,
} from '../utils/contractViewModel';
import {
  createTimeAxisTickFormatter,
  formatTokenAxisTick,
  formatTokenWithRawValue,
} from '../utils/chartFormatters';
import { truncateMiddle } from '../utils/display';
import { useI18n } from '../i18n';
import { MetricTerm } from './MetricHelp';
import './CrossSessionOverview.css';

type RangePreset = '7d' | '30d' | '90d' | 'custom';

interface DateWindow {
  startDate: string | null;
  endDate: string | null;
}

interface DayNightRow {
  period: 'Day' | 'Night';
  model: number;
  tool: number;
  user: number;
  inactive: number;
  ratioDenominator: number;
  total: number;
  share: number;
}

interface DayNightCoverageRow {
  period: 'Day' | 'Night';
  windowSeconds: number;
  modelSeconds: number;
  toolSeconds: number;
  userSeconds: number;
  modelCoverage: number;
  toolCoverage: number;
  userCoverage: number;
}

type SourceFilter = 'all' | string;
type RoleSourceMetric = 'time' | 'tokens' | 'tool_calls' | 'errors';
type RoleSourceView = 'source' | 'role';
type DayNightRatioMode = 'include_inactive' | 'exclude_inactive';

const DISTRIBUTION_COLORS = ['#2563eb', '#0891b2', '#ea580c', '#dc2626', '#16a34a', '#7c3aed'];
const ROLE_COLORS: Record<'user' | 'model' | 'tool', string> = {
  model: '#2563eb',
  tool: '#0891b2',
  user: '#ea580c',
};

function sourceFilterTestId(ecosystem: string): string {
  if (ecosystem === 'claude_code') {
    return 'source-filter-claude';
  }
  return `source-filter-${ecosystem}`;
}

function toIsoDate(value: Date): string {
  const adjusted = new Date(value.getTime() - value.getTimezoneOffset() * 60000);
  return adjusted.toISOString().slice(0, 10);
}

function buildPresetRange(days: number): DateWindow {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (days - 1));
  return {
    startDate: toIsoDate(start),
    endDate: toIsoDate(end),
  };
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds <= 0) return '0s';
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m`;
  }

  return `${Math.floor(seconds)}s`;
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / Math.pow(1024, index);
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatLeverage(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return 'N/A';
  }
  return `${value.toFixed(2)}x`;
}

function formatSessionShareLabel(label: string): string {
  return truncateMiddle(label, 5, 4);
}

function clamp01(value: number): number {
  if (!Number.isFinite(value)) return 0;
  if (value <= 0) return 0;
  if (value >= 1) return 1;
  return value;
}

function buildSwimlaneColor(tokens: number, maxTokens: number): string {
  if (tokens <= 0 || maxTokens <= 0) {
    return '#f3f4f6';
  }
  const ratio = Math.min(1, tokens / maxTokens);
  const alpha = 0.18 + ratio * 0.72;
  return `rgba(37, 99, 235, ${alpha.toFixed(3)})`;
}

function formatPeriodLabel(
  period: string,
  interval: 'day' | 'week',
  formatDate: (value: string | Date, options?: Intl.DateTimeFormatOptions) => string,
): string {
  if (interval === 'day') {
    return formatDate(period, { month: 'short', day: 'numeric' });
  }

  const weekMatch = /^(\d{4})-W(\d{2})$/.exec(period);
  if (!weekMatch) {
    return period;
  }
  return `W${weekMatch[2]} ${weekMatch[1]}`;
}

function metricValue(row: RoleSourceAggregate, metric: RoleSourceMetric): number {
  if (metric === 'tokens') return row.token_count;
  if (metric === 'tool_calls') return row.tool_calls;
  if (metric === 'errors') return row.error_count;
  return row.time_seconds;
}

export function CrossSessionOverview() {
  const { t, formatNumber, formatTokenCount, formatPercent, formatDate } = useI18n();
  const [preset, setPreset] = useState<RangePreset>('7d');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [roleSourceMetric, setRoleSourceMetric] = useState<RoleSourceMetric>('time');
  const [roleSourceView, setRoleSourceView] = useState<RoleSourceView>('source');
  const [dayNightRatioMode, setDayNightRatioMode] = useState<DayNightRatioMode>('include_inactive');
  const [projectTimelineInterval, setProjectTimelineInterval] = useState<'day' | 'week'>('day');
  const [codingFraction, setCodingFraction] = useState(0.3);
  const [tokensPerLine, setTokensPerLine] = useState(10);
  const [projectSelection, setProjectSelection] = useState<Record<string, boolean>>({});
  const [customRange, setCustomRange] = useState<DateWindow>({
    startDate: null,
    endDate: null,
  });

  const activeRange = useMemo<DateWindow>(() => {
    if (preset === '30d') {
      return buildPresetRange(30);
    }
    if (preset === '90d') {
      return buildPresetRange(90);
    }
    if (preset === 'custom') {
      return customRange;
    }
    return buildPresetRange(7);
  }, [customRange, preset]);

  const interval = preset === '90d' ? 'week' : 'day';
  const ecosystemFilter = sourceFilter === 'all' ? null : sourceFilter;
  const formatPercentPoint = (value: number): string => formatPercent(value, 1);
  const formatPercentRatio = (value: number): string => formatPercent(value / 100, 1);
  const formatTokenTooltip = (value: number): string =>
    formatTokenWithRawValue(value, formatNumber);

  const { data: overview, isLoading: overviewLoading, error: overviewError } =
    useAnalyticsOverviewQuery(activeRange.startDate, activeRange.endDate, ecosystemFilter);

  const { data: automationDistribution, isLoading: automationLoading, error: automationError } =
    useAnalyticsDistributionQuery(
      'automation_band',
      activeRange.startDate,
      activeRange.endDate,
      ecosystemFilter
    );

  const { data: sessionShareDistribution, isLoading: shareLoading, error: shareError } =
    useAnalyticsDistributionQuery(
      'session_token_share',
      activeRange.startDate,
      activeRange.endDate,
      ecosystemFilter
    );

  const { data: timeseries, isLoading: timeseriesLoading, error: timeseriesError } =
    useAnalyticsTimeseriesQuery(interval, activeRange.startDate, activeRange.endDate, ecosystemFilter);

  const {
    data: projectComparison,
    isLoading: projectComparisonLoading,
    error: projectComparisonError,
  } = useProjectComparisonQuery(
    activeRange.startDate,
    activeRange.endDate,
    12,
    ecosystemFilter
  );

  const {
    data: projectSwimlane,
    isLoading: projectSwimlaneLoading,
    error: projectSwimlaneError,
  } = useProjectSwimlaneQuery(
    projectTimelineInterval,
    activeRange.startDate,
    activeRange.endDate,
    12,
    ecosystemFilter
  );
  const capabilitiesQuery = useCapabilitiesQuery();

  const isLoading =
    overviewLoading ||
    automationLoading ||
    shareLoading ||
    timeseriesLoading ||
    projectComparisonLoading ||
    projectSwimlaneLoading;
  const errorMessage =
    overviewError?.message ||
    automationError?.message ||
    shareError?.message ||
    timeseriesError?.message ||
    projectComparisonError?.message ||
    projectSwimlaneError?.message ||
    null;

  const topSessionShare = useMemo(() => {
    if (!sessionShareDistribution) return [];
    return sessionShareDistribution.buckets.slice(0, 8);
  }, [sessionShareDistribution]);

  const getLeadingBucket = (buckets: AnalyticsBucket[]): string => {
    if (buckets.length === 0) {
      return t('table.unknown');
    }
    const [top] = buckets;
    return `${top.label} (${formatPercentRatio(top.percent)})`;
  };

  const dayNightRows = useMemo<DayNightRow[]>(() => {
    if (!overview) return [];
    const includeInactive = dayNightRatioMode === 'include_inactive';

    const rows: DayNightRow[] = [
      {
        period: 'Day',
        model: overview.day_model_time_seconds,
        tool: overview.day_tool_time_seconds,
        user: overview.day_user_time_seconds,
        inactive: overview.day_inactive_time_seconds,
        ratioDenominator: 0,
        total: 0,
        share: 0,
      },
      {
        period: 'Night',
        model: overview.night_model_time_seconds,
        tool: overview.night_tool_time_seconds,
        user: overview.night_user_time_seconds,
        inactive: overview.night_inactive_time_seconds,
        ratioDenominator: 0,
        total: 0,
        share: 0,
      },
    ];

    const withTotals = rows.map((row) => {
      const activeSeconds = row.model + row.tool + row.user;
      const ratioDenominator = includeInactive ? activeSeconds + row.inactive : activeSeconds;
      return {
        ...row,
        ratioDenominator,
        total: ratioDenominator,
      };
    });
    const grandTotal = withTotals.reduce((sum, row) => sum + row.ratioDenominator, 0);

    return withTotals.map((row) => ({
      ...row,
      share: grandTotal > 0 ? row.ratioDenominator / grandTotal : 0,
    }));
  }, [dayNightRatioMode, overview]);

  const dayNightCoverageRows = useMemo<DayNightCoverageRow[]>(() => {
    if (!overview) return [];
    const dayWindow = Math.max(0, overview.coverage_day_window_seconds || 0);
    const nightWindow = Math.max(0, overview.coverage_night_window_seconds || 0);
    const rows: DayNightCoverageRow[] = [
      {
        period: 'Day',
        windowSeconds: dayWindow,
        modelSeconds: Math.max(0, overview.day_model_coverage_seconds || 0),
        toolSeconds: Math.max(0, overview.day_tool_coverage_seconds || 0),
        userSeconds: Math.max(0, overview.day_user_coverage_seconds || 0),
        modelCoverage: 0,
        toolCoverage: 0,
        userCoverage: 0,
      },
      {
        period: 'Night',
        windowSeconds: nightWindow,
        modelSeconds: Math.max(0, overview.night_model_coverage_seconds || 0),
        toolSeconds: Math.max(0, overview.night_tool_coverage_seconds || 0),
        userSeconds: Math.max(0, overview.night_user_coverage_seconds || 0),
        modelCoverage: 0,
        toolCoverage: 0,
        userCoverage: 0,
      },
    ];

    return rows.map((row) => ({
      ...row,
      modelCoverage: row.windowSeconds > 0 ? clamp01(row.modelSeconds / row.windowSeconds) : 0,
      toolCoverage: row.windowSeconds > 0 ? clamp01(row.toolSeconds / row.windowSeconds) : 0,
      userCoverage: row.windowSeconds > 0 ? clamp01(row.userSeconds / row.windowSeconds) : 0,
    }));
  }, [overview]);

  const leverageEstimate = useMemo(() => {
    if (!overview) {
      return {
        outputBudgetTokens: 0,
        effectiveCodingTokens: 0,
        estimatedCodeLines: 0,
      };
    }

    const normalizedFraction = Number.isFinite(codingFraction) && codingFraction > 0
      ? codingFraction
      : 0;
    const normalizedTokensPerLine = Number.isFinite(tokensPerLine) && tokensPerLine > 0
      ? tokensPerLine
      : 10;
    const outputBudgetTokens =
      overview.total_output_tokens + (overview.total_tool_output_tokens || 0);
    const effectiveCodingTokens = outputBudgetTokens * normalizedFraction;
    const estimatedCodeLines = effectiveCodingTokens / normalizedTokensPerLine;

    return {
      outputBudgetTokens,
      effectiveCodingTokens,
      estimatedCodeLines,
    };
  }, [codingFraction, overview, tokensPerLine]);

  if (isLoading) {
    return (
      <section className="cross-session-overview loading" aria-live="polite">
        <div className="cross-session-skeleton">{t('cross.loading')}</div>
      </section>
    );
  }

  if (errorMessage) {
    return (
      <section className="cross-session-overview error">
        <h3>{t('cross.errorTitle')}</h3>
        <p>{errorMessage}</p>
      </section>
    );
  }

  if (
    !overview ||
    !automationDistribution ||
    !timeseries ||
    !projectComparison ||
    !projectSwimlane
  ) {
    return null;
  }

  const runtime = overview.runtime_plane ?? {
    total_messages: overview.total_messages,
    total_tokens: overview.total_tokens,
    total_tool_calls: overview.total_tool_calls,
    total_input_tokens: overview.total_input_tokens,
    total_output_tokens: overview.total_output_tokens,
    total_tool_output_tokens: overview.total_tool_output_tokens,
    total_cache_read_tokens: overview.total_cache_read_tokens,
    total_cache_creation_tokens: overview.total_cache_creation_tokens,
    total_chars: overview.total_chars,
    total_user_chars: overview.total_user_chars,
    total_model_chars: overview.total_model_chars,
    total_tool_chars: overview.total_tool_chars,
    total_cjk_chars: overview.total_cjk_chars,
    total_latin_chars: overview.total_latin_chars,
    total_other_chars: overview.total_other_chars,
    yield_ratio_tokens_mean: overview.yield_ratio_tokens_mean,
    yield_ratio_tokens_median: overview.yield_ratio_tokens_median,
    yield_ratio_tokens_p90: overview.yield_ratio_tokens_p90,
    yield_ratio_chars_mean: overview.yield_ratio_chars_mean,
    yield_ratio_chars_median: overview.yield_ratio_chars_median,
    yield_ratio_chars_p90: overview.yield_ratio_chars_p90,
    leverage_tokens_mean: overview.leverage_tokens_mean,
    leverage_tokens_median: overview.leverage_tokens_median,
    leverage_tokens_p90: overview.leverage_tokens_p90,
    leverage_chars_mean: overview.leverage_chars_mean,
    leverage_chars_median: overview.leverage_chars_median,
    leverage_chars_p90: overview.leverage_chars_p90,
    avg_tokens_per_second_mean: overview.avg_tokens_per_second_mean,
    avg_tokens_per_second_median: overview.avg_tokens_per_second_median,
    avg_tokens_per_second_p90: overview.avg_tokens_per_second_p90,
    read_tokens_per_second_mean: overview.read_tokens_per_second_mean,
    read_tokens_per_second_median: overview.read_tokens_per_second_median,
    read_tokens_per_second_p90: overview.read_tokens_per_second_p90,
    output_tokens_per_second_mean: overview.output_tokens_per_second_mean,
    output_tokens_per_second_median: overview.output_tokens_per_second_median,
    output_tokens_per_second_p90: overview.output_tokens_per_second_p90,
    cache_tokens_per_second_mean: overview.cache_tokens_per_second_mean,
    cache_tokens_per_second_median: overview.cache_tokens_per_second_median,
    cache_tokens_per_second_p90: overview.cache_tokens_per_second_p90,
    cache_read_tokens_per_second_mean: overview.cache_read_tokens_per_second_mean,
    cache_read_tokens_per_second_median: overview.cache_read_tokens_per_second_median,
    cache_read_tokens_per_second_p90: overview.cache_read_tokens_per_second_p90,
    cache_creation_tokens_per_second_mean: overview.cache_creation_tokens_per_second_mean,
    cache_creation_tokens_per_second_median: overview.cache_creation_tokens_per_second_median,
    cache_creation_tokens_per_second_p90: overview.cache_creation_tokens_per_second_p90,
    avg_automation_ratio: overview.avg_automation_ratio,
    avg_session_duration_seconds: overview.avg_session_duration_seconds,
    model_time_seconds: overview.model_time_seconds,
    tool_time_seconds: overview.tool_time_seconds,
    user_time_seconds: overview.user_time_seconds,
    inactive_time_seconds: overview.inactive_time_seconds,
    day_model_time_seconds: overview.day_model_time_seconds,
    day_tool_time_seconds: overview.day_tool_time_seconds,
    day_user_time_seconds: overview.day_user_time_seconds,
    day_inactive_time_seconds: overview.day_inactive_time_seconds,
    night_model_time_seconds: overview.night_model_time_seconds,
    night_tool_time_seconds: overview.night_tool_time_seconds,
    night_user_time_seconds: overview.night_user_time_seconds,
    night_inactive_time_seconds: overview.night_inactive_time_seconds,
    coverage_total_window_seconds: overview.coverage_total_window_seconds,
    coverage_day_window_seconds: overview.coverage_day_window_seconds,
    coverage_night_window_seconds: overview.coverage_night_window_seconds,
    day_model_coverage_seconds: overview.day_model_coverage_seconds,
    day_tool_coverage_seconds: overview.day_tool_coverage_seconds,
    day_user_coverage_seconds: overview.day_user_coverage_seconds,
    night_model_coverage_seconds: overview.night_model_coverage_seconds,
    night_tool_coverage_seconds: overview.night_tool_coverage_seconds,
    night_user_coverage_seconds: overview.night_user_coverage_seconds,
    active_time_ratio: overview.active_time_ratio,
    model_timeout_count: overview.model_timeout_count,
    source_breakdown: overview.source_breakdown,
    role_source_breakdown: overview.role_source_breakdown ?? [],
    primary_bottleneck_key: overview.primary_bottleneck_key ?? null,
    primary_bottleneck_label: overview.primary_bottleneck_label ?? null,
    primary_bottleneck_source: overview.primary_bottleneck_source ?? null,
    primary_bottleneck_role: overview.primary_bottleneck_role ?? null,
    bottleneck_distribution: overview.bottleneck_distribution,
    top_projects: overview.top_projects,
    top_tools: overview.top_tools,
  };

  const control = overview.control_plane ?? {
    logical_sessions: overview.total_sessions,
    physical_sessions: overview.total_sessions,
    files: {
      total_files: 0,
      parsed_files: 0,
      error_files: 0,
      pending_files: 0,
      total_tracked_file_size_bytes: 0,
      total_trajectory_file_size_bytes: overview.total_trajectory_file_size_bytes,
      last_parsed_at: null,
    },
    sync_running: false,
    last_sync: {
      status: 'idle' as const,
      trigger: 'startup' as const,
      started_at: null,
      finished_at: null,
      parsed: 0,
      skipped: 0,
      errors: 0,
      total_files_scanned: 0,
      total_file_size_bytes: 0,
      ecosystems: [],
      error_samples: [],
    },
  };

  const topProjects = runtime.top_projects.slice(0, 8);
  const topTools = runtime.top_tools.slice(0, 8);
  const sourceBreakdown = runtime.source_breakdown || [];
  const capabilityIndex = buildCapabilityIndex(capabilitiesQuery.data);
  const sourcePresentation = Object.fromEntries(
    sourceBreakdown.map((source) => [
      source.ecosystem,
      getEcosystemPresentation(source.ecosystem, capabilityIndex),
    ])
  );
  const sourceFilterOptions = sourceBreakdown.map((source) => {
    const present = sourcePresentation[source.ecosystem];
    return {
      ecosystem: source.ecosystem,
      label: present?.label || source.label || source.ecosystem,
      color: present?.color || '#94a3b8',
    };
  });
  const sourceBreakdownDisplay = sourceBreakdown.map((source) => ({
    ...source,
    label:
      sourcePresentation[source.ecosystem]?.label || source.label || source.ecosystem,
    color: sourcePresentation[source.ecosystem]?.color || '#94a3b8',
  }));
  const selectedCapability =
    sourceFilter !== 'all' && sourceFilter ? capabilityIndex[sourceFilter] : undefined;
  const capabilityNotices = deriveCapabilityNotices(selectedCapability);
  const roleSourceBreakdown = runtime.role_source_breakdown;
  const roleSourceMetricLabel =
    roleSourceMetric === 'tokens'
      ? t('table.tokens')
      : roleSourceMetric === 'tool_calls'
        ? t('cross.callVolume')
        : roleSourceMetric === 'errors'
          ? t('cross.errors')
          : t('cross.activeTime');
  const roleSourcePrimary = runtime.primary_bottleneck_label || t('table.unknown');
  const roleSourceBySource = (() => {
    const grouped = new Map<
      string,
      {
        label: string;
        roleValues: Record<'user' | 'model' | 'tool', number>;
        total: number;
      }
    >();
    for (const row of roleSourceBreakdown) {
      const existing = grouped.get(row.ecosystem) ?? {
        label:
          sourcePresentation[row.ecosystem]?.label || row.ecosystem_label || row.ecosystem,
        roleValues: { user: 0, model: 0, tool: 0 },
        total: 0,
      };
      const value = metricValue(row, roleSourceMetric);
      existing.roleValues[row.role] += value;
      existing.total += value;
      grouped.set(row.ecosystem, existing);
    }

    return Array.from(grouped.entries())
      .map(([ecosystem, value]) => ({
        ecosystem,
        label: value.label,
        user: value.roleValues.user,
        model: value.roleValues.model,
        tool: value.roleValues.tool,
        total: value.total,
      }))
      .sort((a, b) => b.total - a.total);
  })();
  const roleSourceByRole = (() => {
    const grouped = new Map<
      string,
      {
        roleLabel: string;
        ecosystemValues: Record<string, number>;
        total: number;
      }
    >();
    for (const row of roleSourceBreakdown) {
      const existing = grouped.get(row.role) ?? {
        roleLabel: row.role_label,
        ecosystemValues: {},
        total: 0,
      };
      const value = metricValue(row, roleSourceMetric);
      existing.ecosystemValues[row.ecosystem] =
        (existing.ecosystemValues[row.ecosystem] ?? 0) + value;
      existing.total += value;
      grouped.set(row.role, existing);
    }

    return Array.from(grouped.entries())
      .map(([role, value]) => ({
        role,
        roleLabel: value.roleLabel,
        ...value.ecosystemValues,
        total: value.total,
      }))
      .sort((a, b) => b.total - a.total);
  })();
  const roleSourceTotal = roleSourceBreakdown.reduce(
    (sum, row) => sum + metricValue(row, roleSourceMetric),
    0
  );
  const roleSourceTableRows = roleSourceBreakdown
    .map((row) => {
      const value = metricValue(row, roleSourceMetric);
      const share = roleSourceTotal > 0 ? value / roleSourceTotal : 0;
      return {
        ...row,
        ecosystem_label:
          sourcePresentation[row.ecosystem]?.label || row.ecosystem_label || row.ecosystem,
        value,
        share,
      };
    })
    .sort((a, b) => b.value - a.value);
  const comparisonProjects = projectComparison.projects;
  const defaultProjectPaths = comparisonProjects.slice(0, 3).map((project) => project.project_path);
  const selectedProjectPaths = comparisonProjects
    .filter((project) => {
      const overridden = projectSelection[project.project_path];
      if (typeof overridden === 'boolean') {
        return overridden;
      }
      return defaultProjectPaths.includes(project.project_path);
    })
    .map((project) => project.project_path);
  const selectedComparisonProjects = comparisonProjects.filter((project) =>
    selectedProjectPaths.includes(project.project_path)
  );
  const swimlaneProjects = projectSwimlane.projects.filter((project) =>
    selectedProjectPaths.includes(project.project_path)
  );
  const periodIndexMap = new Map<string, number>();
  projectSwimlane.periods.forEach((period, index) => {
    periodIndexMap.set(period, index);
  });

  const ganttRows = swimlaneProjects.map((project) => {
    const sortedPoints = projectSwimlane.points
      .filter((point) => point.project_path === project.project_path)
      .sort((a, b) => (periodIndexMap.get(a.period) ?? -1) - (periodIndexMap.get(b.period) ?? -1));

    type TimelineSegment = {
      project_path: string;
      project_name: string;
      startPeriod: string;
      endPeriod: string;
      startIndex: number;
      endIndex: number;
      totalTokens: number;
      totalSessions: number;
      activeRatioSum: number;
      activeRatioCount: number;
      leverageSum: number;
      leverageCount: number;
    };

    const segments: TimelineSegment[] = [];
    let current: TimelineSegment | null = null;

    const flushSegment = () => {
      if (current) {
        segments.push(current);
      }
      current = null;
    };

    for (const point of sortedPoints) {
      const index = periodIndexMap.get(point.period);
      if (index === undefined) {
        continue;
      }

      if (!current) {
        current = {
          project_path: point.project_path,
          project_name: point.project_name,
          startPeriod: point.period,
          endPeriod: point.period,
          startIndex: index,
          endIndex: index,
          totalTokens: point.tokens,
          totalSessions: point.sessions,
          activeRatioSum: point.active_ratio,
          activeRatioCount: 1,
          leverageSum: point.leverage_tokens_mean ?? 0,
          leverageCount: point.leverage_tokens_mean === null ? 0 : 1,
        };
        continue;
      }

      if (index === current.endIndex + 1) {
        current.endIndex = index;
        current.endPeriod = point.period;
        current.totalTokens += point.tokens;
        current.totalSessions += point.sessions;
        current.activeRatioSum += point.active_ratio;
        current.activeRatioCount += 1;
        if (point.leverage_tokens_mean !== null) {
          current.leverageSum += point.leverage_tokens_mean;
          current.leverageCount += 1;
        }
        continue;
      }

      flushSegment();
      current = {
        project_path: point.project_path,
        project_name: point.project_name,
        startPeriod: point.period,
        endPeriod: point.period,
        startIndex: index,
        endIndex: index,
        totalTokens: point.tokens,
        totalSessions: point.sessions,
        activeRatioSum: point.active_ratio,
        activeRatioCount: 1,
        leverageSum: point.leverage_tokens_mean ?? 0,
        leverageCount: point.leverage_tokens_mean === null ? 0 : 1,
      };
    }

    flushSegment();

    return {
      project,
      segments,
    };
  }).filter((row) => row.segments.length > 0);

  const ganttMaxTokens = ganttRows.length > 0
    ? Math.max(...ganttRows.flatMap((row) => row.segments.map((segment) => segment.totalTokens)))
    : 0;
  const roleSourceAxisMax = roleSourceTableRows.reduce(
    (maxValue, row) => Math.max(maxValue, Math.abs(row.value)),
    0
  );
  const roleSourceTimeTickFormatter = createTimeAxisTickFormatter(roleSourceAxisMax);
  const dayNightAxisMax = dayNightRows.reduce(
    (maxValue, row) =>
      Math.max(
        maxValue,
        Math.abs(row.model),
        Math.abs(row.tool),
        Math.abs(row.user),
        Math.abs(row.inactive),
        Math.abs(row.total),
        Math.abs(row.ratioDenominator)
      ),
    0
  );
  const dayNightTimeTickFormatter = createTimeAxisTickFormatter(dayNightAxisMax);

  const toggleProjectSelection = (projectPath: string) => {
    setProjectSelection((prev) => {
      const currentlySelected = selectedProjectPaths.includes(projectPath);
      return { ...prev, [projectPath]: !currentlySelected };
    });
  };

  const ganttLabelWidth = 170;
  const ganttCellWidth = projectTimelineInterval === 'week' ? 92 : 66;
  const ganttRowHeight = 36;
  const ganttAxisHeight = 30;
  const ganttChartWidth = ganttLabelWidth + projectSwimlane.periods.length * ganttCellWidth + 16;
  const ganttChartHeight = ganttAxisHeight + ganttRows.length * ganttRowHeight + 14;
  const ganttTickStep = Math.max(1, Math.ceil(projectSwimlane.periods.length / 8));

  return (
    <section className="cross-session-overview" aria-label="Cross session overview">
      <div className="cross-session-header">
        <div>
          <h3>{t('cross.title')}</h3>
          <p>{t('cross.subtitle')}</p>
        </div>

        <div className="cross-session-controls">
          <div className="preset-buttons" role="tablist" aria-label="Time window presets">
            <button
              type="button"
              className={preset === '7d' ? 'active' : ''}
              onClick={() => {
                setPreset('7d');
                setProjectTimelineInterval('day');
              }}
            >
              {t('cross.preset.days7')}
            </button>
            <button
              type="button"
              className={preset === '30d' ? 'active' : ''}
              onClick={() => setPreset('30d')}
            >
              {t('cross.preset.days30')}
            </button>
            <button
              type="button"
              className={preset === '90d' ? 'active' : ''}
              onClick={() => {
                setPreset('90d');
                setProjectTimelineInterval('week');
              }}
            >
              {t('cross.preset.days90')}
            </button>
            <button
              type="button"
              className={preset === 'custom' ? 'active' : ''}
              onClick={() => setPreset('custom')}
            >
              {t('cross.preset.custom')}
            </button>
          </div>

          {preset === 'custom' && (
            <div className="custom-range-inputs">
              <label>
                {t('dateRange.from')}
                <input
                  type="date"
                  value={customRange.startDate ?? ''}
                  onChange={(event) =>
                    setCustomRange((prev) => ({
                      ...prev,
                      startDate: event.target.value || null,
                    }))
                  }
                />
              </label>
              <label>
                {t('dateRange.to')}
                <input
                  type="date"
                  value={customRange.endDate ?? ''}
                  onChange={(event) =>
                    setCustomRange((prev) => ({
                      ...prev,
                      endDate: event.target.value || null,
                    }))
                  }
                />
              </label>
            </div>
          )}

          <div className="source-filter-group" role="group" aria-label={t('cross.sourceFilter')}>
            <button
              type="button"
              className={sourceFilter === 'all' ? 'active' : ''}
              onClick={() => setSourceFilter('all')}
              data-testid="source-filter-all"
            >
              {t('cross.sourceAll')}
            </button>
            {sourceFilterOptions.map((source) => (
              <button
                key={source.ecosystem}
                type="button"
                className={sourceFilter === source.ecosystem ? 'active' : ''}
                onClick={() => setSourceFilter(source.ecosystem)}
                data-testid={sourceFilterTestId(source.ecosystem)}
              >
                {source.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {capabilityNotices.length > 0 && (
        <section className="overview-card capability-notes" data-testid="cross-capability-notes">
          <h4>{t('cross.plane.runtime.title')} - Capability Notes</h4>
          <div className="capability-notes-grid">
            {capabilityNotices.map((notice) => (
              <div
                key={notice.id}
                className={`capability-note capability-note--${notice.severity}`}
                title={notice.reason}
              >
                <strong>{notice.label}</strong>
                <span>{notice.reason}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="plane-section plane-section--control" aria-label={t('cross.plane.control.title')}>
        <div className="plane-section__header">
          <h4>{t('cross.plane.control.title')}</h4>
          <p>{t('cross.plane.control.subtitle')}</p>
        </div>
        <div className="control-plane-grid">
          <article className="overview-card control-plane-card">
            <h4>{t('cross.control.syncStatus')}</h4>
            <p>
              {t('sync.lastSync')}
              : {control.last_sync.finished_at ? formatDate(control.last_sync.finished_at) : t('sync.never')}
            </p>
            <p>
              {t('cross.control.syncStatus')}
              : {control.last_sync.status}
            </p>
            <p>
              {t('sync.summary.parsed')}
              /{t('sync.summary.skipped')}
              /{t('sync.summary.errors')}
              : {formatNumber(control.last_sync.parsed)}
              /{formatNumber(control.last_sync.skipped)}
              /{formatNumber(control.last_sync.errors)}
            </p>
          </article>

          <article className="overview-card control-plane-card">
            <h4>{t('sync.summary.files')}</h4>
            <p>
              {formatNumber(control.files.total_files)}
              {' '}
              {t('sync.filesSuffix')}
            </p>
            <p>
              {t('sync.summary.size')}
              : {formatBytes(control.files.total_tracked_file_size_bytes)}
            </p>
            <p>
              {t('cross.kpi.trajectorySize')}
              : {formatBytes(control.files.total_trajectory_file_size_bytes)}
            </p>
          </article>

          <article className="overview-card control-plane-card">
            <h4>{t('cross.control.parseStatus')}</h4>
            <p>
              {t('sync.summary.parsed')}
              : {formatNumber(control.files.parsed_files)}
            </p>
            <p>
              {t('sync.summary.errors')}
              : {formatNumber(control.files.error_files)}
            </p>
            <p>
              {t('cross.control.pending')}
              : {formatNumber(control.files.pending_files)}
            </p>
          </article>

          <article className="overview-card control-plane-card">
            <h4>{t('cross.control.sessionScope')}</h4>
            <p>
              {t('cross.control.logicalSessions')}
              : {formatNumber(control.logical_sessions)}
            </p>
            <p>
              {t('cross.control.physicalSessions')}
              : {formatNumber(control.physical_sessions)}
            </p>
          </article>
        </div>
      </section>

      <section className="plane-section plane-section--runtime" aria-label={t('cross.plane.runtime.title')}>
        <div className="plane-section__header">
          <h4>{t('cross.plane.runtime.title')}</h4>
          <p>{t('cross.plane.runtime.subtitle')}</p>
        </div>

      <div className="kpi-grid">
        <article className="kpi-card">
          <h4>{t('cross.kpi.totalSessions')}</h4>
          <div className="kpi-value">{formatNumber(control.logical_sessions)}</div>
          <p>
            <MetricTerm metricId="bottleneck">{t('cross.kpi.primaryBottleneck')}</MetricTerm>
            : {getLeadingBucket(runtime.bottleneck_distribution)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>{t('cross.kpi.automationEfficiency')}</h4>
          <div className="kpi-value">{runtime.avg_automation_ratio.toFixed(2)}x</div>
          <p>
            <MetricTerm metricId="active_ratio">{t('cross.kpi.activeRatio')}</MetricTerm>
            : {formatPercentPoint(runtime.active_time_ratio)}
          </p>
          <p>
            <MetricTerm metricId="leverage">{t('cross.kpi.tokenLeverage')}</MetricTerm>
            : {formatLeverage(
              runtime.leverage_tokens_mean ?? runtime.yield_ratio_tokens_mean
            )} /
            {' '}
            {formatLeverage(runtime.leverage_tokens_median ?? runtime.yield_ratio_tokens_median)} /
            {' '}
            {formatLeverage(runtime.leverage_tokens_p90 ?? runtime.yield_ratio_tokens_p90)}
          </p>
          <p>
            <MetricTerm metricId="yield">{t('cross.kpi.charLeverage')}</MetricTerm>
            : {formatLeverage(
              runtime.leverage_chars_mean ?? runtime.yield_ratio_chars_mean
            )} /
            {' '}
            {formatLeverage(runtime.leverage_chars_median ?? runtime.yield_ratio_chars_median)} /
            {' '}
            {formatLeverage(runtime.leverage_chars_p90 ?? runtime.yield_ratio_chars_p90)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>{t('cross.kpi.tokenVolume')}</h4>
          <div className="kpi-value" title={formatNumber(runtime.total_tokens)}>
            {formatTokenCount(runtime.total_tokens)}
          </div>
          <p>
            {t('cross.kpi.inputOutput')}
            : <span title={formatNumber(runtime.total_input_tokens)}>
              {formatTokenCount(runtime.total_input_tokens)}
            </span>
            {' / '}
            <span title={formatNumber(runtime.total_output_tokens)}>
              {formatTokenCount(runtime.total_output_tokens)}
            </span>
          </p>
          <p>
            {t('cross.kpi.trajectorySize')}
            : {formatNumber(control.files.total_trajectory_file_size_bytes)}
            {' '}
            {t('cross.kpi.bytes')}
          </p>
          <p>
            {t('cross.kpi.charsCjkLatin')}
            : {formatNumber(runtime.total_cjk_chars)}
            {' / '}
            {formatNumber(runtime.total_latin_chars)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>{t('cross.kpi.toolExecution')}</h4>
          <div className="kpi-value">{formatNumber(runtime.total_tool_calls)}</div>
          <p>
            {t('cross.kpi.avgSessionDuration')}
            : {formatDuration(runtime.avg_session_duration_seconds)} ·
            {' '}
            {t('cross.kpi.modelTimeouts')}
            : {formatNumber(runtime.model_timeout_count)}
          </p>
          <p>
            <MetricTerm metricId="tokens_per_second">{t('cross.kpi.modelTokS')}</MetricTerm>
            : {runtime.avg_tokens_per_second_mean.toFixed(2)} /
            {' '}
            {runtime.avg_tokens_per_second_median.toFixed(2)} /
            {' '}
            {runtime.avg_tokens_per_second_p90.toFixed(2)}
          </p>
          <p>
            <MetricTerm metricId="tokens_per_second">{t('cross.kpi.readOutputTokS')}</MetricTerm>
            : {runtime.read_tokens_per_second_mean.toFixed(2)}
            {' / '}
            {runtime.output_tokens_per_second_mean.toFixed(2)}
          </p>
          <p>
            <MetricTerm metricId="tokens_per_second">{t('cross.kpi.cacheTokS')}</MetricTerm>
            : {runtime.cache_tokens_per_second_mean.toFixed(2)}
            {' ('}
            {runtime.cache_read_tokens_per_second_mean.toFixed(2)}
            {' / '}
            {runtime.cache_creation_tokens_per_second_mean.toFixed(2)}
            {')'}
          </p>
        </article>

        <article className="kpi-card leverage-estimator-card">
          <h4>{t('cross.kpi.codeCapacity')}</h4>
          <div className="kpi-value">{formatNumber(Math.round(leverageEstimate.estimatedCodeLines))}</div>
          <p>{t('cross.kpi.codeCapacityHint')}</p>
          <div className="leverage-controls">
            <label>
              {t('cross.kpi.codingTokenFraction')}
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={codingFraction}
                onChange={(event) => setCodingFraction(Number(event.target.value))}
              />
            </label>
            <label>
              {t('cross.kpi.tokensPerLoc')}
              <input
                type="number"
                min={1}
                step={1}
                value={tokensPerLine}
                onChange={(event) => setTokensPerLine(Number(event.target.value))}
              />
            </label>
          </div>
          <p>
            {t('cross.kpi.inputs')}
            : <span title={formatNumber(leverageEstimate.outputBudgetTokens)}>
              {formatTokenCount(leverageEstimate.outputBudgetTokens)}
            </span>
            {' '}
            {t('cross.kpi.outputTokens')}
            , 
            {' '}
            {t('cross.kpi.effectiveCodingTokens', {
              values: { value: formatTokenCount(Math.round(leverageEstimate.effectiveCodingTokens)) },
            })}
          </p>
          <p className="leverage-note">
            {t('cross.kpi.estimateOnly')}
          </p>
        </article>
      </div>

      <div className="overview-grid">
        <section className="overview-card role-source-card">
          <div className="role-source-header">
            <div>
              <h4>{t('cross.roleSource.title')}</h4>
              <p className="role-source-note">
                {t('cross.roleSource.subtitle')}
              </p>
              <p className="role-source-bottleneck" data-testid="role-source-primary-bottleneck">
                {t('cross.roleSource.primary')}
                : {roleSourcePrimary}
              </p>
            </div>
            <div className="role-source-controls">
              <div className="role-source-control-group" role="group" aria-label={t('cross.roleSource.metric')}>
                <button
                  type="button"
                  className={roleSourceMetric === 'time' ? 'active' : ''}
                  onClick={() => setRoleSourceMetric('time')}
                  data-testid="role-source-metric-time"
                >
                  {t('cross.activeTime')}
                </button>
                <button
                  type="button"
                  className={roleSourceMetric === 'tokens' ? 'active' : ''}
                  onClick={() => setRoleSourceMetric('tokens')}
                  data-testid="role-source-metric-tokens"
                >
                  {t('table.tokens')}
                </button>
                <button
                  type="button"
                  className={roleSourceMetric === 'tool_calls' ? 'active' : ''}
                  onClick={() => setRoleSourceMetric('tool_calls')}
                  data-testid="role-source-metric-calls"
                >
                  {t('cross.callVolume')}
                </button>
                <button
                  type="button"
                  className={roleSourceMetric === 'errors' ? 'active' : ''}
                  onClick={() => setRoleSourceMetric('errors')}
                  data-testid="role-source-metric-errors"
                >
                  {t('cross.errors')}
                </button>
              </div>
              <div className="role-source-control-group" role="group" aria-label={t('cross.roleSource.dimension')}>
                <button
                  type="button"
                  className={roleSourceView === 'source' ? 'active' : ''}
                  onClick={() => setRoleSourceView('source')}
                  data-testid="role-source-dimension-source"
                >
                  {t('cross.roleSource.bySource')}
                </button>
                <button
                  type="button"
                  className={roleSourceView === 'role' ? 'active' : ''}
                  onClick={() => setRoleSourceView('role')}
                  data-testid="role-source-dimension-role"
                >
                  {t('cross.roleSource.byRole')}
                </button>
              </div>
            </div>
          </div>

          {roleSourceBreakdown.length === 0 ? (
            <p className="empty-hint" data-testid="role-source-empty">{t('cross.roleSource.empty')}</p>
          ) : (
            <div className="role-source-layout">
              <div className="role-source-chart" data-testid="role-source-chart">
                <ResponsiveContainer width="100%" height={300}>
                  <BarChart
                    data={roleSourceView === 'source' ? roleSourceBySource : roleSourceByRole}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey={roleSourceView === 'source' ? 'label' : 'roleLabel'} />
                    <YAxis
                      tickFormatter={(value) => {
                        if (roleSourceMetric === 'tokens') {
                          return formatTokenAxisTick(value);
                        }
                        if (roleSourceMetric === 'time') {
                          return roleSourceTimeTickFormatter(value);
                        }
                        return formatNumber(Number(value));
                      }}
                    />
                    <Tooltip
                      formatter={(value) => {
                        const numeric = Number(value ?? 0);
                        if (roleSourceMetric === 'tokens') {
                          return formatTokenTooltip(numeric);
                        }
                        if (roleSourceMetric === 'time') {
                          return `${roleSourceTimeTickFormatter(numeric)} (${formatDuration(numeric)})`;
                        }
                        return formatNumber(numeric);
                      }}
                    />
                    <Legend />
                    {roleSourceView === 'source' ? (
                      <>
                        <Bar dataKey="model" stackId="role" fill={ROLE_COLORS.model} name={t('cross.model')} />
                        <Bar dataKey="tool" stackId="role" fill={ROLE_COLORS.tool} name={t('cross.tool')} />
                        <Bar dataKey="user" stackId="role" fill={ROLE_COLORS.user} name={t('cross.user')} />
                      </>
                    ) : (
                      sourceBreakdownDisplay.map((source) => (
                        <Bar
                          key={source.ecosystem}
                          dataKey={source.ecosystem}
                          stackId="source"
                          fill={source.color}
                          name={source.label}
                        />
                      ))
                    )}
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="table-wrapper">
                <table className="compact-table role-source-table" data-testid="role-source-table">
                  <thead>
                    <tr>
                      <th>{t('table.ecosystem')}</th>
                      <th>{t('cross.roleSource.role')}</th>
                      <th>{roleSourceMetricLabel}</th>
                      <th>{t('cross.share')}</th>
                      <th>{t('cross.activeTime')}</th>
                      <th>{t('table.tokens')}</th>
                      <th>{t('cross.callVolume')}</th>
                      <th>{t('cross.errors')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {roleSourceTableRows.map((row) => (
                      <tr key={row.key} data-testid={`role-source-row-${row.key}`}>
                        <td>
                          <span className="role-source-tag role-source-tag--source">
                            {row.ecosystem_label}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`role-source-tag role-source-tag--role role-source-tag--role-${row.role}`}
                          >
                            {row.role_label}
                          </span>
                        </td>
                        <td>
                          {roleSourceMetric === 'time'
                            ? formatDuration(row.value)
                            : roleSourceMetric === 'tokens'
                              ? formatTokenCount(row.value)
                              : formatNumber(row.value)}
                        </td>
                        <td>{formatPercentPoint(row.share)}</td>
                        <td>{formatDuration(row.time_seconds)}</td>
                        <td>{formatTokenCount(row.token_count)}</td>
                        <td>{formatNumber(row.tool_calls)}</td>
                        <td>{formatNumber(row.error_count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      </div>

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>{t('cross.sourceDistribution')}</h4>
          {sourceBreakdown.length === 0 ? (
            <p className="empty-hint">{t('cross.noSourceData')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={sourceBreakdownDisplay}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis tickFormatter={formatTokenAxisTick} />
                <Tooltip
                  formatter={(value, name) => {
                    const numeric = Number(value);
                    return String(name).toLowerCase().includes('token')
                      ? formatTokenTooltip(numeric)
                      : formatNumber(numeric);
                  }}
                />
                <Legend />
                <Bar dataKey="sessions" fill="#2563eb" name={t('cross.sessions')} />
                <Bar dataKey="total_tokens" fill="#ea580c" name={t('table.tokens')} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="overview-card">
          <h4>{t('cross.sourceComparisonTable')}</h4>
          {sourceBreakdown.length === 0 ? (
            <p className="empty-hint">{t('cross.noSourceData')}</p>
          ) : (
            <div className="table-wrapper">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>{t('table.ecosystem')}</th>
                    <th>{t('cross.sessions')}</th>
                    <th>{t('cross.tokenShare')}</th>
                    <th>{t('cross.callVolume')}</th>
                    <th>{t('cross.activeTime')}</th>
                  </tr>
                </thead>
                <tbody>
                  {sourceBreakdownDisplay.map((source) => (
                    <tr key={source.ecosystem}>
                      <td>{source.label}</td>
                      <td>{formatNumber(source.sessions)}</td>
                      <td>{formatPercentRatio(source.percent_tokens)}</td>
                      <td>{formatNumber(source.total_tool_calls)}</td>
                      <td>{formatDuration(source.active_time_seconds)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <div className="overview-grid">
        <section className="overview-card day-night-card">
          <h4>{t('cross.dayNightMix')}</h4>
          <p className="day-night-note">{t('cross.dayNightWindow')}</p>
          <p className="day-night-explain">{t('cross.dayNightExplain')}</p>
          <div className="day-night-ratio-toggle" role="group" aria-label={t('cross.ratioDenominator')}>
            <span className="day-night-ratio-label">{t('cross.ratioDenominator')}</span>
            <button
              type="button"
              className={dayNightRatioMode === 'include_inactive' ? 'active' : ''}
              onClick={() => setDayNightRatioMode('include_inactive')}
            >
              {t('cross.ratio.includeInactive')}
            </button>
            <button
              type="button"
              className={dayNightRatioMode === 'exclude_inactive' ? 'active' : ''}
              onClick={() => setDayNightRatioMode('exclude_inactive')}
            >
              {t('cross.ratio.excludeInactive')}
            </button>
          </div>
          <p className="day-night-summary">
            {t('cross.dayTotal')}
            : {formatDuration(dayNightRows[0]?.total ?? 0)}
            {' · '}
            {t('cross.nightTotal')}
            : {formatDuration(dayNightRows[1]?.total ?? 0)}
          </p>

          {dayNightRows.length === 0 || dayNightRows.every((row) => row.total <= 0) ? (
            <p className="empty-hint">{t('cross.noDayNight')}</p>
          ) : (
            <div className="day-night-layout">
              <div className="day-night-chart" aria-label="Day night time chart">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={dayNightRows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis
                      dataKey="period"
                      tickFormatter={(value: string) =>
                        value === 'Day' ? t('cross.period.day') : t('cross.period.night')
                      }
                    />
                    <YAxis tickFormatter={dayNightTimeTickFormatter} />
                    <Tooltip
                      formatter={(value, name, item) => {
                        const numeric = Number(value);
                        const payload = (item as { payload?: DayNightRow; dataKey?: string })?.payload;
                        const dataKey = (item as { dataKey?: string })?.dataKey;
                        if (!payload || !Number.isFinite(numeric)) {
                          return formatDuration(Number.isFinite(numeric) ? numeric : 0);
                        }
                        if (dayNightRatioMode === 'exclude_inactive' && dataKey === 'inactive') {
                          return [formatDuration(numeric), name];
                        }
                        const denominator = payload.ratioDenominator;
                        const ratio = denominator > 0 ? numeric / denominator : 0;
                        return [`${formatDuration(numeric)} (${formatPercentPoint(ratio)})`, name];
                      }}
                      labelFormatter={(label) =>
                        `${label === 'Day' ? t('cross.period.day') : t('cross.period.night')} ${t('cross.period')}`
                      }
                    />
                    <Legend />
                    <Bar dataKey="model" stackId="total" name={t('cross.model')} fill="#2563eb" />
                    <Bar dataKey="tool" stackId="total" name={t('cross.tool')} fill="#0891b2" />
                    <Bar dataKey="user" stackId="total" name={t('cross.user')} fill="#ea580c" />
                    <Bar dataKey="inactive" stackId="total" name={t('cross.inactive')} fill="#94a3b8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="table-wrapper">
                <table className="compact-table day-night-table">
                  <thead>
                    <tr>
                      <th>{t('cross.period')}</th>
                      <th>{t('cross.model')}</th>
                      <th>{t('cross.tool')}</th>
                      <th>{t('cross.user')}</th>
                      <th>{t('cross.inactive')}</th>
                      <th>{t('cross.total')}</th>
                      <th>{t('cross.share')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dayNightRows.map((row) => (
                      <tr key={row.period}>
                        <td>{row.period === 'Day' ? t('cross.period.day') : t('cross.period.night')}</td>
                        <td>{formatDuration(row.model)}</td>
                        <td>{formatDuration(row.tool)}</td>
                        <td>{formatDuration(row.user)}</td>
                        <td>{formatDuration(row.inactive)}</td>
                        <td>{formatDuration(row.ratioDenominator)}</td>
                        <td>{formatPercentPoint(row.share)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="table-wrapper">
            <h5 className="day-night-coverage-title">{t('cross.coverageTableTitle')}</h5>
            <p className="day-night-coverage-note">{t('cross.coverageTableNote')}</p>
            <table className="compact-table day-night-coverage-table">
              <thead>
                <tr>
                  <th>{t('cross.period')}</th>
                  <th>{t('cross.coverageWindow')}</th>
                  <th>{t('cross.model')}</th>
                  <th>{t('cross.tool')}</th>
                  <th>{t('cross.user')}</th>
                </tr>
              </thead>
              <tbody>
                {dayNightCoverageRows.map((row) => (
                  <tr key={`coverage-${row.period}`}>
                    <td>{row.period === 'Day' ? t('cross.period.day') : t('cross.period.night')}</td>
                    <td>{formatDuration(row.windowSeconds)}</td>
                    <td>{`${formatPercentPoint(row.modelCoverage)} · ${formatDuration(row.modelSeconds)}`}</td>
                    <td>{`${formatPercentPoint(row.toolCoverage)} · ${formatDuration(row.toolSeconds)}`}</td>
                    <td>{`${formatPercentPoint(row.userCoverage)} · ${formatDuration(row.userSeconds)}`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>{t('cross.projectComparison')}</h4>
          {comparisonProjects.length === 0 ? (
            <p className="empty-hint">{t('cross.noProjectComparison')}</p>
          ) : (
            <>
              <p className="project-compare-note">
                {t('cross.projectCompareNote')}
              </p>
              <div className="project-chip-group">
                {comparisonProjects.map((project) => (
                  <label key={project.project_path} className="project-chip">
                    <input
                      type="checkbox"
                      checked={selectedProjectPaths.includes(project.project_path)}
                      onChange={() => toggleProjectSelection(project.project_path)}
                    />
                    <span>{project.project_name}</span>
                  </label>
                ))}
              </div>

              {selectedComparisonProjects.length === 0 ? (
                <p className="empty-hint">{t('cross.selectProjectPrompt')}</p>
              ) : (
                <div className="table-wrapper">
                  <table className="compact-table">
                    <thead>
                      <tr>
                        <th>{t('table.project')}</th>
                        <th>{t('cross.sessions')}</th>
                        <th>{t('table.tokens')}</th>
                        <th><MetricTerm metricId="active_ratio">{t('cross.kpi.activeRatio')}</MetricTerm></th>
                        <th><MetricTerm metricId="leverage">{t('cross.kpi.tokenLeverage')}</MetricTerm></th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedComparisonProjects.map((project) => (
                        <tr key={project.project_path}>
                          <td>{project.project_name}</td>
                          <td>{formatNumber(project.sessions)}</td>
                          <td title={formatNumber(project.total_tokens)}>
                            {formatTokenCount(project.total_tokens)}
                          </td>
                          <td>{formatPercentPoint(project.active_ratio)}</td>
                          <td>{formatLeverage(project.leverage_tokens_mean)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </section>

        <section className="overview-card">
          <div className="project-gantt-header">
            <h4>{t('cross.projectGantt')}</h4>
            <div className="project-gantt-granularity" role="group" aria-label={t('cross.ganttGranularity')}>
              <button
                type="button"
                className={projectTimelineInterval === 'day' ? 'active' : ''}
                onClick={() => setProjectTimelineInterval('day')}
              >
                {t('cross.ganttDay')}
              </button>
              <button
                type="button"
                className={projectTimelineInterval === 'week' ? 'active' : ''}
                onClick={() => setProjectTimelineInterval('week')}
              >
                {t('cross.ganttWeek')}
              </button>
            </div>
          </div>
          {projectSwimlane.truncated_project_count > 0 && (
            <p className="project-compare-note">
              {t('cross.projectSwimlaneNote', {
                values: {
                  limit: projectSwimlane.project_limit,
                  hidden: projectSwimlane.truncated_project_count,
                },
              })}
            </p>
          )}
          {projectSwimlane.periods.length === 0 || ganttRows.length === 0 ? (
            <p className="empty-hint">{t('cross.noSwimlane')}</p>
          ) : (
            <div className="gantt-wrapper">
              <svg
                className="project-gantt-chart"
                width={ganttChartWidth}
                height={ganttChartHeight}
                role="img"
                aria-label={t('cross.ganttAria')}
              >
                {projectSwimlane.periods.map((period, index) => {
                  if (index % ganttTickStep !== 0 && index !== projectSwimlane.periods.length - 1) {
                    return null;
                  }
                  const x = ganttLabelWidth + index * ganttCellWidth + ganttCellWidth / 2;
                  return (
                    <text key={`gantt-tick-${period}`} x={x} y={14} textAnchor="middle" className="gantt-axis-label">
                      {formatPeriodLabel(period, projectTimelineInterval, formatDate)}
                    </text>
                  );
                })}

                {projectSwimlane.periods.map((period, index) => {
                  const x = ganttLabelWidth + index * ganttCellWidth;
                  return (
                    <line
                      key={`gantt-grid-${period}`}
                      x1={x}
                      y1={ganttAxisHeight - 2}
                      x2={x}
                      y2={ganttChartHeight - 2}
                      className="gantt-grid-line"
                    />
                  );
                })}
                <line
                  x1={ganttLabelWidth + projectSwimlane.periods.length * ganttCellWidth}
                  y1={ganttAxisHeight - 2}
                  x2={ganttLabelWidth + projectSwimlane.periods.length * ganttCellWidth}
                  y2={ganttChartHeight - 2}
                  className="gantt-grid-line"
                />

                {ganttRows.map((row, rowIndex) => {
                  const yBase = ganttAxisHeight + rowIndex * ganttRowHeight;
                  const labelY = yBase + ganttRowHeight / 2 + 4;
                  return (
                    <g key={row.project.project_path} className="gantt-row">
                      <text x={ganttLabelWidth - 10} y={labelY} textAnchor="end" className="gantt-row-label">
                        {row.project.project_name}
                      </text>
                      {row.segments.map((segment) => {
                        const x = ganttLabelWidth + segment.startIndex * ganttCellWidth + 2;
                        const width = (segment.endIndex - segment.startIndex + 1) * ganttCellWidth - 4;
                        const y = yBase + 6;
                        const height = ganttRowHeight - 12;
                        const avgActiveRatio =
                          segment.activeRatioCount > 0
                            ? segment.activeRatioSum / segment.activeRatioCount
                            : 0;
                        const avgLeverage =
                          segment.leverageCount > 0
                            ? segment.leverageSum / segment.leverageCount
                            : null;
                        return (
                          <g key={`${segment.project_path}-${segment.startPeriod}-${segment.endPeriod}`}>
                            <rect
                              className="gantt-bar"
                              x={x}
                              y={y}
                              width={width}
                              height={height}
                              rx={4}
                              style={{
                                fill: buildSwimlaneColor(segment.totalTokens, ganttMaxTokens),
                              }}
                            >
                              <title>
                                {`Project: ${segment.project_name}\n`}
                                {`Range: ${segment.startPeriod} -> ${segment.endPeriod}\n`}
                                {`Tokens: ${formatTokenTooltip(segment.totalTokens)}\n`}
                                {`Sessions: ${formatNumber(segment.totalSessions)}\n`}
                                {`Active ratio: ${formatPercentPoint(avgActiveRatio)}\n`}
                                {`Token leverage: ${formatLeverage(avgLeverage)}`}
                              </title>
                            </rect>
                            {width > 64 && (
                              <text
                                x={x + 8}
                                y={y + height / 2 + 4}
                                className="gantt-bar-label"
                              >
                                {formatTokenCount(segment.totalTokens)}
                              </text>
                            )}
                          </g>
                        );
                      })}
                    </g>
                  );
                })}
              </svg>
            </div>
          )}
        </section>
      </div>

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>{t('cross.throughputTrend')}</h4>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={timeseries.points}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" />
              <YAxis yAxisId="left" tickFormatter={(value) => formatNumber(Number(value))} />
              <YAxis yAxisId="right" orientation="right" tickFormatter={formatTokenAxisTick} />
              <Tooltip
                formatter={(value, name) => {
                  const numeric = Number(value);
                  return String(name).toLowerCase().includes('token')
                    ? formatTokenTooltip(numeric)
                    : formatNumber(numeric);
                }}
              />
              <Legend />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="sessions"
                stroke="#2563eb"
                fill="#bfdbfe"
                name={t('cross.sessions')}
              />
              <Area
                yAxisId="right"
                type="monotone"
                dataKey="tokens"
                stroke="#ea580c"
                fill="#fed7aa"
                name={t('table.tokens')}
              />
            </AreaChart>
          </ResponsiveContainer>
        </section>

        <section className="overview-card">
          <h4>
            <MetricTerm metricId="bottleneck">{t('cross.bottleneckDistribution')}</MetricTerm>
          </h4>
          {runtime.bottleneck_distribution.length === 0 ? (
            <p className="empty-hint">{t('cross.noBottleneckData')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={runtime.bottleneck_distribution}
                  dataKey="count"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  outerRadius={95}
                  label={({ name, percent }) =>
                    `${name || t('table.unknown')}: ${formatPercentPoint(percent || 0)}`
                  }
                >
                  {runtime.bottleneck_distribution.map((entry, index) => (
                    <Cell key={entry.key} fill={DISTRIBUTION_COLORS[index % DISTRIBUTION_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => formatNumber(Number(value))} />
              </PieChart>
            </ResponsiveContainer>
          )}
        </section>
      </div>

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>{t('cross.automationBands')}</h4>
          {automationDistribution.buckets.length === 0 ? (
            <p className="empty-hint">{t('cross.noAutomationData')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={automationDistribution.buckets}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip formatter={(value) => formatNumber(Number(value))} />
                <Legend />
                <Bar dataKey="count" fill="#2563eb" name={t('cross.sessions')} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="overview-card">
          <h4>{t('cross.topTools')}</h4>
          {topTools.length === 0 ? (
            <p className="empty-hint">{t('cross.noToolData')}</p>
          ) : (
            <div className="table-wrapper">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>{t('cross.tool')}</th>
                    <th>{t('cross.callVolume')}</th>
                    <th>{t('cross.errors')}</th>
                    <th>{t('cross.avgLatency')}</th>
                  </tr>
                </thead>
                <tbody>
                  {topTools.map((tool) => (
                    <tr key={tool.tool_name}>
                      <td>{tool.tool_name}</td>
                      <td>{formatNumber(tool.total_calls)}</td>
                      <td>{formatNumber(tool.error_count)}</td>
                      <td>{tool.avg_latency_seconds.toFixed(2)}s</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>{t('cross.topProjects')}</h4>
          {topProjects.length === 0 ? (
            <p className="empty-hint">{t('cross.noProjectData')}</p>
          ) : (
            <div className="table-wrapper">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>{t('table.project')}</th>
                    <th>{t('cross.sessions')}</th>
                    <th>{t('cross.tokenShare')}</th>
                    <th><MetricTerm metricId="leverage">{t('cross.kpi.tokenLeverage')}</MetricTerm></th>
                    <th><MetricTerm metricId="yield">{t('cross.kpi.charLeverage')}</MetricTerm></th>
                  </tr>
                </thead>
                <tbody>
                  {topProjects.map((project) => (
                    <tr key={project.project_path || project.project_name}>
                      <td>{project.project_name}</td>
                      <td>{formatNumber(project.sessions)}</td>
                      <td>{formatPercentRatio(project.percent_tokens)}</td>
                      <td>{formatLeverage(project.leverage_tokens_mean)}</td>
                      <td>{formatLeverage(project.leverage_chars_mean)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="overview-card">
          <h4>{t('cross.topSessionsByShare')}</h4>
          {topSessionShare.length === 0 ? (
            <p className="empty-hint">{t('cross.noTokenShareData')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={topSessionShare}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" tickFormatter={formatSessionShareLabel} />
                <YAxis />
                <Tooltip formatter={(value) => formatNumber(Number(value))} />
                <Legend />
                <Bar dataKey="percent" fill="#0f766e" name={t('cross.tokenShare')} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>
      </div>
      </section>
    </section>
  );
}
