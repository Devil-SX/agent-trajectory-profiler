/**
 * StatisticsDashboard component for displaying session analytics.
 *
 * Metrics are organized by user-facing dimensions:
 * - Automation & Interaction
 * - Tool Execution
 * - Time & Stability
 * - Resource Consumption
 */

import { useEffect } from 'react';
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
import { useSessionStatisticsQuery } from '../hooks/useSessionsQuery';
import type { SessionStatistics } from '../types/session';
import { TimeBreakdownChart } from './TimeBreakdownChart';
import { BottleneckInsight } from './BottleneckInsight';
import { BashCommandTable } from './BashCommandTable';
import './StatisticsDashboard.css';

interface StatisticsDashboardProps {
  sessionId: string | null;
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

export function StatisticsDashboard({ sessionId }: StatisticsDashboardProps) {
  const { data, isLoading, error: queryError } = useSessionStatisticsQuery(sessionId);

  const statistics: SessionStatistics | null = data?.statistics || null;
  const loading = isLoading;
  const error = queryError?.message || null;

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
        <div className="loading-spinner">Loading statistics...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="statistics-dashboard error">
        <p className="error-text">{error}</p>
      </div>
    );
  }

  if (!statistics) {
    return null;
  }

  const interactions = statistics.time_breakdown?.user_interaction_count || 0;
  const automationRatio = interactions > 0
    ? statistics.total_tool_calls / interactions
    : null;

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
      <h2 className="dashboard-title">Session Metrics</h2>

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
            <h4 className="card-title">Automation Ratio</h4>
            <div className="stat-value large">
              {automationRatio !== null ? `${automationRatio.toFixed(2)}x` : 'N/A'}
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
                  <YAxis />
                  <Tooltip formatter={(value) => formatNumber(value as number)} />
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
                      <td>{formatNumber(tool.total_tokens)}</td>
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
            <div className="stat-value large">{formatNumber(statistics.total_tokens)}</div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Input</span>
                <span className="breakdown-value">{formatNumber(statistics.total_input_tokens)}</span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Output</span>
                <span className="breakdown-value">{formatNumber(statistics.total_output_tokens)}</span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <h4 className="card-title">Cache Tokens</h4>
            <div className="stat-value large">
              {formatNumber(statistics.cache_read_tokens + statistics.cache_creation_tokens)}
            </div>
            <div className="stat-breakdown">
              <div className="breakdown-item">
                <span className="breakdown-label">Read</span>
                <span className="breakdown-value">{formatNumber(statistics.cache_read_tokens)}</span>
              </div>
              <div className="breakdown-item">
                <span className="breakdown-label">Created</span>
                <span className="breakdown-value">{formatNumber(statistics.cache_creation_tokens)}</span>
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
                <Tooltip formatter={(value) => formatNumber(value as number)} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      </section>
    </div>
  );
}
