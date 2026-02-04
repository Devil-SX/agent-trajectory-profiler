/**
 * MessageTimeline component for displaying Claude Code session messages.
 *
 * Features:
 * - Social-media-style scrollable message timeline
 * - Message bubbles styled by source (user/assistant/subagent)
 * - Syntax highlighting for code blocks
 * - Timestamps for each message
 * - Smooth scrolling with keyboard/mouse support
 * - Auto-scroll to bottom on load option
 * - Responsive design
 */

import { useEffect, useRef, useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { fetchSessionDetail } from '../api/sessions';
import type {
  MessageRecord,
  Session,
  TextContent,
  ToolUseContent,
  ToolResultContent,
  SubagentType,
} from '../types/session';
import { SubagentSession } from './SubagentSession';
import './MessageTimeline.css';

interface MessageTimelineProps {
  sessionId: string;
  autoScrollToBottom?: boolean;
}

export function MessageTimeline({ sessionId, autoScrollToBottom = true }: MessageTimelineProps) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const timelineEndRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    async function loadSession() {
      try {
        setLoading(true);
        setError(null);
        const data = await fetchSessionDetail(sessionId);
        setSession(data.session);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load session');
      } finally {
        setLoading(false);
      }
    }

    loadSession();
  }, [sessionId]);

  useEffect(() => {
    if (autoScrollToBottom && timelineEndRef.current && !loading) {
      timelineEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [session, autoScrollToBottom, loading]);

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getMessageSource = (message: MessageRecord): 'user' | 'assistant' | 'subagent' => {
    if (message.isSidechain) {
      return 'subagent';
    }
    if (message.message?.role === 'user') {
      return 'user';
    }
    return 'assistant';
  };

  const renderContentBlock = (content: unknown, index: number) => {
    if (!content || typeof content !== 'object') {
      return null;
    }

    const block = content as Record<string, unknown>;

    if (block.type === 'text') {
      const textBlock = block as unknown as TextContent;
      return renderTextWithCodeBlocks(textBlock.text, index);
    }

    if (block.type === 'thinking') {
      return (
        <div key={index} className="thinking-block">
          <span className="thinking-label">🤔 Thinking</span>
        </div>
      );
    }

    if (block.type === 'tool_use') {
      const toolBlock = block as unknown as ToolUseContent;
      return (
        <div key={index} className="tool-use-block">
          <span className="tool-label">🔧 Tool: {toolBlock.name}</span>
        </div>
      );
    }

    if (block.type === 'tool_result') {
      const resultBlock = block as unknown as ToolResultContent;
      const isError = resultBlock.is_error;
      return (
        <div key={index} className={`tool-result-block ${isError ? 'error' : ''}`}>
          <span className="tool-result-label">
            {isError ? '❌' : '✓'} Tool Result
          </span>
        </div>
      );
    }

    return null;
  };

  const renderTextWithCodeBlocks = (text: string, baseIndex: number) => {
    // Match code blocks with language specifier: ```language\ncode\n```
    const codeBlockRegex = /```(\w+)?\n([\s\S]*?)```/g;
    const parts: React.ReactElement[] = [];
    let lastIndex = 0;
    let match;
    let matchIndex = 0;

    while ((match = codeBlockRegex.exec(text)) !== null) {
      // Add text before code block
      if (match.index > lastIndex) {
        const textBefore = text.substring(lastIndex, match.index);
        parts.push(
          <p key={`text-${baseIndex}-${matchIndex}`} className="message-text">
            {textBefore}
          </p>
        );
      }

      // Add code block
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
      matchIndex++;
    }

    // Add remaining text
    if (lastIndex < text.length) {
      const remainingText = text.substring(lastIndex);
      parts.push(
        <p key={`text-${baseIndex}-${matchIndex}`} className="message-text">
          {remainingText}
        </p>
      );
    }

    return parts.length > 0 ? parts : <p className="message-text">{text}</p>;
  };

  const renderMessageContent = (message: MessageRecord): React.ReactElement | React.ReactElement[] => {
    if (!message.message || !message.message.content) {
      return <p className="message-text">(Empty message)</p>;
    }

    const content = message.message.content;

    if (typeof content === 'string') {
      const result = renderTextWithCodeBlocks(content, 0);
      return Array.isArray(result) ? <>{result}</> : result;
    }

    if (Array.isArray(content)) {
      const blocks = content.map((block, index) => renderContentBlock(block, index)).filter((b): b is React.ReactElement => b !== null);
      return blocks.length > 0 ? <>{blocks}</> : <p className="message-text">(Empty content)</p>;
    }

    return <p className="message-text">(Unknown content format)</p>;
  };

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

  // Separate main messages from subagent messages
  const mainMessages = session.messages.filter(
    (msg) => (msg.type === 'user' || msg.type === 'assistant') && !msg.isSidechain
  );

  // Group subagent messages by agentId and parent message
  const subagentGroups = new Map<string, { agentId: string; messages: MessageRecord[] }>();
  session.messages
    .filter((msg) => msg.isSidechain && msg.agentId)
    .forEach((msg) => {
      const key = `${msg.parentUuid || 'root'}_${msg.agentId}`;
      if (!subagentGroups.has(key)) {
        subagentGroups.set(key, { agentId: msg.agentId!, messages: [] });
      }
      subagentGroups.get(key)!.messages.push(msg);
    });

  // Build a map of parent UUID to subagent groups
  const subagentsByParent = new Map<string, typeof subagentGroups>();
  subagentGroups.forEach((group, key) => {
    const parentUuid = key.split('_')[0];
    if (!subagentsByParent.has(parentUuid)) {
      subagentsByParent.set(parentUuid, new Map());
    }
    subagentsByParent.get(parentUuid)!.set(key, group);
  });

  // Infer subagent type from messages or default to 'other'
  const inferSubagentType = (messages: MessageRecord[]): SubagentType => {
    // Try to infer from tool use or message content
    for (const msg of messages) {
      if (msg.message?.content) {
        const content = msg.message.content;
        if (Array.isArray(content)) {
          for (const block of content) {
            if (typeof block === 'object' && block !== null && 'type' in block) {
              const toolBlock = block as Record<string, unknown>;
              if (toolBlock.type === 'tool_use' && typeof toolBlock.name === 'string') {
                const toolName = toolBlock.name.toLowerCase();
                if (toolName.includes('explore') || toolName.includes('glob') || toolName.includes('grep')) {
                  return 'Explore' as SubagentType;
                }
                if (toolName.includes('bash') || toolName.includes('command')) {
                  return 'Bash' as SubagentType;
                }
                if (toolName.includes('plan')) {
                  return 'Plan' as SubagentType;
                }
                if (toolName.includes('test')) {
                  return 'test-runner' as SubagentType;
                }
              }
            }
          }
        }
      }
    }
    return 'other' as SubagentType;
  };

  return (
    <div className="message-timeline" ref={timelineRef}>
      <div className="timeline-header">
        <h2>Conversation Timeline</h2>
        <p className="message-count">
          {mainMessages.length} message{mainMessages.length !== 1 ? 's' : ''}
          {subagentGroups.size > 0 && ` · ${subagentGroups.size} subagent session${subagentGroups.size !== 1 ? 's' : ''}`}
        </p>
      </div>
      <div className="messages-container">
        {mainMessages.map((message) => {
          const source = getMessageSource(message);
          return (
            <div key={message.uuid}>
              <div className={`message-bubble ${source}`}>
                <div className="message-header">
                  <span className="message-source">{source}</span>
                  <span className="message-timestamp">{formatTimestamp(message.timestamp)}</span>
                </div>
                <div className="message-content">{renderMessageContent(message)}</div>
              </div>

              {/* Render subagent sessions that are children of this message */}
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
        <div ref={timelineEndRef} />
      </div>
    </div>
  );
}
