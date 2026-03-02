import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { I18nContext, type I18nContextValue, type Locale, type TranslateOptions } from './context';
import { messages, type TranslationDictionary } from './messages';
import { formatTokenCount as formatTokenCountCompact } from '../utils/tokenFormat';

function getInitialLocale(): Locale {
  return 'en';
}

function interpolate(template: string, values?: Record<string, string | number>): string {
  if (!values) {
    return template;
  }

  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (_match, key: string) => {
    const next = values[key];
    return next === undefined ? '' : String(next);
  });
}

function resolveMessage(locale: Locale, key: string, dict: TranslationDictionary): string {
  if (dict[key]) {
    return dict[key];
  }
  if (locale !== 'en' && messages.en[key]) {
    return messages.en[key];
  }
  return key;
}

function getRelativeTimeToken(diffMs: number): {
  key: 'time.justNow' | 'time.minutesAgo' | 'time.hoursAgo' | 'time.daysAgo';
  count: number;
} {
  if (diffMs < 60_000) {
    return { key: 'time.justNow', count: 0 };
  }

  const minutes = Math.floor(diffMs / 60_000);
  if (minutes < 60) {
    return { key: 'time.minutesAgo', count: minutes };
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return { key: 'time.hoursAgo', count: hours };
  }

  const days = Math.floor(hours / 24);
  return { key: 'time.daysAgo', count: days };
}

interface I18nProviderProps {
  children: ReactNode;
}

export function I18nProvider({ children }: I18nProviderProps) {
  const [locale, setLocale] = useState<Locale>(getInitialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const value = useMemo<I18nContextValue>(() => {
    const dict = messages[locale];

    const t = (key: string, options?: TranslateOptions): string => {
      const template = resolveMessage(locale, key, dict);
      return interpolate(template, options?.values);
    };

    const formatNumber = (num: number, options?: Intl.NumberFormatOptions): string => {
      return new Intl.NumberFormat(locale, options).format(num);
    };

    const formatTokenCount = (num: number): string => {
      return formatTokenCountCompact(num);
    };

    const formatPercent = (value: number, fractionDigits: number = 1): string => {
      return new Intl.NumberFormat(locale, {
        style: 'percent',
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }).format(value);
    };

    const formatDate = (value: string | Date, options?: Intl.DateTimeFormatOptions): string => {
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      return date.toLocaleDateString(locale, options);
    };

    const formatDateTime = (
      value: string | Date,
      options?: Intl.DateTimeFormatOptions,
    ): string => {
      const date = value instanceof Date ? value : new Date(value);
      if (Number.isNaN(date.getTime())) {
        return String(value);
      }
      return date.toLocaleString(locale, options);
    };

    const formatRelativeWithAbsolute = (timestamp: string): string => {
      const now = new Date();
      const past = new Date(timestamp);
      if (Number.isNaN(past.getTime())) {
        return timestamp;
      }

      const { key, count } = getRelativeTimeToken(now.getTime() - past.getTime());
      const relative = key === 'time.justNow' ? t(key) : t(key, { values: { count } });
      const absolute = formatDateTime(past, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
      return `${relative} (${absolute})`;
    };

    return {
      locale,
      setLocale,
      t,
      formatNumber,
      formatTokenCount,
      formatPercent,
      formatDate,
      formatDateTime,
      formatRelativeWithAbsolute,
    };
  }, [locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}
