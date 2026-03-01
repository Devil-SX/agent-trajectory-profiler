const K = 1_000;
const M = 1_000_000;
const B = 1_000_000_000;

function trimDecimal(value: number): string {
  return value.toFixed(1).replace(/\.0$/, '');
}

function formatWithUnit(value: number, unit: number, suffix: 'K' | 'M' | 'B'): string {
  const scaled = value / unit;
  const rounded = Number(scaled.toFixed(1));

  // Prevent "1000K" or "1000M" after rounding.
  if (suffix === 'K' && rounded >= 1000) {
    return `${trimDecimal(value / M)}M`;
  }
  if (suffix === 'M' && rounded >= 1000) {
    return `${trimDecimal(value / B)}B`;
  }

  return `${trimDecimal(rounded)}${suffix}`;
}

export function formatTokenCount(value: number): string {
  if (!Number.isFinite(value)) {
    return '0';
  }

  const sign = value < 0 ? '-' : '';
  const absValue = Math.abs(value);

  if (absValue < K) {
    return `${Math.round(value)}`;
  }
  if (absValue < M) {
    return `${sign}${formatWithUnit(absValue, K, 'K')}`;
  }
  if (absValue < B) {
    return `${sign}${formatWithUnit(absValue, M, 'M')}`;
  }
  return `${sign}${formatWithUnit(absValue, B, 'B')}`;
}
