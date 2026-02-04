/**
 * Utilities for exporting session data and analytics to various formats.
 */

import type { SessionStatistics } from '../types/session';
import type { AdvancedAnalytics, ExportConfig } from '../types/analytics';

/**
 * Convert data to CSV format.
 */
function convertToCSV(data: Record<string, unknown>[]): string {
  if (data.length === 0) return '';

  const headers = Object.keys(data[0]);
  const rows = data.map((row) =>
    headers.map((header) => {
      const value = row[header];
      if (value === null || value === undefined) return '';
      const stringValue = String(value);
      // Escape quotes and wrap in quotes if contains comma or newline
      if (stringValue.includes(',') || stringValue.includes('\n') || stringValue.includes('"')) {
        return `"${stringValue.replace(/"/g, '""')}"`;
      }
      return stringValue;
    }).join(',')
  );

  return [headers.join(','), ...rows].join('\n');
}

/**
 * Export session statistics to CSV.
 */
export function exportStatisticsToCSV(
  _sessionId: string,
  statistics: SessionStatistics
): string {
  const rows: Record<string, unknown>[] = [
    {
      metric: 'Total Messages',
      value: statistics.message_count,
    },
    {
      metric: 'User Messages',
      value: statistics.user_message_count,
    },
    {
      metric: 'Assistant Messages',
      value: statistics.assistant_message_count,
    },
    {
      metric: 'Total Tokens',
      value: statistics.total_tokens,
    },
    {
      metric: 'Input Tokens',
      value: statistics.total_input_tokens,
    },
    {
      metric: 'Output Tokens',
      value: statistics.total_output_tokens,
    },
    {
      metric: 'Cache Read Tokens',
      value: statistics.cache_read_tokens,
    },
    {
      metric: 'Cache Creation Tokens',
      value: statistics.cache_creation_tokens,
    },
    {
      metric: 'Total Tool Calls',
      value: statistics.total_tool_calls,
    },
    {
      metric: 'Subagent Count',
      value: statistics.subagent_count,
    },
    {
      metric: 'Session Duration (seconds)',
      value: statistics.session_duration_seconds || 0,
    },
  ];

  return convertToCSV(rows);
}

/**
 * Export tool statistics to CSV.
 */
export function exportToolStatsToCSV(statistics: SessionStatistics): string {
  const rows = statistics.tool_calls.map((tool) => ({
    tool_name: tool.tool_name,
    total_calls: tool.count,
    total_tokens: tool.total_tokens,
    success_count: tool.success_count,
    error_count: tool.error_count,
    success_rate: (
      (tool.success_count / (tool.success_count + tool.error_count || 1)) *
      100
    ).toFixed(2),
  }));

  return convertToCSV(rows);
}

/**
 * Export advanced analytics to CSV (multiple sheets/files).
 */
