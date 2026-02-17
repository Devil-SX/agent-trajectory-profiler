/**
 * Utility functions to compute advanced analytics from session data.
 */

import type {
  MessageRecord,
  SessionStatistics,
  ToolCallStatistics,
  Session,
} from '../types/session';
import type {
  TokenUsageHeatmap,
  TokenUsageDataPoint,
  ExpensiveOperation,
  ToolUsagePattern,
  SubagentEfficiency,
  PerformanceBottleneck,
  UsageRecommendation,
  AdvancedAnalytics,
  SessionComparison,
} from '../types/analytics';

/**
 * Compute token usage heatmap from session messages.
 */
export function computeTokenUsageHeatmap(messages: MessageRecord[]): TokenUsageHeatmap {
  const dataPoints: TokenUsageDataPoint[] = [];
  let totalTokens = 0;
  let peakUsage = { timestamp: '', tokens: 0 };

  for (const msg of messages) {
    if (!msg.message?.usage) continue;

    const usage = msg.message.usage;
    const tokens =
      (usage.input_tokens || 0) +
      (usage.output_tokens || 0) +
      (usage.cache_creation_input_tokens || 0) +
      (usage.cache_read_input_tokens || 0);

    const dataPoint: TokenUsageDataPoint = {
      timestamp: msg.timestamp,
      tokens,
      inputTokens: usage.input_tokens || 0,
      outputTokens: usage.output_tokens || 0,
      cacheReadTokens: usage.cache_read_input_tokens || 0,
      cacheCreationTokens: usage.cache_creation_input_tokens || 0,
      messageType: msg.message.role as 'user' | 'assistant' | 'system',
      messageUuid: msg.uuid,
    };

    dataPoints.push(dataPoint);
    totalTokens += tokens;

    if (tokens > peakUsage.tokens) {
      peakUsage = { timestamp: msg.timestamp, tokens };
    }
  }

  const timestamps = dataPoints.map((dp) => dp.timestamp).filter(Boolean);
  const timeRange = {
    start: timestamps.length > 0 ? timestamps[0] : '',
    end: timestamps.length > 0 ? timestamps[timestamps.length - 1] : '',
  };

  return {
    dataPoints,
    timeRange,
    totalTokens,
    peakUsage,
  };
}

/**
 * Identify expensive operations in the session.
 */
export function identifyExpensiveOperations(
  messages: MessageRecord[],
  limit: number = 10
): ExpensiveOperation[] {
  const operations: ExpensiveOperation[] = [];

  for (const msg of messages) {
    if (!msg.message?.usage) continue;

    const usage = msg.message.usage;
    const tokens =
      (usage.input_tokens || 0) +
      (usage.output_tokens || 0) +
      (usage.cache_creation_input_tokens || 0) +
      (usage.cache_read_input_tokens || 0);

    // Check for tool calls in message content
    if (Array.isArray(msg.message.content)) {
      for (const block of msg.message.content) {
        if (typeof block === 'object' && block !== null && 'type' in block) {
          if (block.type === 'tool_use' && 'name' in block) {
            operations.push({
              messageUuid: msg.uuid,
              timestamp: msg.timestamp,
              type: 'tool_call',
              name: String(block.name),
              tokens,
              costRank: 0,
              details: {
                toolName: String(block.name),
              },
            });
          }
        }
      }
    }

    // Check for subagent messages
    if (msg.agentId) {
      operations.push({
        messageUuid: msg.uuid,
        timestamp: msg.timestamp,
        type: 'subagent',
        name: `Subagent ${msg.agentId}`,
        tokens,
        costRank: 0,
        details: {
          agentType: 'subagent',
        },
      });
    }

    // Regular message operations
    if (!msg.agentId && tokens > 1000) {
      operations.push({
        messageUuid: msg.uuid,
        timestamp: msg.timestamp,
        type: 'message',
        name: `${msg.message.role} message`,
        tokens,
        costRank: 0,
        details: {},
      });
    }
  }

  // Sort by tokens and assign ranks
  operations.sort((a, b) => b.tokens - a.tokens);
  operations.forEach((op, index) => {
    op.costRank = index + 1;
  });

  return operations.slice(0, limit);
}

/**
 * Analyze tool usage patterns.
 */
