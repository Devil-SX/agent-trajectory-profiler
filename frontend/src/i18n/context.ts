import { createContext } from 'react';

export type Locale = 'en' | 'zh-CN';

export interface TranslateOptions {
  values?: Record<string, string | number>;
}

export interface I18nContextValue {
  locale: Locale;
  setLocale: (next: Locale) => void;
  t: (key: string, options?: TranslateOptions) => string;
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) => string;
  formatPercent: (value: number, fractionDigits?: number) => string;
  formatDate: (value: string | Date, options?: Intl.DateTimeFormatOptions) => string;
  formatDateTime: (value: string | Date, options?: Intl.DateTimeFormatOptions) => string;
  formatRelativeWithAbsolute: (timestamp: string) => string;
}

export const I18nContext = createContext<I18nContextValue | null>(null);
