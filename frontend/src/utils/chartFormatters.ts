import { formatTokenCount } from './tokenFormat';

const MINUTE_SECONDS = 60;
const HOUR_SECONDS = 60 * MINUTE_SECONDS;
const DAY_SECONDS = 24 * HOUR_SECONDS;

export type TimeAxisUnit = 'min' | 'hour' | 'day';

function toFiniteNumber(value: number | string | null | undefined): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
}

function trimTrailingZeros(value: number): string {
  return value.toFixed(2).replace(/\.?0+$/, '');
}

function formatScaledUnit(value: number, unitSeconds: number, unitLabel: TimeAxisUnit): string {
  const sign = value < 0 ? '-' : '';
  const scaled = Math.abs(value) / unitSeconds;
  const precision = scaled >= 100 ? 0 : scaled >= 10 ? 1 : scaled >= 1 ? 1 : 2;
  const rounded = Number(scaled.toFixed(precision));
  return `${sign}${trimTrailingZeros(rounded)} ${unitLabel}`;
}

export function formatTokenAxisTick(value: number | string | null | undefined): string {
  return formatTokenCount(toFiniteNumber(value));
}

export function formatTokenWithRawValue(
  value: number | string | null | undefined,
  formatNumber: (value: number) => string = (num) => num.toLocaleString()
): string {
  const numeric = toFiniteNumber(value);
  return `${formatTokenCount(numeric)} (${formatNumber(numeric)})`;
}

export function resolveTimeAxisUnit(maxAbsSeconds: number | string | null | undefined): TimeAxisUnit {
  const abs = Math.abs(toFiniteNumber(maxAbsSeconds));
  if (abs >= DAY_SECONDS) {
    return 'day';
  }
  if (abs >= HOUR_SECONDS) {
    return 'hour';
  }
  return 'min';
}

export function formatTimeAxisTick(
  value: number | string | null | undefined,
  unit: TimeAxisUnit
): string {
  const numeric = toFiniteNumber(value);
  if (unit === 'day') {
    return formatScaledUnit(numeric, DAY_SECONDS, 'day');
  }
  if (unit === 'hour') {
    return formatScaledUnit(numeric, HOUR_SECONDS, 'hour');
  }
  return formatScaledUnit(numeric, MINUTE_SECONDS, 'min');
}

export function createTimeAxisTickFormatter(
  maxAbsSeconds: number | string | null | undefined
): (value: number | string | null | undefined) => string {
  const axisUnit = resolveTimeAxisUnit(maxAbsSeconds);
  return (value) => formatTimeAxisTick(value, axisUnit);
}