export function analyzeToolUsagePatterns(
  toolStats: ToolCallStatistics[],
  messages: MessageRecord[]
): ToolUsagePattern[] {
  const patterns: ToolUsagePattern[] = [];

  for (const tool of toolStats) {
    const avgTokens = tool.count > 0 ? tool.total_tokens / tool.count : 0;
    const successRate =
      tool.success_count + tool.error_count > 0
        ? tool.success_count / (tool.success_count + tool.error_count)
        : 1.0;

    // Find tool usage in messages to analyze parameters
    const commonParameters: Record<string, number> = {};
    const toolMessages = messages.filter((msg) => {
      if (!Array.isArray(msg.message?.content)) return false;
      return msg.message.content.some(
        (block) =>
          typeof block === 'object' &&
          block !== null &&
          'type' in block &&
          block.type === 'tool_use' &&
          'name' in block &&
          block.name === tool.tool_name
      );
    });

    // Analyze parameters
    for (const msg of toolMessages) {
      if (!Array.isArray(msg.message?.content)) continue;
      for (const block of msg.message.content) {
        if (
          typeof block === 'object' &&
          block !== null &&
          'type' in block &&
          block.type === 'tool_use' &&
          'input' in block &&
          typeof block.input === 'object'
        ) {
          const input = block.input as Record<string, unknown>;
          for (const key of Object.keys(input)) {
            commonParameters[key] = (commonParameters[key] || 0) + 1;
          }
        }
      }
    }

    patterns.push({
      toolName: tool.tool_name,
      totalCalls: tool.count,
      averageTokensPerCall: avgTokens,
      successRate,
      averageDuration: tool.avg_latency_seconds || undefined,
      commonParameters,
      errorPatterns: tool.error_count > 0 ? [{ errorType: 'unknown', count: tool.error_count }] : undefined,
    });
  }

  return patterns;
}

/**
 * Calculate subagent efficiency metrics.
 */
export function calculateSubagentEfficiency(
  session: Session,
  statistics: SessionStatistics
): SubagentEfficiency[] {
  const efficiencyMetrics: SubagentEfficiency[] = [];

  for (const [agentType, count] of Object.entries(statistics.subagent_sessions)) {
    // Since Session doesn't have subagent_sessions array, compute from messages
    const subagentMessages = session.messages.filter(
      (msg) => msg.isSidechain && msg.agentId
    );

    if (subagentMessages.length === 0) continue;

    const totalMessages = subagentMessages.length;
    const totalTokens = subagentMessages.reduce((sum, msg) => {
      const usage = msg.message?.usage;
      if (!usage) return sum;
      return sum + (usage.input_tokens + usage.output_tokens);
    }, 0);

    // Estimate duration from message timestamps (approximation)
    const totalDuration = 0; // We don't have explicit duration info

    const avgMessages = count > 0 ? totalMessages / count : 0;
    const avgTokens = count > 0 ? totalTokens / count : 0;
    const avgDuration = count > 0 ? totalDuration / count : 0;
    const tokensPerMinute = avgDuration > 0 ? (avgTokens / avgDuration) * 60 : 0;

    // Simple efficiency score: tokens per minute normalized
    const efficiencyScore = Math.min(100, Math.round((tokensPerMinute / 1000) * 100));

    const recommendations: string[] = [];
    if (efficiencyScore < 30) {
      recommendations.push(`Consider optimizing ${agentType} agent usage`);
    }
    if (avgTokens > 10000) {
      recommendations.push(`${agentType} uses high token count - review task complexity`);
    }
    if (avgDuration > 60) {
      recommendations.push(`${agentType} takes long to complete - consider breaking down tasks`);
    }

    efficiencyMetrics.push({
      agentType,
      totalInvocations: count,
      averageMessages: avgMessages,
      averageTokens: avgTokens,
      averageDuration: avgDuration,
      successRate: 1.0, // Would need error tracking
      tokensPerMinute,
      efficiencyScore,
      recommendations,
    });
  }

  return efficiencyMetrics;
}

/**
 * Identify performance bottlenecks.
 */
