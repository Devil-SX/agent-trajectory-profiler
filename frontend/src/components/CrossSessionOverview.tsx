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
} from '../hooks/useSessionsQuery';
import type { AnalyticsBucket } from '../types/session';
import { truncateMiddle } from '../utils/display';
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

function formatNumber(value: number): string {
  return value.toLocaleString();
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

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function getLeadingBucket(buckets: AnalyticsBucket[]): string {
  if (buckets.length === 0) {
    return 'No data';
  }
  const [top] = buckets;
  return `${top.label} (${top.percent.toFixed(1)}%)`;
}

function formatSessionShareLabel(label: string): string {
  return truncateMiddle(label, 5, 4);
}

export function CrossSessionOverview() {
  const [preset, setPreset] = useState<RangePreset>('7d');
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

  const { data: overview, isLoading: overviewLoading, error: overviewError } =
    useAnalyticsOverviewQuery(activeRange.startDate, activeRange.endDate);

  const { data: automationDistribution, isLoading: automationLoading, error: automationError } =
    useAnalyticsDistributionQuery('automation_band', activeRange.startDate, activeRange.endDate);

  const { data: sessionShareDistribution, isLoading: shareLoading, error: shareError } =
    useAnalyticsDistributionQuery('session_token_share', activeRange.startDate, activeRange.endDate);

  const { data: timeseries, isLoading: timeseriesLoading, error: timeseriesError } =
    useAnalyticsTimeseriesQuery(interval, activeRange.startDate, activeRange.endDate);

  const isLoading = overviewLoading || automationLoading || shareLoading || timeseriesLoading;
  const errorMessage =
    overviewError?.message ||
    automationError?.message ||
    shareError?.message ||
    timeseriesError?.message ||
    null;

  const topSessionShare = useMemo(() => {
    if (!sessionShareDistribution) return [];
    return sessionShareDistribution.buckets.slice(0, 8);
  }, [sessionShareDistribution]);

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

  if (isLoading) {
    return (
      <section className="cross-session-overview loading" aria-live="polite">
        <div className="cross-session-skeleton">Loading cross-session analytics...</div>
      </section>
    );
  }

  if (errorMessage) {
    return (
      <section className="cross-session-overview error">
        <h3>Cross-session overview</h3>
        <p>{errorMessage}</p>
      </section>
    );
  }

  if (!overview || !automationDistribution || !timeseries) {
    return null;
  }

  const topProjects = overview.top_projects.slice(0, 8);
  const topTools = overview.top_tools.slice(0, 8);

  return (
    <section className="cross-session-overview" aria-label="Cross session overview">
      <div className="cross-session-header">
        <div>
          <h3>Cross-session overview</h3>
          <p>Aggregate health signals across all sessions in the selected window.</p>
        </div>

        <div className="cross-session-controls">
          <div className="preset-buttons" role="tablist" aria-label="Time window presets">
            <button
              type="button"
              className={preset === '7d' ? 'active' : ''}
              onClick={() => setPreset('7d')}
            >
              7 days
            </button>
            <button
              type="button"
              className={preset === '30d' ? 'active' : ''}
              onClick={() => setPreset('30d')}
            >
              30 days
            </button>
            <button
              type="button"
              className={preset === '90d' ? 'active' : ''}
              onClick={() => setPreset('90d')}
            >
              90 days
            </button>
            <button
              type="button"
              className={preset === 'custom' ? 'active' : ''}
              onClick={() => setPreset('custom')}
            >
              Custom
            </button>
          </div>

          {preset === 'custom' && (
            <div className="custom-range-inputs">
              <label>
                Start
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
                End
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
          <h4>Total sessions</h4>
          <div className="kpi-value">{formatNumber(overview.total_sessions)}</div>
          <p>Primary bottleneck: {getLeadingBucket(overview.bottleneck_distribution)}</p>
        </article>

        <article className="kpi-card">
          <h4>Automation efficiency</h4>
          <div className="kpi-value">{overview.avg_automation_ratio.toFixed(2)}x</div>
          <p>Active ratio: {formatPercent(overview.active_time_ratio * 100)}</p>
          <p>
            Token yield (mean/median/p90): {overview.yield_ratio_tokens_mean.toFixed(2)}x /
            {' '}
            {overview.yield_ratio_tokens_median.toFixed(2)}x /
            {' '}
            {overview.yield_ratio_tokens_p90.toFixed(2)}x
          </p>
          <p>
            Char yield (mean/median/p90): {overview.yield_ratio_chars_mean.toFixed(2)}x /
            {' '}
            {overview.yield_ratio_chars_median.toFixed(2)}x /
            {' '}
            {overview.yield_ratio_chars_p90.toFixed(2)}x
          </p>
        </article>

        <article className="kpi-card">
          <h4>Token volume</h4>
          <div className="kpi-value">{formatNumber(overview.total_tokens)}</div>
          <p>
            Input/Output: {formatNumber(overview.total_input_tokens)} /{' '}
            {formatNumber(overview.total_output_tokens)}
          </p>
          <p>
            Trajectory size: {formatNumber(overview.total_trajectory_file_size_bytes)}
            {' '}
            bytes
          </p>
          <p>
            Chars (CJK/Latin): {formatNumber(overview.total_cjk_chars)}
            {' / '}
            {formatNumber(overview.total_latin_chars)}
          </p>
        </article>

        <article className="kpi-card">
          <h4>Tool execution</h4>
          <div className="kpi-value">{formatNumber(overview.total_tool_calls)}</div>
          <p>
            Avg session duration: {formatDuration(overview.avg_session_duration_seconds)} ·
            {' '}
            Model timeouts: {formatNumber(overview.model_timeout_count)}
          </p>
          <p>
            Model tok/s (mean/median/p90): {overview.avg_tokens_per_second_mean.toFixed(2)} /
            {' '}
            {overview.avg_tokens_per_second_median.toFixed(2)} /
            {' '}
            {overview.avg_tokens_per_second_p90.toFixed(2)}
          </p>
          <p>
            Read/Output tok/s mean: {overview.read_tokens_per_second_mean.toFixed(2)}
            {' / '}
            {overview.output_tokens_per_second_mean.toFixed(2)}
          </p>
          <p>
            Cache tok/s mean: {overview.cache_tokens_per_second_mean.toFixed(2)}
            {' ('}
            {overview.cache_read_tokens_per_second_mean.toFixed(2)}
            {' / '}
            {overview.cache_creation_tokens_per_second_mean.toFixed(2)}
            {')'}
          </p>
        </article>
      </div>

      <div className="overview-grid">
        <section className="overview-card day-night-card">
          <h4>Day vs night time mix</h4>
          <p className="day-night-note">Night window: 01:00-09:00 (local time).</p>
          <p className="day-night-summary">
            Day total: {formatDuration(dayNightRows[0]?.total ?? 0)}
            {' · '}
            Night total: {formatDuration(dayNightRows[1]?.total ?? 0)}
          </p>

          {dayNightRows.length === 0 || dayNightRows.every((row) => row.total <= 0) ? (
            <p className="empty-hint">No day/night time data in this range.</p>
          ) : (
            <div className="day-night-layout">
              <div className="day-night-chart" aria-label="Day night time chart">
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={dayNightRows}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" />
                    <YAxis />
                    <Tooltip
                      formatter={(value) => formatDuration(Number(value))}
                      labelFormatter={(label) => `${label} period`}
                    />
                    <Legend />
                    <Bar dataKey="model" stackId="total" name="Model" fill="#2563eb" />
                    <Bar dataKey="tool" stackId="total" name="Tool" fill="#0891b2" />
                    <Bar dataKey="user" stackId="total" name="User" fill="#ea580c" />
                    <Bar dataKey="inactive" stackId="total" name="Inactive" fill="#94a3b8" />
                  </BarChart>
                </ResponsiveContainer>
              </div>

              <div className="table-wrapper">
                <table className="compact-table day-night-table">
                  <thead>
                    <tr>
                      <th>Period</th>
                      <th>Model</th>
                      <th>Tool</th>
                      <th>User</th>
                      <th>Inactive</th>
                      <th>Total</th>
                      <th>Share</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dayNightRows.map((row) => (
                      <tr key={row.period}>
                        <td>{row.period}</td>
                        <td>{formatDuration(row.model)}</td>
                        <td>{formatDuration(row.tool)}</td>
                        <td>{formatDuration(row.user)}</td>
                        <td>{formatDuration(row.inactive)}</td>
                        <td>{formatDuration(row.total)}</td>
                        <td>{formatPercent(row.share * 100)}</td>
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
          <h4>Session throughput trend</h4>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={timeseries.points}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" />
              <YAxis yAxisId="left" />
              <YAxis yAxisId="right" orientation="right" />
              <Tooltip formatter={(value) => formatNumber(Number(value))} />
              <Legend />
              <Area
                yAxisId="left"
                type="monotone"
                dataKey="sessions"
                stroke="#2563eb"
                fill="#bfdbfe"
                name="Sessions"
              />
              <Area
                yAxisId="right"
                type="monotone"
                dataKey="tokens"
                stroke="#ea580c"
                fill="#fed7aa"
                name="Tokens"
              />
            </AreaChart>
          </ResponsiveContainer>
        </section>

        <section className="overview-card">
          <h4>Bottleneck distribution</h4>
          {overview.bottleneck_distribution.length === 0 ? (
            <p className="empty-hint">No bottleneck data in this range.</p>
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
                    `${name || 'Unknown'}: ${formatPercent((percent || 0) * 100)}`
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
          <h4>Automation bands</h4>
          {automationDistribution.buckets.length === 0 ? (
            <p className="empty-hint">No automation data in this range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={automationDistribution.buckets}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip formatter={(value) => formatNumber(Number(value))} />
                <Legend />
                <Bar dataKey="count" fill="#2563eb" name="Sessions" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="overview-card">
          <h4>Top tools by call volume</h4>
          {topTools.length === 0 ? (
            <p className="empty-hint">No tool data in this range.</p>
          ) : (
            <div className="table-wrapper">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>Tool</th>
                    <th>Calls</th>
                    <th>Errors</th>
                    <th>Avg latency</th>
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
          <h4>Top projects</h4>
          {topProjects.length === 0 ? (
            <p className="empty-hint">No project data in this range.</p>
          ) : (
            <div className="table-wrapper">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Sessions</th>
                    <th>Token share</th>
                  </tr>
                </thead>
                <tbody>
                  {topProjects.map((project) => (
                    <tr key={project.project_path || project.project_name}>
                      <td>{project.project_name}</td>
                      <td>{formatNumber(project.sessions)}</td>
                      <td>{formatPercent(project.percent_tokens)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="overview-card">
          <h4>Top sessions by token share</h4>
          {topSessionShare.length === 0 ? (
            <p className="empty-hint">No token-share data in this range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={topSessionShare}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" tickFormatter={formatSessionShareLabel} />
                <YAxis />
                <Tooltip formatter={(value) => formatNumber(Number(value))} />
                <Legend />
                <Bar dataKey="percent" fill="#0f766e" name="Token share %" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>
      </div>
    </section>
  );
}
