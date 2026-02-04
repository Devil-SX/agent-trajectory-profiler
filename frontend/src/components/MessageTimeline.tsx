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
} from '../types/session';
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
      const textBlock = block as TextContent;
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
      const toolBlock = block as ToolUseContent;
      return (
        <div key={index} className="tool-use-block">
          <span className="tool-label">🔧 Tool: {toolBlock.name}</span>
        </div>
      );
    }

    if (block.type === 'tool_result') {
      const resultBlock = block as ToolResultContent;
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
    const parts: JSX.Element[] = [];
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

  const renderMessageContent = (message: MessageRecord) => {
    if (!message.message || !message.message.content) {
      return <p className="message-text">(Empty message)</p>;
    }

    const content = message.message.content;

    if (typeof content === 'string') {
      return renderTextWithCodeBlocks(content, 0);
    }

    if (Array.isArray(content)) {
      return content.map((block, index) => renderContentBlock(block, index));
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

  // Filter out non-user and non-assistant messages for the timeline
  const displayMessages = session.messages.filter(
    (msg) => msg.type === 'user' || msg.type === 'assistant'
  );

  return (
    <div className="message-timeline" ref={timelineRef}>
      <div className="timeline-header">
        <h2>Conversation Timeline</h2>
        <p className="message-count">
          {displayMessages.length} message{displayMessages.length !== 1 ? 's' : ''}
        </p>
      </div>
      <div className="messages-container">
        {displayMessages.map((message) => {
          const source = getMessageSource(message);
          return (
            <div key={message.uuid} className={`message-bubble ${source}`}>
              <div className="message-header">
                <span className="message-source">{source}</span>
                <span className="message-timestamp">{formatTimestamp(message.timestamp)}</span>
              </div>
              <div className="message-content">{renderMessageContent(message)}</div>
            </div>
          );
        })}
        <div ref={timelineEndRef} />
      </div>
    </div>
  );
}