export function identifyBottlenecks(
  heatmap: TokenUsageHeatmap,
  toolPatterns: ToolUsagePattern[]
): PerformanceBottleneck[] {
  const bottlenecks: PerformanceBottleneck[] = [];

  // Check for token spikes
  const avgTokens =
    heatmap.dataPoints.reduce((sum, dp) => sum + dp.tokens, 0) / heatmap.dataPoints.length;
  const tokenSpikes = heatmap.dataPoints.filter((dp) => dp.tokens > avgTokens * 3);

  if (tokenSpikes.length > 0) {
    bottlenecks.push({
      type: 'token_spike',
      severity: tokenSpikes.length > 5 ? 'high' : 'medium',
      description: `Detected ${tokenSpikes.length} token usage spikes (>3x average)`,
      affectedComponent: 'Session messages',
      impactMetrics: {
        tokensWasted: tokenSpikes.reduce((sum, dp) => sum + (dp.tokens - avgTokens), 0),
      },
      recommendation: 'Review messages with high token usage and optimize prompts',
      relatedMessages: tokenSpikes.map((dp) => dp.messageUuid),
    });
  }

  // Check for high error rate tools
  const highErrorTools = toolPatterns.filter((p) => p.successRate < 0.7 && p.totalCalls > 3);
  for (const tool of highErrorTools) {
    bottlenecks.push({
      type: 'high_error_rate',
      severity: tool.successRate < 0.5 ? 'high' : 'medium',
      description: `Tool "${tool.toolName}" has ${Math.round((1 - tool.successRate) * 100)}% error rate`,
      affectedComponent: tool.toolName,
      impactMetrics: {
        errorCount: Math.round(tool.totalCalls * (1 - tool.successRate)),
      },
      recommendation: `Review and fix error conditions for ${tool.toolName}`,
      relatedMessages: [],
    });
  }

  // Check for inefficient tools
  const inefficientTools = toolPatterns.filter(
    (p) => p.averageTokensPerCall > 5000 && p.totalCalls > 5
  );
  for (const tool of inefficientTools) {
    bottlenecks.push({
      type: 'inefficient_tool',
      severity: tool.averageTokensPerCall > 10000 ? 'high' : 'medium',
      description: `Tool "${tool.toolName}" uses ${Math.round(tool.averageTokensPerCall)} tokens per call on average`,
      affectedComponent: tool.toolName,
      impactMetrics: {
        tokensWasted: Math.round(tool.averageTokensPerCall * tool.totalCalls * 0.3), // Estimate 30% could be saved
      },
      recommendation: `Optimize ${tool.toolName} usage or consider alternative approaches`,
      relatedMessages: [],
    });
  }

  return bottlenecks;
}

/**
 * Generate usage-based recommendations.
 */
export function generateRecommendations(
  statistics: SessionStatistics,
  bottlenecks: PerformanceBottleneck[],
  toolPatterns: ToolUsagePattern[],
  subagentEfficiency: SubagentEfficiency[]
): UsageRecommendation[] {
  const recommendations: UsageRecommendation[] = [];

  // Cache usage recommendation
  const cacheRatio =
    statistics.total_input_tokens > 0
      ? statistics.cache_read_tokens / statistics.total_input_tokens
      : 0;

  if (cacheRatio < 0.1 && statistics.total_input_tokens > 10000) {
    recommendations.push({
      category: 'cost',
      priority: 'high',
      title: 'Low cache utilization detected',
      description: `Only ${Math.round(cacheRatio * 100)}% of input tokens came from cache. Improving cache usage can reduce costs significantly.`,
      potentialSavings: {
        tokens: Math.round(statistics.total_input_tokens * 0.5),
      },
      actionItems: [
        'Review conversation structure to enable better caching',
        'Consider using system prompts that can be cached',
        'Group similar operations together',
      ],
    });
  }

  // Tool usage recommendations
  const topTools = toolPatterns.slice(0, 5);
  const totalToolTokens = topTools.reduce((sum, t) => sum + t.averageTokensPerCall * t.totalCalls, 0);

  if (totalToolTokens > statistics.total_tokens * 0.5) {
    recommendations.push({
      category: 'efficiency',
      priority: 'medium',
      title: 'Tool calls dominate token usage',
      description: 'Over 50% of tokens are used by tool calls. Consider optimizing tool parameters and results.',
      actionItems: [
        'Review tool input parameters for unnecessary data',
        'Implement result filtering in tools',
        'Consider batching tool operations',
      ],
    });
  }

  // Subagent recommendations
  const inefficientSubagents = subagentEfficiency.filter((s) => s.efficiencyScore < 40);
  if (inefficientSubagents.length > 0) {
    recommendations.push({
      category: 'performance',
      priority: 'medium',
      title: 'Inefficient subagent usage detected',
      description: `${inefficientSubagents.length} subagent type(s) show low efficiency scores.`,
      actionItems: inefficientSubagents.flatMap((s) => s.recommendations),
    });
  }

  // Bottleneck-based recommendations
  for (const bottleneck of bottlenecks) {
    if (bottleneck.severity === 'high') {
      recommendations.push({
        category: 'performance',
        priority: 'high',
        title: bottleneck.description,
        description: bottleneck.recommendation,
        potentialSavings: bottleneck.impactMetrics.tokensWasted
          ? { tokens: bottleneck.impactMetrics.tokensWasted }
          : undefined,
        actionItems: [bottleneck.recommendation],
      });
    }
  }

  // Token usage recommendations
  if (statistics.total_tokens > 100000) {
    recommendations.push({
      category: 'cost',
      priority: 'medium',
      title: 'High token usage session',
      description: `This session used ${statistics.total_tokens.toLocaleString()} tokens. Consider strategies to reduce usage.`,
      actionItems: [
        'Break down complex tasks into smaller sessions',
        'Use more specific prompts to reduce back-and-forth',
        'Enable aggressive caching strategies',
      ],
    });
  }

  return recommendations;
}

