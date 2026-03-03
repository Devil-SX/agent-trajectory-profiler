/**
 * MessageTimeline component for displaying session messages with a minimap navigator.
 *
 * Features:
 * - Scrollable message timeline with windowed rendering for long sessions
 * - Right-side minimap (desktop) with user/model/tool activity curves
 * - Click/drag minimap navigation synced with main scroll viewport
 * - Anomaly markers (model stall + tool error) with jump + temporary highlight
 * - Syntax highlighting for fenced code blocks
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import toast from 'react-hot-toast';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useSessionDetailQuery } from '../hooks/useSessionsQuery';
import type {
  MessageRecord,
  Session,
  SubagentType,
  TextContent,
  ToolResultContent,
  ToolUseContent,
} from '../types/session';
import { SubagentSession } from './SubagentSession';
import { ToolCallBlock } from './ToolCallBlock';
import './MessageTimeline.css';

interface MessageTimelineProps {
  sessionId: string;
  autoScrollToBottom?: boolean;
}

type TimelineRole = 'user' | 'model' | 'tool';
type TimelineAnomalyType = 'model_stall' | 'tool_error';

interface TimelineAnomaly {
  type: TimelineAnomalyType;
  messageUuid: string;
  messageIndex: number;
  timestamp: string;
  label: string;
}

interface ScrollMetrics {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
}

const ESTIMATED_ROW_HEIGHT = 220;
const OVERSCAN_COUNT = 8;
const MINIMAP_BUCKETS = 72;
const MINIMAP_WIDTH = 104;
const MINIMAP_HEIGHT = 420;
const MODEL_STALL_SECONDS = 600;
const MESSAGE_HIGHLIGHT_MS = 2200;

const FALLBACK_TOOL_USE_NAME = 'Tool Result';

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function binarySearchPrefix(prefix: number[], target: number): number {
  let low = 0;
  let high = Math.max(0, prefix.length - 2);
  while (low <= high) {
    const mid = Math.floor((low + high) / 2);
    if (prefix[mid + 1] <= target) {
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return clamp(low, 0, Math.max(0, prefix.length - 2));
}

function buildSmoothPath(values: number[], width: number, height: number): string {
  if (values.length === 0) {
    return '';
  }

  const topPadding = 8;
  const bottomPadding = 8;
  const leftPadding = 8;
  const rightPadding = 10;
  const usableHeight = Math.max(1, height - topPadding - bottomPadding);
  const usableWidth = Math.max(1, width - leftPadding - rightPadding);
  const maxValue = Math.max(...values, 1);

  const points = values.map((value, index) => {
    const y = topPadding + (index / Math.max(values.length - 1, 1)) * usableHeight;
    const x = leftPadding + (value / maxValue) * usableWidth;
    return { x, y };
  });

  if (points.length === 1) {
    return `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  }

  let path = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const midX = (previous.x + current.x) / 2;
    const midY = (previous.y + current.y) / 2;
    path += ` Q ${previous.x.toFixed(2)} ${previous.y.toFixed(2)} ${midX.toFixed(2)} ${midY.toFixed(2)}`;
    if (index === points.length - 1) {
      path += ` T ${current.x.toFixed(2)} ${current.y.toFixed(2)}`;
    }
  }

  return path;
}

function getMessageSource(message: MessageRecord): 'user' | 'assistant' | 'subagent' {
  if (message.isSidechain) {
    return 'subagent';
  }
  if (message.message?.role === 'user') {
    return 'user';
  }
  return 'assistant';
}

function classifyTimelineRole(message: MessageRecord): TimelineRole {
  if (message.message?.role === 'user') {
    return 'user';
  }

  const content = message.message?.content;
  if (Array.isArray(content)) {
    const hasToolUse = content.some((block) => {
      if (!block || typeof block !== 'object') {
        return false;
      }
      const typed = block as Record<string, unknown>;
      return typed.type === 'tool_use';
    });
    if (hasToolUse) {
      return 'tool';
    }
  }

  return 'model';
}

function inferSubagentType(messages: MessageRecord[]): SubagentType {
  for (const msg of messages) {
    if (!msg.message?.content || !Array.isArray(msg.message.content)) {
      continue;
    }

    for (const block of msg.message.content) {
      if (!block || typeof block !== 'object') {
        continue;
      }
      const toolBlock = block as Record<string, unknown>;
      if (toolBlock.type !== 'tool_use' || typeof toolBlock.name !== 'string') {
        continue;
      }

      const toolName = toolBlock.name.toLowerCase();
      if (toolName.includes('explore') || toolName.includes('glob') || toolName.includes('grep')) {
        return 'Explore';
      }
      if (toolName.includes('bash') || toolName.includes('command')) {
        return 'Bash';
      }
      if (toolName.includes('plan')) {
        return 'Plan';
      }
      if (toolName.includes('test')) {
        return 'test-runner';
      }
    }
  }

  return 'other';
}

function isToolResultOnlyMessage(message: MessageRecord): boolean {
  const content = message.message?.content;
  if (!Array.isArray(content) || content.length === 0) {
    return false;
  }
  return content.every((block) => {
    if (!block || typeof block !== 'object') {
      return false;
    }
    const typed = block as Record<string, unknown>;
    return typed.type === 'tool_result';
  });
}

export function MessageTimeline({ sessionId, autoScrollToBottom = true }: MessageTimelineProps) {
  const { data, isLoading, error: queryError } = useSessionDetailQuery(sessionId);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const minimapTrackRef = useRef<HTMLDivElement>(null);
  const clearHighlightTimeoutRef = useRef<number | null>(null);
  const isDraggingViewportRef = useRef(false);
  const dragOffsetRef = useRef(0);
  const [measuredHeights, setMeasuredHeights] = useState<Record<string, number>>({});
  const [scrollMetrics, setScrollMetrics] = useState<ScrollMetrics>({
    scrollTop: 0,
    scrollHeight: 1,
    clientHeight: 1,
  });
  const [showModelStalls, setShowModelStalls] = useState(true);
  const [showToolErrors, setShowToolErrors] = useState(true);
  const [highlightedMessageUuid, setHighlightedMessageUuid] = useState<string | null>(null);

  const session: Session | null = data?.session ?? null;
  const loading = isLoading;
  const error = queryError?.message ?? null;

  const {
    mainMessages,
    rawMainMessageCount,
    linkedToolResultsById,
    toolUseById,
    subagentsByParent,
    subagentGroups,
  } = useMemo(() => {
    if (!session || session.messages.length === 0) {
      return {
        mainMessages: [] as MessageRecord[],
        rawMainMessageCount: 0,
        linkedToolResultsById: new Map<string, ToolResultContent>(),
        toolUseById: new Map<string, ToolUseContent>(),
        subagentsByParent: new Map<string, Map<string, { agentId: string; messages: MessageRecord[] }>>(),
        subagentGroups: new Map<string, { agentId: string; messages: MessageRecord[] }>(),
      };
    }

    const baseMessages = session.messages.filter(
      (msg) => (msg.type === 'user' || msg.type === 'assistant') && !msg.isSidechain
    );
    const toolUseById = new Map<string, ToolUseContent>();
    const linkedToolResultsById = new Map<string, ToolResultContent>();
    const messagesToHide = new Set<string>();

    baseMessages.forEach((msg) => {
      const content = msg.message?.content;
      if (!Array.isArray(content)) {
        return;
      }

      content.forEach((block) => {
        if (!block || typeof block !== 'object') {
          return;
        }

        const typed = block as Record<string, unknown>;
        if (
          typed.type === 'tool_use' &&
          typeof typed.id === 'string' &&
          typeof typed.name === 'string' &&
          typed.input &&
          typeof typed.input === 'object'
        ) {
          if (!toolUseById.has(typed.id)) {
            toolUseById.set(typed.id, typed as unknown as ToolUseContent);
          }
          return;
        }

        if (typed.type === 'tool_result' && typeof typed.tool_use_id === 'string') {
          if (!linkedToolResultsById.has(typed.tool_use_id)) {
            linkedToolResultsById.set(typed.tool_use_id, typed as unknown as ToolResultContent);
          }
          if (isToolResultOnlyMessage(msg) && toolUseById.has(typed.tool_use_id)) {
            messagesToHide.add(msg.uuid);
          }
        }
      });
    });

    const filteredBaseMessages = baseMessages.filter((msg) => !messagesToHide.has(msg.uuid));

    const groups = new Map<string, { agentId: string; messages: MessageRecord[] }>();
    session.messages
      .filter((msg) => msg.isSidechain && msg.agentId)
      .forEach((msg) => {
        const key = `${msg.parentUuid || 'root'}_${msg.agentId}`;
        const existing = groups.get(key);
        if (existing) {
          existing.messages.push(msg);
        } else {
          groups.set(key, { agentId: msg.agentId!, messages: [msg] });
        }
      });

    const byParent = new Map<string, Map<string, { agentId: string; messages: MessageRecord[] }>>();
    groups.forEach((group, key) => {
      const parentUuid = key.split('_')[0];
      const parentMap = byParent.get(parentUuid) ?? new Map();
      parentMap.set(key, group);
      byParent.set(parentUuid, parentMap);
    });

    return {
      mainMessages: filteredBaseMessages,
      rawMainMessageCount: baseMessages.length,
      linkedToolResultsById,
      toolUseById,
      subagentsByParent: byParent,
      subagentGroups: groups,
    };
  }, [session]);

  const messageIndexByUuid = useMemo(() => {
    const indexByUuid = new Map<string, number>();
    mainMessages.forEach((message, index) => {
      indexByUuid.set(message.uuid, index);
    });
    return indexByUuid;
  }, [mainMessages]);

  const formatTimestamp = useMemo(
    () =>
      (timestamp: string): string => {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('en-US', {
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
        });
      },
    []
  );

  const timelineSeries = useMemo(() => {
    const modelBuckets = Array.from({ length: MINIMAP_BUCKETS }, () => 0);
    const toolBuckets = Array.from({ length: MINIMAP_BUCKETS }, () => 0);
    const userBuckets = Array.from({ length: MINIMAP_BUCKETS }, () => 0);
    const anomalies: TimelineAnomaly[] = [];

    if (mainMessages.length === 0) {
      return { modelBuckets, toolBuckets, userBuckets, anomalies };
    }

    const timestampAt = (index: number): number => {
      const value = Date.parse(mainMessages[index].timestamp);
      return Number.isFinite(value) ? value : 0;
    };

    const addToBucket = (role: TimelineRole, bucketIndex: number, value: number) => {
      if (role === 'model') {
        modelBuckets[bucketIndex] += value;
      } else if (role === 'tool') {
        toolBuckets[bucketIndex] += value;
      } else {
        userBuckets[bucketIndex] += value;
      }
    };

    for (let index = 0; index < mainMessages.length; index += 1) {
      const message = mainMessages[index];
      const role = classifyTimelineRole(message);
      const currentTime = timestampAt(index);
      const nextTime = index < mainMessages.length - 1 ? timestampAt(index + 1) : currentTime + 1;
      const deltaSeconds = clamp((nextTime - currentTime) / 1000, 1, MODEL_STALL_SECONDS * 2);
      const bucketIndex = clamp(
        Math.floor((index / Math.max(mainMessages.length - 1, 1)) * (MINIMAP_BUCKETS - 1)),
        0,
        MINIMAP_BUCKETS - 1
      );
      addToBucket(role, bucketIndex, deltaSeconds);

      if (index < mainMessages.length - 1) {
        const gapSeconds = (timestampAt(index + 1) - currentTime) / 1000;
        const nextMessage = mainMessages[index + 1];
        if (gapSeconds >= MODEL_STALL_SECONDS && nextMessage.message?.role === 'assistant') {
          anomalies.push({
            type: 'model_stall',
            messageUuid: nextMessage.uuid,
            messageIndex: index + 1,
            timestamp: nextMessage.timestamp,
            label: `Model stall ${Math.round(gapSeconds)}s`,
          });
        }
      }

      const content = message.message?.content;
      if (Array.isArray(content)) {
        const hasToolError = content.some((block) => {
          if (!block || typeof block !== 'object') {
            return false;
          }
          const typed = block as Record<string, unknown>;
          return typed.type === 'tool_result' && Boolean(typed.is_error);
        });
        if (hasToolError) {
          anomalies.push({
            type: 'tool_error',
            messageUuid: message.uuid,
            messageIndex: index,
            timestamp: message.timestamp,
            label: 'Tool error',
          });
        }
      }
    }

    return { modelBuckets, toolBuckets, userBuckets, anomalies };
  }, [mainMessages]);

  const filteredAnomalies = useMemo(
    () =>
      timelineSeries.anomalies.filter(
        (anomaly) =>
          (anomaly.type === 'model_stall' && showModelStalls) ||
          (anomaly.type === 'tool_error' && showToolErrors)
      ),
    [showModelStalls, showToolErrors, timelineSeries.anomalies]
  );

  const heightModel = useMemo(() => {
    const heights = mainMessages.map(
      (message) => measuredHeights[message.uuid] ?? ESTIMATED_ROW_HEIGHT
    );
    const prefixSums = new Array<number>(heights.length + 1).fill(0);
    for (let index = 0; index < heights.length; index += 1) {
      prefixSums[index + 1] = prefixSums[index] + heights[index];
    }
    return {
      heights,
      prefixSums,
      totalHeight: prefixSums[prefixSums.length - 1] ?? 0,
    };
  }, [mainMessages, measuredHeights]);

  const updateScrollMetrics = useCallback(() => {
    if (!messagesContainerRef.current) {
      return;
    }

    const container = messagesContainerRef.current;
    setScrollMetrics({
      scrollTop: container.scrollTop,
      scrollHeight: Math.max(container.scrollHeight, 1),
      clientHeight: Math.max(container.clientHeight, 1),
    });
  }, []);

  const visibleWindow = useMemo(() => {
    const total = mainMessages.length;
    if (total === 0) {
      return { start: 0, end: 0 };
    }

    const viewportTop = scrollMetrics.scrollTop;
    const viewportBottom = viewportTop + scrollMetrics.clientHeight;
    const startBase = binarySearchPrefix(heightModel.prefixSums, viewportTop);
    const endBase = binarySearchPrefix(heightModel.prefixSums, viewportBottom) + 1;

    return {
      start: clamp(startBase - OVERSCAN_COUNT, 0, total),
      end: clamp(endBase + OVERSCAN_COUNT, 0, total),
    };
  }, [heightModel.prefixSums, mainMessages.length, scrollMetrics.clientHeight, scrollMetrics.scrollTop]);

  const visibleMessages = useMemo(
    () => mainMessages.slice(visibleWindow.start, visibleWindow.end),
    [mainMessages, visibleWindow.end, visibleWindow.start]
  );

  const visibleTopSpacer = heightModel.prefixSums[visibleWindow.start] ?? 0;
  const visibleBottomSpacer = Math.max(
    0,
    heightModel.totalHeight - (heightModel.prefixSums[visibleWindow.end] ?? 0)
  );

  const minimapViewportRatio = useMemo(() => {
    const maxScroll = Math.max(1, scrollMetrics.scrollHeight - scrollMetrics.clientHeight);
    const topRatio = scrollMetrics.scrollTop / maxScroll;
    const heightRatio = Math.min(1, scrollMetrics.clientHeight / scrollMetrics.scrollHeight);
    return {
      top: clamp(topRatio, 0, 1),
      height: clamp(heightRatio, 0.06, 1),
    };
  }, [scrollMetrics.clientHeight, scrollMetrics.scrollHeight, scrollMetrics.scrollTop]);

  const minimapPaths = useMemo(
    () => ({
      user: buildSmoothPath(timelineSeries.userBuckets, MINIMAP_WIDTH, MINIMAP_HEIGHT),
      model: buildSmoothPath(timelineSeries.modelBuckets, MINIMAP_WIDTH, MINIMAP_HEIGHT),
      tool: buildSmoothPath(timelineSeries.toolBuckets, MINIMAP_WIDTH, MINIMAP_HEIGHT),
    }),
    [timelineSeries.modelBuckets, timelineSeries.toolBuckets, timelineSeries.userBuckets]
  );

  const setMessageNode = (uuid: string) => (node: HTMLDivElement | null) => {
    if (!node) {
      return;
    }

    const measured = Math.max(80, Math.round(node.getBoundingClientRect().height));
    setMeasuredHeights((previous) => {
      const previousValue = previous[uuid] ?? ESTIMATED_ROW_HEIGHT;
      if (Math.abs(previousValue - measured) <= 1) {
        return previous;
      }
      return {
        ...previous,
        [uuid]: measured,
      };
    });
  };

  const scrollToLatest = useCallback((behavior: ScrollBehavior = 'smooth') => {
    if (!messagesContainerRef.current) {
      return;
    }
    messagesContainerRef.current.scrollTo({
      top: messagesContainerRef.current.scrollHeight,
      behavior,
    });
  }, []);

  const scrollToMessageIndex = useCallback(
    (index: number, behavior: ScrollBehavior = 'smooth') => {
      if (!messagesContainerRef.current || mainMessages.length === 0) {
        return;
      }

      const container = messagesContainerRef.current;
      const clampedIndex = clamp(index, 0, mainMessages.length - 1);
      const rowTop = heightModel.prefixSums[clampedIndex] ?? 0;
      const rowHeight = heightModel.heights[clampedIndex] ?? ESTIMATED_ROW_HEIGHT;
      const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
      const centeredTop = rowTop - container.clientHeight * 0.35 + rowHeight * 0.5;
      const targetTop = clamp(centeredTop, 0, maxScrollTop);

      container.scrollTo({
        top: targetTop,
        behavior,
      });
    },
    [heightModel.heights, heightModel.prefixSums, mainMessages.length]
  );

  const jumpByViewportRatio = useCallback((ratio: number, behavior: ScrollBehavior = 'auto') => {
    if (!messagesContainerRef.current) {
      return;
    }

    const container = messagesContainerRef.current;
    const maxScrollTop = Math.max(0, container.scrollHeight - container.clientHeight);
    container.scrollTo({
      top: clamp(ratio, 0, 1) * maxScrollTop,
      behavior,
    });
  }, []);

  const highlightMessage = useCallback((messageUuid: string) => {
    setHighlightedMessageUuid(messageUuid);
    if (clearHighlightTimeoutRef.current !== null) {
      window.clearTimeout(clearHighlightTimeoutRef.current);
    }
    clearHighlightTimeoutRef.current = window.setTimeout(() => {
      setHighlightedMessageUuid((current) => (current === messageUuid ? null : current));
      clearHighlightTimeoutRef.current = null;
    }, MESSAGE_HIGHLIGHT_MS);
  }, []);

  const jumpToMessageByUuid = useCallback(
    (messageUuid: string, behavior: ScrollBehavior = 'smooth') => {
      const messageIndex = messageIndexByUuid.get(messageUuid);
      if (messageIndex === undefined) {
        return;
      }
      scrollToMessageIndex(messageIndex, behavior);
      highlightMessage(messageUuid);
    },
    [highlightMessage, messageIndexByUuid, scrollToMessageIndex]
  );

  const handleMinimapTrackClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!minimapTrackRef.current) {
        return;
      }
      const rect = minimapTrackRef.current.getBoundingClientRect();
      const clickRatio = (event.clientY - rect.top) / Math.max(rect.height, 1);
      const targetTopRatio = clamp(clickRatio - minimapViewportRatio.height / 2, 0, 1);
      jumpByViewportRatio(targetTopRatio, 'auto');
    },
    [jumpByViewportRatio, minimapViewportRatio.height]
  );

  const handleViewportPointerDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (!minimapTrackRef.current) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();

    const viewportRect = event.currentTarget.getBoundingClientRect();
    dragOffsetRef.current = event.clientY - viewportRect.top;
    isDraggingViewportRef.current = true;
  }, []);

  const renderTextWithCodeBlocks = useCallback((text: string, baseIndex: number): ReactElement | ReactElement[] => {
    const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
    const parts: ReactElement[] = [];
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    let matchIndex = 0;

    while ((match = codeBlockRegex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        const textBefore = text.substring(lastIndex, match.index);
        parts.push(
          <p key={`text-${baseIndex}-${matchIndex}`} className="message-text">
            {textBefore}
          </p>
        );
      }

      const language = match[1] || 'text';
      const code = match[2];
      parts.push(
        <div key={`code-${baseIndex}-${matchIndex}`} className="code-block-container">
          <div className="code-block-header">
            <span className="code-language">{language}</span>
          </div>
          <SyntaxHighlighter language={language} style={vscDarkPlus} customStyle={{ margin: 0 }}>
            {code}
          </SyntaxHighlighter>
        </div>
      );

      lastIndex = match.index + match[0].length;
      matchIndex += 1;
    }

    if (lastIndex < text.length) {
      const remainingText = text.substring(lastIndex);
      parts.push(
        <p key={`text-${baseIndex}-${matchIndex}`} className="message-text">
          {remainingText}
        </p>
      );
    }

    return parts.length > 0 ? parts : <p className="message-text">{text}</p>;
  }, []);

  const renderContentBlock = useCallback(
    (
      content: unknown,
      index: number,
      allContent: unknown[],
      message: MessageRecord
    ): ReactElement | null => {
      if (!content || typeof content !== 'object') {
        return null;
      }

      const block = content as Record<string, unknown>;

      if (block.type === 'text') {
        const textBlock = block as unknown as TextContent;
        const rendered = renderTextWithCodeBlocks(textBlock.text, index);
        return Array.isArray(rendered) ? <>{rendered}</> : rendered;
      }

      if (block.type === 'thinking') {
        return (
          <div key={index} className="thinking-block">
            <span className="thinking-label">Thinking</span>
          </div>
        );
      }

      if (block.type === 'tool_use') {
        const toolBlock = block as unknown as ToolUseContent;
        const toolResult = allContent.find((entry) => {
          if (!entry || typeof entry !== 'object') {
            return false;
          }
          const typed = entry as Record<string, unknown>;
          return typed.type === 'tool_result' && typed.tool_use_id === toolBlock.id;
        }) as ToolResultContent | undefined
          ?? linkedToolResultsById.get(toolBlock.id);

        return <ToolCallBlock key={index} toolUse={toolBlock} toolResult={toolResult} />;
      }

      if (block.type === 'tool_result') {
        const toolResultBlock = block as unknown as ToolResultContent;
        const linkedToolUse = toolUseById.get(toolResultBlock.tool_use_id);
        const syntheticToolUse: ToolUseContent = linkedToolUse ?? {
          type: 'tool_use',
          id: toolResultBlock.tool_use_id,
          name: FALLBACK_TOOL_USE_NAME,
          input: {},
        };

        return (
          <ToolCallBlock
            key={`${message.uuid}-${index}-tool-result`}
            toolUse={syntheticToolUse}
            toolResult={toolResultBlock}
          />
        );
      }

      return null;
    },
    [linkedToolResultsById, renderTextWithCodeBlocks, toolUseById]
  );

  const renderMessageContent = useCallback(
    (message: MessageRecord): ReactElement => {
      if (!message.message || !message.message.content) {
        return <p className="message-text">(Empty message)</p>;
      }

      const content = message.message.content;
      if (typeof content === 'string') {
        const rendered = renderTextWithCodeBlocks(content, 0);
        return Array.isArray(rendered) ? <>{rendered}</> : rendered;
      }

      if (Array.isArray(content)) {
        const blocks = content
          .map((block, index) => renderContentBlock(block, index, content, message))
          .filter((entry): entry is ReactElement => entry !== null);
        return blocks.length > 0 ? <>{blocks}</> : <p className="message-text">(Empty content)</p>;
      }

      return <p className="message-text">(Unknown content format)</p>;
    },
    [renderContentBlock, renderTextWithCodeBlocks]
  );

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  useEffect(() => {
    if (autoScrollToBottom && !loading) {
      scrollToLatest('smooth');
    }
  }, [autoScrollToBottom, loading, scrollToLatest, session]);

  useEffect(() => {
    if (!autoScrollToBottom && !loading && messagesContainerRef.current) {
      messagesContainerRef.current.scrollTo({ top: 0, behavior: 'auto' });
      updateScrollMetrics();
    }
  }, [sessionId, autoScrollToBottom, loading, updateScrollMetrics]);

  useEffect(() => {
    updateScrollMetrics();
  }, [heightModel.totalHeight, sessionId, updateScrollMetrics]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) {
      return undefined;
    }

    updateScrollMetrics();

    const onScroll = () => updateScrollMetrics();
    container.addEventListener('scroll', onScroll, { passive: true });

    const observer = new ResizeObserver(() => updateScrollMetrics());
    observer.observe(container);

    return () => {
      observer.disconnect();
      container.removeEventListener('scroll', onScroll);
    };
  }, [sessionId, updateScrollMetrics]);

  useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      if (!isDraggingViewportRef.current || !minimapTrackRef.current) {
        return;
      }

      const rect = minimapTrackRef.current.getBoundingClientRect();
      const ratio = (event.clientY - rect.top - dragOffsetRef.current) / Math.max(rect.height, 1);
      jumpByViewportRatio(ratio, 'auto');
    };

    const onPointerUp = () => {
      isDraggingViewportRef.current = false;
    };

    window.addEventListener('pointermove', onPointerMove);
    window.addEventListener('pointerup', onPointerUp);

    return () => {
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
    };
  }, [jumpByViewportRatio]);

  useEffect(() => {
    return () => {
      if (clearHighlightTimeoutRef.current !== null) {
        window.clearTimeout(clearHighlightTimeoutRef.current);
      }
    };
  }, []);

  if (loading) {
    return (
      <div className="message-timeline loading">
        <div className="loading-spinner">Loading messages...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="message-timeline error">
        <div className="error-message">
          <h3>Error loading session</h3>
          <p>{error}</p>
        </div>
      </div>
    );
  }

  if (!session || session.messages.length === 0) {
    return (
      <div className="message-timeline empty">
        <p>No messages in this session.</p>
      </div>
    );
  }

  const viewportTopPercent = minimapViewportRatio.top * 100;
  const viewportHeightPercent = minimapViewportRatio.height * 100;

  return (
    <div className="message-timeline" data-testid="message-timeline">
      <div className="timeline-header">
        <h2>Conversation Timeline</h2>
        <div className="timeline-header-meta">
          <p className="message-count">
            {mainMessages.length} message{mainMessages.length !== 1 ? 's' : ''}
            {rawMainMessageCount > mainMessages.length
              ? ` (filtered from ${rawMainMessageCount})`
              : ''}
            {subagentGroups.size > 0
              ? ` · ${subagentGroups.size} subagent session${subagentGroups.size !== 1 ? 's' : ''}`
              : ''}
            <span className="message-visible-count" data-testid="timeline-visible-count">
              {' '}
              · Rendered {visibleMessages.length}
            </span>
          </p>
          {!autoScrollToBottom && (
            <button type="button" className="timeline-jump-button" onClick={() => scrollToLatest('smooth')}>
              Jump to latest
            </button>
          )}
        </div>
      </div>

      <div className="timeline-layout">
        <div className="messages-panel">
          <div className="messages-container" ref={messagesContainerRef} data-testid="timeline-message-scroll">
            <div className="timeline-virtual-spacer" style={{ height: `${visibleTopSpacer}px` }} aria-hidden="true" />

            {visibleMessages.map((message, visibleIndex) => {
              const actualIndex = visibleWindow.start + visibleIndex;
              const source = getMessageSource(message);
              const isHighlighted = highlightedMessageUuid === message.uuid;
              return (
                <div
                  key={message.uuid}
                  ref={setMessageNode(message.uuid)}
                  className={`message-row ${isHighlighted ? 'message-row-highlighted' : ''}`}
                  data-message-uuid={message.uuid}
                  data-message-index={actualIndex}
                >
                  <div className={`message-bubble ${source}`}>
                    <div className="message-header">
                      <span className="message-source">{source}</span>
                      <span className="message-timestamp">{formatTimestamp(message.timestamp)}</span>
                    </div>
                    <div className="message-content">{renderMessageContent(message)}</div>
                  </div>

                  {subagentsByParent.has(message.uuid) && (
                    <div className="subagent-sessions-container">
                      {Array.from(subagentsByParent.get(message.uuid)!.values()).map((group) => (
                        <SubagentSession
                          key={group.agentId}
                          agentId={group.agentId}
                          agentType={inferSubagentType(group.messages)}
                          messages={group.messages}
                          renderMessageContent={renderMessageContent}
                          formatTimestamp={formatTimestamp}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            <div className="timeline-virtual-spacer" style={{ height: `${visibleBottomSpacer}px` }} aria-hidden="true" />
          </div>
        </div>

        <aside className="timeline-minimap-panel" aria-label="Session minimap" data-testid="timeline-minimap-panel">
          <div className="timeline-minimap-controls">
            <label className="timeline-toggle">
              <input
                type="checkbox"
                checked={showModelStalls}
                onChange={(event) => setShowModelStalls(event.target.checked)}
                aria-label="Toggle model stall anomalies"
              />
              <span>Model stall</span>
            </label>
            <label className="timeline-toggle">
              <input
                type="checkbox"
                checked={showToolErrors}
                onChange={(event) => setShowToolErrors(event.target.checked)}
                aria-label="Toggle tool error anomalies"
              />
              <span>Tool error</span>
            </label>
          </div>

          <div
            className="timeline-minimap-track"
            ref={minimapTrackRef}
            onClick={handleMinimapTrackClick}
            role="button"
            tabIndex={0}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                const next = clamp(minimapViewportRatio.top + minimapViewportRatio.height / 2, 0, 1);
                jumpByViewportRatio(next, 'auto');
              }
            }}
            aria-label="Minimap track"
            data-testid="timeline-minimap-track"
          >
            <svg
              className="timeline-minimap-svg"
              width={MINIMAP_WIDTH}
              height={MINIMAP_HEIGHT}
              viewBox={`0 0 ${MINIMAP_WIDTH} ${MINIMAP_HEIGHT}`}
              aria-hidden="true"
            >
              <path d={minimapPaths.user} className="timeline-minimap-path user" />
              <path d={minimapPaths.model} className="timeline-minimap-path model" />
              <path d={minimapPaths.tool} className="timeline-minimap-path tool" />
            </svg>

            {filteredAnomalies.map((anomaly, index) => {
              const ratio = anomaly.messageIndex / Math.max(mainMessages.length - 1, 1);
              return (
                <button
                  key={`${anomaly.messageUuid}-${anomaly.type}-${index}`}
                  type="button"
                  className={`timeline-minimap-anomaly timeline-minimap-anomaly--${anomaly.type}`}
                  style={{ top: `${ratio * 100}%` }}
                  onClick={(event) => {
                    event.stopPropagation();
                    jumpToMessageByUuid(anomaly.messageUuid);
                  }}
                  title={`${anomaly.label} · ${formatTimestamp(anomaly.timestamp)}`}
                  aria-label={`Anomaly marker at ${formatTimestamp(anomaly.timestamp)}`}
                  data-testid={`timeline-anomaly-${anomaly.type}`}
                />
              );
            })}

            <div
              className="timeline-minimap-viewport"
              style={{
                top: `${viewportTopPercent}%`,
                height: `${viewportHeightPercent}%`,
              }}
              onPointerDown={handleViewportPointerDown}
              role="presentation"
              data-testid="timeline-minimap-viewport"
            />
          </div>

          <div className="timeline-minimap-legend">
            <span className="legend-item legend-item--user">User</span>
            <span className="legend-item legend-item--model">Model</span>
            <span className="legend-item legend-item--tool">Tool</span>
            <span className="legend-item legend-item--anomaly">Anomaly: {filteredAnomalies.length}</span>
          </div>
        </aside>
      </div>
    </div>
  );
}
