/**
 * TypeScript types for advanced analytics features.
 *
 * These types support features like:
 * - Token usage heatmaps
 * - Performance bottleneck identification
 * - Tool usage pattern analysis
 * - Subagent efficiency metrics
 * - Session comparisons
 */

import type { SessionStatistics } from './session';

/**
 * Token usage data point for heatmap visualization.
 */
export interface TokenUsageDataPoint {
  timestamp: string;
  tokens: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
  messageType: 'user' | 'assistant' | 'system';
  messageUuid: string;
}

/**
 * Time-based token usage heatmap data.
 */
export interface TokenUsageHeatmap {
  dataPoints: TokenUsageDataPoint[];
  timeRange: {
    start: string;
    end: string;
  };
  totalTokens: number;
  peakUsage: {
    timestamp: string;
    tokens: number;
  };
}

/**
 * Expensive operation identified in the session.
 */
export interface ExpensiveOperation {
  messageUuid: string;
  timestamp: string;
  type: 'tool_call' | 'message' | 'subagent';
  name: string;
  tokens: number;
  duration?: number; // in seconds
  costRank: number; // 1 = most expensive
  details: {
    toolName?: string;
    agentType?: string;
    errorOccurred?: boolean;
  };
}

/**
 * Tool usage pattern analysis.
 */
export interface ToolUsagePattern {
  toolName: string;
  totalCalls: number;
  averageTokensPerCall: number;
  successRate: number;
  averageDuration?: number; // in seconds
  peakUsageTime?: string;
  commonParameters: Record<string, number>; // parameter name -> usage count
  errorPatterns?: {
    errorType: string;
    count: number;
  }[];
}

/**
 * Subagent efficiency metrics.
 */
export interface SubagentEfficiency {
  agentType: string;
  totalInvocations: number;
  averageMessages: number;
  averageTokens: number;
  averageDuration: number; // in seconds
  successRate: number;
  tokensPerMinute: number;
  efficiencyScore: number; // 0-100, higher is better
  recommendations: string[];
}

/**
 * Performance bottleneck identified in the session.
 */
export interface PerformanceBottleneck {
  type: 'token_spike' | 'long_duration' | 'high_error_rate' | 'inefficient_tool';
  severity: 'low' | 'medium' | 'high';
  description: string;
  affectedComponent: string;
  impactMetrics: {
    tokensWasted?: number;
    timeWasted?: number; // in seconds
    errorCount?: number;
  };
  recommendation: string;
  relatedMessages: string[]; // message UUIDs
}

/**
 * Session comparison data for comparing two sessions.
 */
export interface SessionComparison {
  session1: {
    sessionId: string;
    statistics: SessionStatistics;
  };
  session2: {
    sessionId: string;
    statistics: SessionStatistics;
  };
  differences: {
    totalTokensDiff: number;
    totalTokensDiffPercent: number;
    messageDiff: number;
    toolCallsDiff: number;
    durationDiff: number; // in seconds
    efficiencyScoreDiff: number;
  };
  insights: string[];
}

/**
 * Usage-based recommendation.
 */
export interface UsageRecommendation {
  category: 'efficiency' | 'cost' | 'performance' | 'best-practice';
  priority: 'low' | 'medium' | 'high';
  title: string;
  description: string;
  potentialSavings?: {
    tokens?: number;
    time?: number; // in seconds
  };
  actionItems: string[];
}

/**
 * Complete advanced analytics data.
 */
export interface AdvancedAnalytics {
  sessionId: string;
  tokenUsageHeatmap: TokenUsageHeatmap;
  expensiveOperations: ExpensiveOperation[];
  toolUsagePatterns: ToolUsagePattern[];
  subagentEfficiency: SubagentEfficiency[];
  performanceBottlenecks: PerformanceBottleneck[];
  recommendations: UsageRecommendation[];
}

/**
 * Export format options.
 */
export type ExportFormat = 'csv' | 'json';

/**
 * Export configuration.
 */
export interface ExportConfig {
  format: ExportFormat;
  includeRawData: boolean;
  includeCharts: boolean; // for future PDF export
  sections: {
    statistics: boolean;
    analytics: boolean;
    toolUsage: boolean;
    subagents: boolean;
    recommendations: boolean;
  };
}