/**
 * Compare two sessions.
 */
export function compareSessions(
  session1Stats: SessionStatistics,
  session1Id: string,
  session2Stats: SessionStatistics,
  session2Id: string
): SessionComparison {
  const tokensDiff = session1Stats.total_tokens - session2Stats.total_tokens;
  const tokensDiffPercent =
    session2Stats.total_tokens > 0
      ? (tokensDiff / session2Stats.total_tokens) * 100
      : 0;

  const messageDiff = session1Stats.message_count - session2Stats.message_count;
  const toolCallsDiff = session1Stats.total_tool_calls - session2Stats.total_tool_calls;
  const durationDiff =
    (session1Stats.session_duration_seconds || 0) -
    (session2Stats.session_duration_seconds || 0);

  // Simple efficiency score: messages per token
  const efficiency1 =
    session1Stats.total_tokens > 0
      ? session1Stats.message_count / session1Stats.total_tokens
      : 0;
  const efficiency2 =
    session2Stats.total_tokens > 0
      ? session2Stats.message_count / session2Stats.total_tokens
      : 0;
  const efficiencyScoreDiff = efficiency1 - efficiency2;

  const insights: string[] = [];

  if (Math.abs(tokensDiffPercent) > 20) {
    insights.push(
      `Session 1 uses ${Math.abs(Math.round(tokensDiffPercent))}% ${tokensDiff > 0 ? 'more' : 'fewer'} tokens`
    );
  }

  if (Math.abs(messageDiff) > 5) {
    insights.push(
      `Session 1 has ${Math.abs(messageDiff)} ${messageDiff > 0 ? 'more' : 'fewer'} messages`
    );
  }

  if (efficiencyScoreDiff > 0.0001) {
    insights.push('Session 1 is more efficient (fewer tokens per message)');
  } else if (efficiencyScoreDiff < -0.0001) {
    insights.push('Session 2 is more efficient (fewer tokens per message)');
  }

  return {
    session1: {
      sessionId: session1Id,
      statistics: session1Stats,
    },
    session2: {
      sessionId: session2Id,
      statistics: session2Stats,
    },
    differences: {
      totalTokensDiff: tokensDiff,
      totalTokensDiffPercent: tokensDiffPercent,
      messageDiff,
      toolCallsDiff,
      durationDiff,
      efficiencyScoreDiff,
    },
    insights,
  };
}

/**
 * Compute complete advanced analytics for a session.
 */
export function computeAdvancedAnalytics(
  session: Session,
  statistics: SessionStatistics
): AdvancedAnalytics {
  const heatmap = computeTokenUsageHeatmap(session.messages);
  const expensiveOps = identifyExpensiveOperations(session.messages);
  const toolPatterns = analyzeToolUsagePatterns(statistics.tool_calls, session.messages);
  const subagentEfficiency = calculateSubagentEfficiency(session, statistics);
  const bottlenecks = identifyBottlenecks(heatmap, toolPatterns);
  const recommendations = generateRecommendations(
    statistics,
    bottlenecks,
    toolPatterns,
    subagentEfficiency
  );

  return {
    sessionId: session.metadata.session_id,
    tokenUsageHeatmap: heatmap,
    expensiveOperations: expensiveOps,
    toolUsagePatterns: toolPatterns,
    subagentEfficiency,
    performanceBottlenecks: bottlenecks,
    recommendations,
  };
}
