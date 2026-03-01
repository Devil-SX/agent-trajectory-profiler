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
  useProjectComparisonQuery,
  useProjectSwimlaneQuery,
} from '../hooks/useSessionsQuery';
import type { AnalyticsBucket } from '../types/session';
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
  total: number;
  share: number;
}

const DISTRIBUTION_COLORS = ['#2563eb', '#0891b2', '#ea580c', '#dc2626', '#16a34a', '#7c3aed'];

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

function formatLeverage(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return 'N/A';
  }
  return `${value.toFixed(2)}x`;
}

function formatSessionShareLabel(label: string): string {
  return truncateMiddle(label, 5, 4);
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

export function CrossSessionOverview() {
  const { t, formatNumber, formatTokenCount, formatPercent, formatDate } = useI18n();
  const [preset, setPreset] = useState<RangePreset>('7d');
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
  const formatPercentPoint = (value: number): string => formatPercent(value, 1);
  const formatPercentRatio = (value: number): string => formatPercent(value / 100, 1);
  const formatTokenTooltip = (value: number): string =>
    `${formatTokenCount(value)} (${formatNumber(value)})`;

  const { data: overview, isLoading: overviewLoading, error: overviewError } =
    useAnalyticsOverviewQuery(activeRange.startDate, activeRange.endDate);

  const { data: automationDistribution, isLoading: automationLoading, error: automationError } =
    useAnalyticsDistributionQuery('automation_band', activeRange.startDate, activeRange.endDate);

  const { data: sessionShareDistribution, isLoading: shareLoading, error: shareError } =
    useAnalyticsDistributionQuery('session_token_share', activeRange.startDate, activeRange.endDate);

  const { data: timeseries, isLoading: timeseriesLoading, error: timeseriesError } =
    useAnalyticsTimeseriesQuery(interval, activeRange.startDate, activeRange.endDate);

  const {
    data: projectComparison,
    isLoading: projectComparisonLoading,
    error: projectComparisonError,
  } = useProjectComparisonQuery(activeRange.startDate, activeRange.endDate, 12);

  const {
    data: projectSwimlane,
    isLoading: projectSwimlaneLoading,
    error: projectSwimlaneError,
  } = useProjectSwimlaneQuery(projectTimelineInterval, activeRange.startDate, activeRange.endDate, 12);

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

    const rows: DayNightRow[] = [
      {
        period: 'Day',
        model: overview.day_model_time_seconds,
        tool: overview.day_tool_time_seconds,
        user: overview.day_user_time_seconds,
        inactive: overview.day_inactive_time_seconds,
        total: 0,
        share: 0,
      },
      {
        period: 'Night',
        model: overview.night_model_time_seconds,
        tool: overview.night_tool_time_seconds,
        user: overview.night_user_time_seconds,
        inactive: overview.night_inactive_time_seconds,
        total: 0,
        share: 0,
      },
    ];

    const withTotals = rows.map((row) => ({
      ...row,
      total: row.model + row.tool + row.user + row.inactive,
    }));
    const grandTotal = withTotals.reduce((sum, row) => sum + row.total, 0);

    return withTotals.map((row) => ({
      ...row,
      share: grandTotal > 0 ? row.total / grandTotal : 0,
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

  const topProjects = overview.top_projects.slice(0, 8);
  const topTools = overview.top_tools.slice(0, 8);
  const sourceBreakdown = overview.source_breakdown || [];
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
        </div>
      </div>

      <div className="kpi-grid">
        <article className="kpi-card">
          <h4>{t('cross.kpi.totalSessions')}</h4>
          <div className="kpi-value">{formatNumber(overview.total_sessions)}</div>
          <p>
            <MetricTerm metricId="bottleneck">{t('cross.kpi.primaryBottleneck')}</MetricTerm>
            : {getLeadingBucket(overview.bottleneck_distribution)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>{t('cross.kpi.automationEfficiency')}</h4>
          <div className="kpi-value">{overview.avg_automation_ratio.toFixed(2)}x</div>
          <p>
            <MetricTerm metricId="active_ratio">{t('cross.kpi.activeRatio')}</MetricTerm>
            : {formatPercentPoint(overview.active_time_ratio)}
          </p>
          <p>
            <MetricTerm metricId="leverage">{t('cross.kpi.tokenLeverage')}</MetricTerm>
            : {formatLeverage(
              overview.leverage_tokens_mean ?? overview.yield_ratio_tokens_mean
            )} /
            {' '}
            {formatLeverage(overview.leverage_tokens_median ?? overview.yield_ratio_tokens_median)} /
            {' '}
            {formatLeverage(overview.leverage_tokens_p90 ?? overview.yield_ratio_tokens_p90)}
          </p>
          <p>
            <MetricTerm metricId="yield">{t('cross.kpi.charLeverage')}</MetricTerm>
            : {formatLeverage(
              overview.leverage_chars_mean ?? overview.yield_ratio_chars_mean
            )} /
            {' '}
            {formatLeverage(overview.leverage_chars_median ?? overview.yield_ratio_chars_median)} /
            {' '}
            {formatLeverage(overview.leverage_chars_p90 ?? overview.yield_ratio_chars_p90)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>{t('cross.kpi.tokenVolume')}</h4>
          <div className="kpi-value" title={formatNumber(overview.total_tokens)}>
            {formatTokenCount(overview.total_tokens)}
          </div>
          <p>
            {t('cross.kpi.inputOutput')}
            : <span title={formatNumber(overview.total_input_tokens)}>
              {formatTokenCount(overview.total_input_tokens)}
            </span>
            {' / '}
            <span title={formatNumber(overview.total_output_tokens)}>
              {formatTokenCount(overview.total_output_tokens)}
            </span>
          </p>
          <p>
            {t('cross.kpi.trajectorySize')}
            : {formatNumber(overview.total_trajectory_file_size_bytes)}
            {' '}
            {t('cross.kpi.bytes')}
          </p>
          <p>
            {t('cross.kpi.charsCjkLatin')}
            : {formatNumber(overview.total_cjk_chars)}
            {' / '}
            {formatNumber(overview.total_latin_chars)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>{t('cross.kpi.toolExecution')}</h4>
          <div className="kpi-value">{formatNumber(overview.total_tool_calls)}</div>
          <p>
            {t('cross.kpi.avgSessionDuration')}
            : {formatDuration(overview.avg_session_duration_seconds)} ·
            {' '}
            {t('cross.kpi.modelTimeouts')}
            : {formatNumber(overview.model_timeout_count)}
          </p>
          <p>
            <MetricTerm metricId="tokens_per_second">{t('cross.kpi.modelTokS')}</MetricTerm>
            : {overview.avg_tokens_per_second_mean.toFixed(2)} /
            {' '}
            {overview.avg_tokens_per_second_median.toFixed(2)} /
            {' '}
            {overview.avg_tokens_per_second_p90.toFixed(2)}
          </p>
          <p>
            <MetricTerm metricId="tokens_per_second">{t('cross.kpi.readOutputTokS')}</MetricTerm>
            : {overview.read_tokens_per_second_mean.toFixed(2)}
            {' / '}
            {overview.output_tokens_per_second_mean.toFixed(2)}
          </p>
          <p>
            <MetricTerm metricId="tokens_per_second">{t('cross.kpi.cacheTokS')}</MetricTerm>
            : {overview.cache_tokens_per_second_mean.toFixed(2)}
            {' ('}
            {overview.cache_read_tokens_per_second_mean.toFixed(2)}
            {' / '}
            {overview.cache_creation_tokens_per_second_mean.toFixed(2)}
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

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>{t('cross.sourceDistribution')}</h4>
          {sourceBreakdown.length === 0 ? (
            <p className="empty-hint">{t('cross.noSourceData')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={sourceBreakdown}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
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
                  {sourceBreakdown.map((source) => (
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
                    <YAxis />
                    <Tooltip
                      formatter={(value) => formatDuration(Number(value))}
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
                        <td>{formatDuration(row.total)}</td>
                        <td>{formatPercentPoint(row.share)}</td>
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
              <YAxis yAxisId="left" />
              <YAxis yAxisId="right" orientation="right" />
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
          {overview.bottleneck_distribution.length === 0 ? (
            <p className="empty-hint">{t('cross.noBottleneckData')}</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={overview.bottleneck_distribution}
                  dataKey="count"
                  nameKey="label"
                  cx="50%"
                  cy="50%"
                  outerRadius={95}
                  label={({ name, percent }) =>
                    `${name || t('table.unknown')}: ${formatPercentPoint(percent || 0)}`
                  }
                >
                  {overview.bottleneck_distribution.map((entry, index) => (
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
  );
}
