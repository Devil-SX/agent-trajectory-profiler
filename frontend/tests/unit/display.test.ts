import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  formatAbsoluteTime,
  formatRelativeWithAbsolute,
  getProjectName,
  getRelativeTime,
  truncateMiddle,
} from '../../src/utils/display';

describe('display utils', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-03T12:00:00Z'));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('extracts readable project name from path', () => {
    expect(getProjectName('/home/sdu/pure_auto/agent_trajectory_profiler')).toBe('agent_trajectory_profiler');
    expect(getProjectName('repo')).toBe('repo');
  });

  it('formats relative time buckets', () => {
    expect(getRelativeTime('2026-03-03T11:59:40Z')).toBe('just now');
    expect(getRelativeTime('2026-03-03T11:10:00Z')).toBe('50 min ago');
    expect(getRelativeTime('2026-03-03T02:00:00Z')).toBe('10h ago');
    expect(getRelativeTime('2026-03-01T12:00:00Z')).toBe('2d ago');
  });

  it('formats absolute + relative composite text', () => {
    const value = formatRelativeWithAbsolute('2026-03-03T11:30:00Z');
    expect(value).toContain('30 min ago');
    expect(value).toContain('(');
    expect(formatAbsoluteTime('2026-03-03T11:30:00Z')).toContain('2026');
  });

  it('truncates long IDs using middle ellipsis', () => {
    expect(truncateMiddle('1234567890abcdef', 4, 4)).toBe('1234…cdef');
    expect(truncateMiddle('short', 4, 4)).toBe('short');
  });
});
