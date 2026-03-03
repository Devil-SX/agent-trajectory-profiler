import { describe, expect, it } from 'vitest';
import { formatTokenCount } from '../../src/utils/tokenFormat';

describe('formatTokenCount', () => {
  it('formats small values without suffix', () => {
    expect(formatTokenCount(0)).toBe('0');
    expect(formatTokenCount(12)).toBe('12');
    expect(formatTokenCount(999)).toBe('999');
  });

  it('formats K/M/B ranges with compact suffixes', () => {
    expect(formatTokenCount(1_000)).toBe('1K');
    expect(formatTokenCount(1_550)).toBe('1.6K');
    expect(formatTokenCount(999_500)).toBe('999.5K');
    expect(formatTokenCount(1_200_000)).toBe('1.2M');
    expect(formatTokenCount(2_500_000_000)).toBe('2.5B');
  });

  it('handles negatives and non-finite values safely', () => {
    expect(formatTokenCount(-1_250)).toBe('-1.3K');
    expect(formatTokenCount(Number.NaN)).toBe('0');
    expect(formatTokenCount(Number.POSITIVE_INFINITY)).toBe('0');
  });
});
