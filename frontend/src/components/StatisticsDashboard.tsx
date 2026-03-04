/**
 * StatisticsDashboard component for displaying session analytics.
 *
 * Metrics are organized by user-facing dimensions:
 * - Automation & Interaction
 * - Tool Execution
 * - Time & Stability
 * - Resource Consumption
 */

import { Fragment, useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { useCapabilitiesQuery, useSessionStatisticsQuery } from '../hooks/useSessionsQuery';
import type { SessionStatistics } from '../types/session';
import { formatTokenCount } from '../utils/tokenFormat';
import { formatTokenAxisTick, formatTokenWithRawValue } from '../utils/chartFormatters';
import {
  buildCapabilityIndex,
  buildSessionStatisticsViewModel,
} from '../utils/contractViewModel';
import { TimeBreakdownChart } from './TimeBreakdownChart';
import { BottleneckInsight } from './BottleneckInsight';
import { BashCommandTable } from './BashCommandTable';
import { MetricTerm } from './MetricHelp';
import './StatisticsDashboard.css';

interface StatisticsDashboardProps {
  sessionId: string | null;
  ecosystem?: string | null;
}

const COLORS = [
  '#1976d2',
  '#388e3c',
  '#f57c00',
  '#d32f2f',
  '#7b1fa2',
  '#0097a7',
  '#c2185b',
  '#fbc02d',
  '#5d4037',
  '#455a64',
];

function formatNumber(num: number): string {
  return num.toLocaleString();
}

function formatTokenWithFull(num: number): string {
  return formatTokenWithRawValue(num, formatNumber);
}

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds <= 0) return 'N/A';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${secs}s`;
  }
  return `${secs}s`;
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(value >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

function formatTokenRate(value: number | null | undefined): string {
  if (typeof value !== 'number') return 'N/A';
  return `${value.toFixed(2)} tok/s`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function StatisticsDashboard({ sessionId, ecosystem = null }: StatisticsDashboardProps) {
  const { data, isLoading, isFetching, error: queryError, refetch } = useSessionStatisticsQuery(sessionId);
  const capabilitiesQuery = useCapabilitiesQuery();
  const [expandedErrors, setExpandedErrors] = useState<Record<string, boolean>>({});

  const statistics: SessionStatistics | null = data?.statistics || null;
  const capabilityIndex = useMemo(
    () => buildCapabilityIndex(capabilitiesQuery.data),
    [capabilitiesQuery.data]
  );
  const selectedCapability = ecosystem ? capabilityIndex[ecosystem] : undefined;
  const statisticsVm = statistics
    ? buildSessionStatisticsViewModel(statistics, selectedCapability)
    : null;
  const loading = isLoading && !statistics;
  const sessionMismatch = Boolean(data && data.session_id !== sessionId);
  const switchingSession = isFetching && Boolean(statistics) && sessionMismatch;
  const refreshingSession = isFetching && Boolean(statistics) && !sessionMismatch;
  const error = queryError?.message || null;
  const blockingError = Boolean(error && !statistics);
  const recoverableError = Boolean(error && statistics);

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  if (!sessionId) {
    return (
      <div className="statistics-dashboard empty">
        <p>Select a session to view statistics</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="statistics-dashboard loading">
        <div className="loading-spinner" role="status" aria-live="polite">
          <span className="panel-loading-title">Loading statistics...</span>
          <div className="stats-loading-skeleton" aria-hidden="true">
            {Array.from({ length: 5 }, (_, index) => (
              <div key={index} className="stats-loading-skeleton-row" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (blockingError) {
    return (
      <div className="statistics-dashboard error">
        <p className="error-text">{error}</p>
        <button
          type="button"
          className="stats-retry-button"
          onClick={() => {
            void refetch();
          }}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!statistics) {
    return null;
  }

  const toolErrorRecords = statistics.tool_error_records || [];
  const errorCategoryEntries = Object.entries(statistics.tool_error_category_counts || {})
    .sort((a, b) => b[1] - a[1]);
  const characterBreakdown = statistics.character_breakdown || {
    total_chars: 0,
    user_chars: 0,
    model_chars: 0,
    tool_chars: 0,
    cjk_chars: 0,
    latin_chars: 0,
    digit_chars: 0,
    whitespace_chars: 0,
    other_chars: 0,
  };

  const toggleErrorDetail = (key: string): void => {
    setExpandedErrors((prev) => ({
      ...prev,
      [key]: !prev[key],
    }));
  };

  const interactions = statistics.time_breakdown?.user_interaction_count || 0;

  const withCalls = statistics.tool_calls.filter((item) => item.count > 0);
  const weightedLatency = withCalls.reduce(
    (sum, item) => sum + item.avg_latency_seconds * item.count,
    0
  );
  const totalCalls = withCalls.reduce((sum, item) => sum + item.count, 0);
  const avgToolLatency = totalCalls > 0 ? weightedLatency / totalCalls : 0;

  // Charts / tabular datasets
  const toolCallData = statistics.tool_calls
    .slice(0, 10)
    .map((tc) => ({
      name: tc.tool_name,
      count: tc.count,
      tokens: tc.total_tokens,
    }));

  const tokenDistribution = [
    { name: 'Input Tokens', value: statistics.total_input_tokens },
    { name: 'Output Tokens', value: statistics.total_output_tokens },
    ...(statistics.cache_read_tokens > 0
      ? [{ name: 'Cache Read Tokens', value: statistics.cache_read_tokens }]
      : []),
    ...(statistics.cache_creation_tokens > 0
      ? [{ name: 'Cache Creation Tokens', value: statistics.cache_creation_tokens }]
      : []),
  ];

  const messageTypeData = [
    { name: 'User', count: statistics.user_message_count },
    { name: 'Assistant', count: statistics.assistant_message_count },
    { name: 'System', count: statistics.system_message_count },
  ].filter((item) => item.count > 0);

  const subagentData = Object.entries(statistics.subagent_sessions).map(([type, count]) => ({
    type,
    count,
  }));

  const toolTokenData = statistics.tool_calls
    .filter((tc) => tc.total_tokens > 0)
    .slice(0, 10)
    .map((tc) => ({
      name: tc.tool_name,
      tokens: tc.total_tokens,
    }));

  return (
    <div className="statistics-dashboard">
      {(switchingSession || refreshingSession || recoverableError) && (
        <div className="stats-refresh-indicator" role="status" aria-live="polite">
          {switchingSession
            ? 'Switching session statistics...'
            : refreshingSession
              ? 'Refreshing statistics...'
              : 'Showing cached statistics (refresh failed)'}
        </div>
      )}
      {switchingSession && (
        <div className="stats-panel-overlay" role="status" aria-live="polite" data-testid="stats-switching-overlay">
          <span>Switching session...</span>
        </div>
      )}
      <h2 className="dashboard-title">Session Metrics</h2>

      {statisticsVm && statisticsVm.capabilityNotices.length > 0 && (
        <section className="metrics-section" data-testid="stats-capability-notes">
          <div className="section-header">
            <h3>Capability Notes</h3>
            <p>Ecosystem-specific support and fallback caveats for derived metrics.</p>
          </div>
          <div className="stats-grid">
            {statisticsVm.capabilityNotices.map((notice) => (
              <div
                key={notice.id}
                className={`stat-card stats-capability-note stats-capability-note--${notice.severity}`}
              >
                <h4 className="card-title">{notice.label}</h4>
                <div className="stat-breakdown">
                  <div className="breakdown-item">
                    <span className="breakdown-label">{notice.reason}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {statistics.time_breakdown && (
        <BottleneckInsight timeBreakdown={statistics.time_breakdown} />
      )}

      <section className="metrics-section">
        <div className="section-header">
          <h3>Automation & Interaction</h3>
          <p>User interaction effort and orchestration intensity.</p>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <h4 className="card-title">Messages</h4>
            <div className="stat-value large">{formatNumber(statistics.message_count)}</div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">User</span>
                <span className="breakdown-value">{formatNumber(statistics.user_message_count)}</span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Assistant</span>
                <span className="breakdown-value">{formatNumber(statistics.assistant_message_count)}</span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">
              <MetricTerm metricId="yield">Automation Ratio</MetricTerm>
            </h4>
            <div className="stat-value large">
              {statisticsVm && statisticsVm.automationRatio !== null
                ? `${statisticsVm.automationRatio.toFixed(2)}x`
                : 'N/A'}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Tool calls</span>
                <span className="breakdown-value">{formatNumber(statistics.total_tool_calls)}</span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Interactions</span>
                <span className="breakdown-value">{formatNumber(interactions)}</span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Subagents</h4>
            <div className="stat-value large">{formatNumber(statistics.subagent_count)}</div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Agent types</span>
                <span className="breakdown-value">{Object.keys(statistics.subagent_sessions).length}</span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">
              <MetricTerm metricId="leverage">Leverage Ratio</MetricTerm>
            </h4>
            <div className="stat-value large">
              {statisticsVm && statisticsVm.tokenYieldRatio !== null
                ? `${statisticsVm.tokenYieldRatio.toFixed(2)}x`
                : 'N/A'}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Chars output/input</span>
                <span className="breakdown-value">
                  {statisticsVm && statisticsVm.charYieldRatio !== null
                    ? `${statisticsVm.charYieldRatio.toFixed(2)}x`
                    : 'N/A'}
                </span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Formula</span>
                <span className="breakdown-value">(Model + Tool) / User</span>
              </div>
            </div>
          </div>
        </div>

        <div className="charts-section">
          {messageTypeData.length > 0 && (
            <div className="chart-card">
              <h4 className="card-title">Message Type Mix</h4>
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={messageTypeData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) =>
                      `${name}: ${percent ? (percent * 100).toFixed(0) : 0}%`
                    }
                    outerRadius={80}
                    dataKey="count"
                  >
                    {messageTypeData.map((_, index) => (
                      <Cell key={`message-type-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}

          {subagentData.length > 0 && (
            <div className="chart-card">
              <h4 className="card-title">Subagent Invocations</h4>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={subagentData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="type" type="category" width={100} />
                  <Tooltip />
                  <Bar dataKey="count" fill={COLORS[1]} name="Count" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </section>

      <section className="metrics-section">
        <div className="section-header">
          <h3>Tool Execution</h3>
          <p>Tool frequency, latency quality, and failure concentration.</p>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <h4 className="card-title">Total Tool Calls</h4>
            <div className="stat-value large">{formatNumber(statistics.total_tool_calls)}</div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Unique tools</span>
                <span className="breakdown-value">{statistics.tool_calls.length}</span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Avg Tool Latency</h4>
            <div className="stat-value large">{avgToolLatency.toFixed(2)}s</div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Tools above 5s</span>
                <span className="breakdown-value">
                  {statistics.tool_calls.filter((tool) => tool.avg_latency_seconds > 5).length}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Tool Errors</h4>
            <div className="stat-value large">
              {formatNumber(statistics.tool_calls.reduce((sum, tool) => sum + tool.error_count, 0))}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Success events</span>
                <span className="breakdown-value">
                  {formatNumber(statistics.tool_calls.reduce((sum, tool) => sum + tool.success_count, 0))}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="charts-section">
          {toolCallData.length > 0 && (
            <div className="chart-card wide">
              <h4 className="card-title">Tool Call Breakdown (Top 10)</h4>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={toolCallData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" angle={-45} textAnchor="end" height={90} />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="count" fill={COLORS[0]} name="Call Count" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {toolTokenData.length > 0 && (
            <div className="chart-card wide">
              <h4 className="card-title">Token Usage by Tool (Top 10)</h4>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={toolTokenData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" angle={-45} textAnchor="end" height={90} />
                  <YAxis tickFormatter={formatTokenAxisTick} />
                  <Tooltip formatter={(value) => formatTokenWithFull(Number(value))} />
                  <Legend />
                  <Bar dataKey="tokens" fill={COLORS[2]} name="Total Tokens" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {statistics.tool_calls.length > 0 && (
          <div className="table-card">
            <h4 className="card-title">Tool Statistics</h4>
            <div className="table-container">
              <table className="stats-table">
                <thead>
                  <tr>
                    <th>Tool Name</th>
                    <th>Calls</th>
                    <th>Total Tokens</th>
                    <th>Avg Latency</th>
                    <th>Success</th>
                    <th>Errors</th>
                  </tr>
                </thead>
                <tbody>
                  {statistics.tool_calls.slice(0, 15).map((tool) => (
                    <tr key={tool.tool_name}>
                      <td className="tool-name">{tool.tool_name}</td>
                      <td>{formatNumber(tool.count)}</td>
                      <td title={formatNumber(tool.total_tokens)}>{formatTokenCount(tool.total_tokens)}</td>
                      <td
                        className={
                          tool.avg_latency_seconds > 10
                            ? 'latency-high'
                            : tool.avg_latency_seconds > 5
                              ? 'latency-medium'
                              : ''
                        }
                      >
                        {tool.avg_latency_seconds > 0
                          ? `${tool.avg_latency_seconds.toFixed(2)}s`
                          : '--'}
                      </td>
                      <td>{formatNumber(tool.success_count)}</td>
                      <td className={tool.error_count > 0 ? 'error-count' : ''}>
                        {formatNumber(tool.error_count)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {toolErrorRecords.length > 0 && (
          <div className="table-card">
            <h4 className="card-title">Tool Error Timeline</h4>
            <p className="error-taxonomy-note">
              Taxonomy v{statistics.error_taxonomy_version} · Unknown patterns are tracked as
              {' '}
              <code>uncategorized</code>
            </p>

            {errorCategoryEntries.length > 0 && (
              <div className="error-category-row">
                {errorCategoryEntries.map(([category, count]) => (
                  <span key={category} className="error-category-chip">
                    <span className="error-category-name">{category}</span>
                    <span className="error-category-count">{formatNumber(count)}</span>
                  </span>
                ))}
              </div>
            )}

            <div className="table-container">
              <table className="stats-table error-timeline-table">
                <thead>
                  <tr>
                    <th>Timestamp</th>
                    <th>Tool</th>
                    <th>Category</th>
                    <th>Rule</th>
                    <th>Preview</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {toolErrorRecords.map((record, index) => {
                    const rowKey = `${record.timestamp}-${record.tool_name}-${index}`;
                    const isExpanded = expandedErrors[rowKey] === true;
                    return (
                      <Fragment key={rowKey}>
                        <tr>
                          <td>{formatTimestamp(record.timestamp)}</td>
                          <td className="tool-name">{record.tool_name}</td>
                          <td>
                            <span className="error-category-badge">{record.category}</span>
                          </td>
                          <td>{record.matched_rule ?? '--'}</td>
                          <td className="error-preview-cell">{record.preview}</td>
                          <td>
                            <button
                              type="button"
                              className="error-expand-button"
                              onClick={() => toggleErrorDetail(rowKey)}
                            >
                              {isExpanded ? 'Collapse' : 'Expand'}
                            </button>
                          </td>
                        </tr>
                        isExpanded ? (
                          <tr className="error-detail-row">
                            <td colSpan={6}>
                              <pre className="error-detail-text">{record.detail}</pre>
                            </td>
                          </tr>
                        ) : null
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {statistics.bash_breakdown && statistics.bash_breakdown.command_stats.length > 0 && (
          <BashCommandTable bashBreakdown={statistics.bash_breakdown} />
        )}
      </section>

      <section className="metrics-section">
        <div className="section-header">
          <h3>Time & Stability</h3>
          <p>Session duration profile and timeout risks.</p>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <h4 className="card-title">Duration</h4>
            <div className="stat-value large">
              {formatDuration(statistics.session_duration_seconds)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Avg per message</span>
                <span className="breakdown-value">
                  {statistics.session_duration_seconds && statistics.message_count > 0
                    ? `${Math.round(statistics.session_duration_seconds / statistics.message_count)}s`
                    : 'N/A'}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Model Timeouts</h4>
            <div className="stat-value large">
              {formatNumber(statistics.time_breakdown?.model_timeout_count || 0)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Threshold</span>
                <span className="breakdown-value">
                  {statistics.time_breakdown
                    ? `${Math.round(statistics.time_breakdown.model_timeout_threshold_seconds)}s`
                    : 'N/A'}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Inactive Time</h4>
            <div className="stat-value large">
              {statistics.time_breakdown
                ? `${statistics.time_breakdown.inactive_time_percent.toFixed(1)}%`
                : 'N/A'}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Total inactive</span>
                <span className="breakdown-value">
                  {statistics.time_breakdown
                    ? formatDuration(statistics.time_breakdown.total_inactive_time_seconds)
                    : 'N/A'}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4
              className="card-title"
              title="Rates use model active seconds as denominator: tokens / model_time_seconds"
            >
              <MetricTerm metricId="tokens_per_second">Model Throughput</MetricTerm>
            </h4>
            <div className="stat-value large">
              {formatTokenRate(statistics.avg_tokens_per_second)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Read / Output</span>
                <span className="breakdown-value">
                  {formatTokenRate(statistics.read_tokens_per_second)}
                  {' / '}
                  {formatTokenRate(statistics.output_tokens_per_second)}
                </span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Cache total (read/create)</span>
                <span className="breakdown-value">
                  {formatTokenRate(statistics.cache_tokens_per_second)}
                  {' ('}
                  {formatTokenRate(statistics.cache_read_tokens_per_second)}
                  {' / '}
                  {formatTokenRate(statistics.cache_creation_tokens_per_second)}
                  {')'}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="charts-section">
          {statistics.time_breakdown && (
            <TimeBreakdownChart timeBreakdown={statistics.time_breakdown} />
          )}
        </div>
      </section>

      <section className="metrics-section">
        <div className="section-header">
          <h3>Resource Consumption</h3>
          <p>Total token footprint and cache behavior.</p>
        </div>

        <div className="stats-grid">
          <div className="stat-card">
            <h4 className="card-title">Total Tokens</h4>
            <div className="stat-value large" title={formatNumber(statistics.total_tokens)}>
              {formatTokenCount(statistics.total_tokens)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Input</span>
                <span className="breakdown-value" title={formatNumber(statistics.total_input_tokens)}>
                  {formatTokenCount(statistics.total_input_tokens)}
                </span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Output</span>
                <span className="breakdown-value" title={formatNumber(statistics.total_output_tokens)}>
                  {formatTokenCount(statistics.total_output_tokens)}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Cache Tokens</h4>
            <div
              className="stat-value large"
              title={formatNumber(statistics.cache_read_tokens + statistics.cache_creation_tokens)}
            >
              {formatTokenCount(statistics.cache_read_tokens + statistics.cache_creation_tokens)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Read</span>
                <span className="breakdown-value" title={formatNumber(statistics.cache_read_tokens)}>
                  {formatTokenCount(statistics.cache_read_tokens)}
                </span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Created</span>
                <span className="breakdown-value" title={formatNumber(statistics.cache_creation_tokens)}>
                  {formatTokenCount(statistics.cache_creation_tokens)}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Trajectory Size</h4>
            <div className="stat-value large">{formatBytes(statistics.trajectory_file_size_bytes)}</div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Raw bytes</span>
                <span className="breakdown-value">
                  {formatNumber(statistics.trajectory_file_size_bytes)}
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Character Volume</h4>
            <div className="stat-value large">
              {formatNumber(characterBreakdown.total_chars)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">CJK / Latin</span>
                <span className="breakdown-value">
                  {formatNumber(characterBreakdown.cjk_chars)}
                  {' / '}
                  {formatNumber(characterBreakdown.latin_chars)}
                </span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">User / Model / Tool</span>
                <span className="breakdown-value">
                  {formatNumber(characterBreakdown.user_chars)}
                  {' / '}
                  {formatNumber(characterBreakdown.model_chars)}
                  {' / '}
                  {formatNumber(characterBreakdown.tool_chars)}
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="charts-section">
          <div className="chart-card">
            <h4 className="card-title">Token Distribution</h4>
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={tokenDistribution}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={({ name, percent }) =>
                    `${name}: ${percent ? (percent * 100).toFixed(0) : 0}%`
                  }
                  outerRadius={85}
                  dataKey="value"
                >
                  {tokenDistribution.map((_, index) => (
                    <Cell key={`token-distribution-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(value) => formatTokenWithFull(Number(value))} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>
    </div>
  );
}
