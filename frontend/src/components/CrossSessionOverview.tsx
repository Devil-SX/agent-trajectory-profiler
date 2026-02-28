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

function formatLeverage(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return 'N/A';
  }
  return `${value.toFixed(2)}x`;
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

function buildSwimlaneColor(tokens: number, maxTokens: number): string {
  if (tokens <= 0 || maxTokens <= 0) {
    return '#f3f4f6';
  }
  const ratio = Math.min(1, tokens / maxTokens);
  const alpha = 0.18 + ratio * 0.72;
  return `rgba(37, 99, 235, ${alpha.toFixed(3)})`;
}

export function CrossSessionOverview() {
  const [preset, setPreset] = useState<RangePreset>('7d');
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
  } = useProjectSwimlaneQuery(interval, activeRange.startDate, activeRange.endDate, 12);

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
  const swimlanePointMap = new Map<string, (typeof projectSwimlane.points)[number]>();
  for (const point of projectSwimlane.points) {
    swimlanePointMap.set(`${point.project_path}::${point.period}`, point);
  }
  const swimlaneMaxTokens =
    projectSwimlane.points.length > 0
      ? Math.max(...projectSwimlane.points.map((point) => point.tokens))
      : 0;

  const toggleProjectSelection = (projectPath: string) => {
    setProjectSelection((prev) => {
      const currentlySelected = selectedProjectPaths.includes(projectPath);
      return { ...prev, [projectPath]: !currentlySelected };
    });
  };

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
            Token leverage (mean/median/p90): {formatLeverage(
              overview.leverage_tokens_mean ?? overview.yield_ratio_tokens_mean
            )} /
            {' '}
            {formatLeverage(overview.leverage_tokens_median ?? overview.yield_ratio_tokens_median)} /
            {' '}
            {formatLeverage(overview.leverage_tokens_p90 ?? overview.yield_ratio_tokens_p90)}
          </p>
          <p>
            Char leverage (mean/median/p90): {formatLeverage(
              overview.leverage_chars_mean ?? overview.yield_ratio_chars_mean
            )} /
            {' '}
            {formatLeverage(overview.leverage_chars_median ?? overview.yield_ratio_chars_median)} /
            {' '}
            {formatLeverage(overview.leverage_chars_p90 ?? overview.yield_ratio_chars_p90)}
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

        <article className="kpi-card leverage-estimator-card">
          <h4>Code capacity estimate</h4>
          <div className="kpi-value">{formatNumber(Math.round(leverageEstimate.estimatedCodeLines))}</div>
          <p>Approximate editable LOC upper bound for this selected range.</p>
          <div className="leverage-controls">
            <label>
              Coding token fraction
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
              Tokens per LOC
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
            Inputs: {formatNumber(leverageEstimate.outputBudgetTokens)}
            {' '}
            output tokens, effective
            {' '}
            {formatNumber(Math.round(leverageEstimate.effectiveCodingTokens))}
            {' '}
            coding tokens.
          </p>
          <p className="leverage-note">
            Estimate only. Real leverage depends on docs quality, skills, tooling, and model fit.
          </p>
        </article>
      </div>

      <div className="overview-grid two-columns">
        <section className="overview-card">
          <h4>Source ecosystem distribution</h4>
          {sourceBreakdown.length === 0 ? (
            <p className="empty-hint">No source ecosystem data in this range.</p>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={sourceBreakdown}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis />
                <Tooltip formatter={(value) => formatNumber(Number(value))} />
                <Legend />
                <Bar dataKey="sessions" fill="#2563eb" name="Sessions" />
                <Bar dataKey="total_tokens" fill="#ea580c" name="Tokens" />
              </BarChart>
            </ResponsiveContainer>
          )}
        </section>

        <section className="overview-card">
          <h4>Source comparison table</h4>
          {sourceBreakdown.length === 0 ? (
            <p className="empty-hint">No source ecosystem data in this range.</p>
          ) : (
            <div className="table-wrapper">
              <table className="compact-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>Sessions</th>
                    <th>Token share</th>
                    <th>Tool calls</th>
                    <th>Active time</th>
                  </tr>
                </thead>
                <tbody>
                  {sourceBreakdown.map((source) => (
                    <tr key={source.ecosystem}>
                      <td>{source.label}</td>
                      <td>{formatNumber(source.sessions)}</td>
                      <td>{formatPercent(source.percent_tokens)}</td>
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
          <h4>Project comparison</h4>
          {comparisonProjects.length === 0 ? (
            <p className="empty-hint">No project-level comparison data in this range.</p>
          ) : (
            <>
              <p className="project-compare-note">
                Select projects to compare KPI rows (sessions, tokens, active ratio, leverage).
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
                <p className="empty-hint">Select at least one project to compare.</p>
              ) : (
                <div className="table-wrapper">
                  <table className="compact-table">
                    <thead>
                      <tr>
                        <th>Project</th>
                        <th>Sessions</th>
                        <th>Tokens</th>
                        <th>Active ratio</th>
                        <th>Token leverage</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedComparisonProjects.map((project) => (
                        <tr key={project.project_path}>
                          <td>{project.project_name}</td>
                          <td>{formatNumber(project.sessions)}</td>
                          <td>{formatNumber(project.total_tokens)}</td>
                          <td>{formatPercent(project.active_ratio * 100)}</td>
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
          <h4>Project swimlane</h4>
          {projectSwimlane.truncated_project_count > 0 && (
            <p className="project-compare-note">
              Showing top {projectSwimlane.project_limit} projects by tokens.
              {' '}
              {projectSwimlane.truncated_project_count}
              {' '}
              additional project(s) are hidden for readability.
            </p>
          )}
          {projectSwimlane.periods.length === 0 || swimlaneProjects.length === 0 ? (
            <p className="empty-hint">No swimlane data for current filters.</p>
          ) : (
            <>
              <div className="table-wrapper swimlane-wrapper">
                <table className="compact-table swimlane-table">
                  <thead>
                    <tr>
                      <th>Project</th>
                      {projectSwimlane.periods.map((period) => (
                        <th key={period}>{period}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {swimlaneProjects.map((project) => (
                      <tr key={project.project_path}>
                        <td>{project.project_name}</td>
                        {projectSwimlane.periods.map((period) => {
                          const point = swimlanePointMap.get(`${project.project_path}::${period}`);
                          const tokens = point?.tokens ?? 0;
                          const sessions = point?.sessions ?? 0;
                          const activeRatio = point?.active_ratio ?? 0;
                          const leverage = point?.leverage_tokens_mean;
                          return (
                            <td
                              key={`${project.project_path}-${period}`}
                              className="swimlane-cell"
                              style={{ backgroundColor: buildSwimlaneColor(tokens, swimlaneMaxTokens) }}
                              title={
                                `Project: ${project.project_name}\nPeriod: ${period}\n` +
                                `Tokens: ${formatNumber(tokens)}\nSessions: ${sessions}\n` +
                                `Active ratio: ${formatPercent(activeRatio * 100)}\n` +
                                `Token leverage: ${formatLeverage(leverage)}`
                              }
                            >
                              <span>{tokens > 0 ? formatNumber(tokens) : '--'}</span>
                              <small>{sessions > 0 ? `${sessions} sess` : ''}</small>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="swimlane-legend">
                <span>Token density</span>
                <div className="swimlane-gradient" />
                <span>Low → High</span>
              </div>
            </>
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
                    <th>Token leverage</th>
                    <th>Char leverage</th>
                  </tr>
                </thead>
                <tbody>
                  {topProjects.map((project) => (
                    <tr key={project.project_path || project.project_name}>
                      <td>{project.project_name}</td>
                      <td>{formatNumber(project.sessions)}</td>
                      <td>{formatPercent(project.percent_tokens)}</td>
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
