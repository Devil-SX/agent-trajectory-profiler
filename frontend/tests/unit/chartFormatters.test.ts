import { describe, expect, it } from 'vitest';
import {
  createTimeAxisTickFormatter,
  formatTimeAxisTick,
  formatTokenAxisTick,
  formatTokenWithRawValue,
  resolveTimeAxisUnit,
} from '../../src/utils/chartFormatters';

describe('chartFormatters', () => {
  it('formats token axis ticks with compact units and safe fallbacks', () => {
    expect(formatTokenAxisTick(0)).toBe('0');
    expect(formatTokenAxisTick(950)).toBe('950');
    expect(formatTokenAxisTick(1_550)).toBe('1.6K');
    expect(formatTokenAxisTick(-1_250_000)).toBe('-1.3M');
    expect(formatTokenAxisTick(Number.NaN)).toBe('0');
  });

  it('formats token tooltip values with compact + raw semantics', () => {
    expect(formatTokenWithRawValue(1_550)).toBe('1.6K (1,550)');
    expect(formatTokenWithRawValue(12_345, (value) => `raw:${value}`)).toBe('12.3K (raw:12345)');
    expect(formatTokenWithRawValue('bad-value')).toBe('0 (0)');
  });

  it('resolves time axis unit by range thresholds', () => {
    expect(resolveTimeAxisUnit(3_599)).toBe('min');
    expect(resolveTimeAxisUnit(3_600)).toBe('hour');
    expect(resolveTimeAxisUnit(86_399)).toBe('hour');
    expect(resolveTimeAxisUnit(86_400)).toBe('day');
  });

  it('formats time axis ticks for min/hour/day with negative edge support', () => {
    expect(formatTimeAxisTick(180, 'min')).toBe('3 min');
    expect(formatTimeAxisTick(5_400, 'hour')).toBe('1.5 hour');
    expect(formatTimeAxisTick(172_800, 'day')).toBe('2 day');
    expect(formatTimeAxisTick(-3_600, 'hour')).toBe('-1 hour');
  });

  it('creates stable time formatters based on max range', () => {
    const minuteFormatter = createTimeAxisTickFormatter(2_000);
    expect(minuteFormatter(300)).toBe('5 min');

    const hourFormatter = createTimeAxisTickFormatter(7_200);
    expect(hourFormatter(1_800)).toBe('0.5 hour');

    const dayFormatter = createTimeAxisTickFormatter(172_800);
    expect(dayFormatter(43_200)).toBe('0.5 day');
  });
});