export function exportAnalyticsToCSV(analytics: AdvancedAnalytics): Map<string, string> {
  const files = new Map<string, string>();

  // Expensive operations
  if (analytics.expensiveOperations.length > 0) {
    const expensiveOpsData = analytics.expensiveOperations.map((op) => ({
      rank: op.costRank,
      type: op.type,
      name: op.name,
      tokens: op.tokens,
      timestamp: op.timestamp,
      tool_name: op.details.toolName || '',
      agent_type: op.details.agentType || '',
    }));
    files.set('expensive_operations.csv', convertToCSV(expensiveOpsData));
  }

  // Tool usage patterns
  if (analytics.toolUsagePatterns.length > 0) {
    const toolPatternsData = analytics.toolUsagePatterns.map((pattern) => ({
      tool_name: pattern.toolName,
      total_calls: pattern.totalCalls,
      avg_tokens_per_call: pattern.averageTokensPerCall.toFixed(2),
      success_rate: (pattern.successRate * 100).toFixed(2),
      parameters: Object.keys(pattern.commonParameters).join('; '),
    }));
    files.set('tool_patterns.csv', convertToCSV(toolPatternsData));
  }

  // Subagent efficiency
  if (analytics.subagentEfficiency.length > 0) {
    const subagentData = analytics.subagentEfficiency.map((eff) => ({
      agent_type: eff.agentType,
      total_invocations: eff.totalInvocations,
      avg_messages: eff.averageMessages.toFixed(2),
      avg_tokens: eff.averageTokens.toFixed(2),
      avg_duration_seconds: eff.averageDuration.toFixed(2),
      tokens_per_minute: eff.tokensPerMinute.toFixed(2),
      efficiency_score: eff.efficiencyScore,
    }));
    files.set('subagent_efficiency.csv', convertToCSV(subagentData));
  }

  // Performance bottlenecks
  if (analytics.performanceBottlenecks.length > 0) {
    const bottleneckData = analytics.performanceBottlenecks.map((bottleneck) => ({
      type: bottleneck.type,
      severity: bottleneck.severity,
      description: bottleneck.description,
      affected_component: bottleneck.affectedComponent,
      tokens_wasted: bottleneck.impactMetrics.tokensWasted || 0,
      recommendation: bottleneck.recommendation,
    }));
    files.set('bottlenecks.csv', convertToCSV(bottleneckData));
  }

  // Recommendations
  if (analytics.recommendations.length > 0) {
    const recommendationData = analytics.recommendations.map((rec) => ({
      category: rec.category,
      priority: rec.priority,
      title: rec.title,
      description: rec.description,
      potential_token_savings: rec.potentialSavings?.tokens || 0,
      action_items: rec.actionItems.join('; '),
    }));
    files.set('recommendations.csv', convertToCSV(recommendationData));
  }

  // Token usage heatmap
  if (analytics.tokenUsageHeatmap.dataPoints.length > 0) {
    const heatmapData = analytics.tokenUsageHeatmap.dataPoints.map((dp) => ({
      timestamp: dp.timestamp,
      total_tokens: dp.tokens,
      input_tokens: dp.inputTokens,
      output_tokens: dp.outputTokens,
      cache_read_tokens: dp.cacheReadTokens,
      cache_creation_tokens: dp.cacheCreationTokens,
      message_type: dp.messageType,
    }));
    files.set('token_heatmap.csv', convertToCSV(heatmapData));
  }

  return files;
}

/**
 * Export session statistics to JSON.
 */
export function exportStatisticsToJSON(
  sessionId: string,
  statistics: SessionStatistics
): string {
  return JSON.stringify(
    {
      session_id: sessionId,
      statistics,
      exported_at: new Date().toISOString(),
    },
    null,
    2
  );
}

/**
 * Export advanced analytics to JSON.
 */
export function exportAnalyticsToJSON(analytics: AdvancedAnalytics): string {
  return JSON.stringify(
    {
      ...analytics,
      exported_at: new Date().toISOString(),
    },
    null,
    2
  );
}

/**
 * Export data based on configuration.
 */
export function exportData(
  config: ExportConfig,
  sessionId: string,
  statistics: SessionStatistics,
  analytics: AdvancedAnalytics
): Map<string, string> {
  const files = new Map<string, string>();

  if (config.format === 'csv') {
    if (config.sections.statistics) {
      files.set(`${sessionId}_statistics.csv`, exportStatisticsToCSV(sessionId, statistics));
      files.set(`${sessionId}_tool_stats.csv`, exportToolStatsToCSV(statistics));
    }

    if (config.sections.analytics) {
      const analyticsFiles = exportAnalyticsToCSV(analytics);
      analyticsFiles.forEach((content, filename) => {
        files.set(`${sessionId}_${filename}`, content);
      });
    }
  } else {
    // JSON format
    if (config.sections.statistics) {
      files.set(`${sessionId}_statistics.json`, exportStatisticsToJSON(sessionId, statistics));
    }

    if (config.sections.analytics) {
      files.set(`${sessionId}_analytics.json`, exportAnalyticsToJSON(analytics));
    }
  }

  return files;
}

/**
 * Download a file in the browser.
 */
export function downloadFile(filename: string, content: string, mimeType: string = 'text/plain'): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * Download multiple files as individual downloads.
 */
export function downloadFiles(files: Map<string, string>, format: 'csv' | 'json'): void {
  const mimeType = format === 'csv' ? 'text/csv' : 'application/json';

  files.forEach((content, filename) => {
    setTimeout(() => {
      downloadFile(filename, content, mimeType);
    }, 100); // Small delay between downloads to avoid browser blocking
  });
}
