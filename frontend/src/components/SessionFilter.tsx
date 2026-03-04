import './SessionFilter.css';
import { DateRangePicker } from './DateRangePicker';
import { useI18n } from '../i18n';
import {
  DEFAULT_SESSION_FILTERS,
  hasActiveSessionFilter,
  type SessionBrowserFilters,
  type SessionBottleneckFilter,
  type SessionSortOption,
} from '../utils/sessionFilters';

export interface SessionFilterProps {
  value: SessionBrowserFilters;
  onChange: (next: SessionBrowserFilters) => void;
}

function toNumberOrNull(raw: string): number | null {
  const normalized = raw.trim();
  if (!normalized) {
    return null;
  }
  const numeric = Number(normalized);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return numeric;
}

export function SessionFilter({ value, onChange }: SessionFilterProps) {
  const { t } = useI18n();

  const applyPatch = (patch: Partial<SessionBrowserFilters>) => {
    onChange({ ...value, ...patch });
  };

  const bottleneckFilters: Array<{ value: SessionBottleneckFilter; label: string }> = [
    { value: 'all', label: t('filter.all') },
    { value: 'model', label: t('filter.model') },
    { value: 'tool', label: t('filter.tool') },
    { value: 'user', label: t('filter.user') },
  ];

  const activeChips: Array<{ key: string; label: string; clear: () => void }> = [];

  if (value.search_query.trim()) {
    activeChips.push({
      key: 'search',
      label: `${t('filter.searchLabel')}: ${value.search_query.trim()}`,
      clear: () => applyPatch({ search_query: DEFAULT_SESSION_FILTERS.search_query }),
    });
  }
  if (value.start_date || value.end_date) {
    activeChips.push({
      key: 'date',
      label: `${t('filter.dateRange')}: ${value.start_date || '...'} -> ${value.end_date || '...'}`,
      clear: () =>
        applyPatch({
          start_date: DEFAULT_SESSION_FILTERS.start_date,
          end_date: DEFAULT_SESSION_FILTERS.end_date,
        }),
    });
  }
  if (value.bottleneck !== 'all') {
    activeChips.push({
      key: 'bottleneck',
      label: `${t('filter.bottleneck')} ${t(`filter.${value.bottleneck}`)}`,
      clear: () => applyPatch({ bottleneck: DEFAULT_SESSION_FILTERS.bottleneck }),
    });
  }
  if (value.ecosystem !== 'all') {
    activeChips.push({
      key: 'ecosystem',
      label: `${t('filter.ecosystem')}: ${value.ecosystem}`,
      clear: () => applyPatch({ ecosystem: DEFAULT_SESSION_FILTERS.ecosystem }),
    });
  }
  if (value.sort_by !== DEFAULT_SESSION_FILTERS.sort_by) {
    activeChips.push({
      key: 'sort-by',
      label: `${t('filter.sortBy')} ${t(`filter.sort.${value.sort_by}`)}`,
      clear: () => applyPatch({ sort_by: DEFAULT_SESSION_FILTERS.sort_by }),
    });
  }
  if (value.sort_direction !== DEFAULT_SESSION_FILTERS.sort_direction) {
    activeChips.push({
      key: 'sort-direction',
      label: `${t('filter.sortDirection')}: ${t(`filter.sortDirection.${value.sort_direction}`)}`,
      clear: () => applyPatch({ sort_direction: DEFAULT_SESSION_FILTERS.sort_direction }),
    });
  }
  if (value.token_min !== null || value.token_max !== null) {
    activeChips.push({
      key: 'tokens',
      label: `${t('filter.tokenRange')}: ${value.token_min ?? '...'} - ${value.token_max ?? '...'}`,
      clear: () =>
        applyPatch({
          token_min: DEFAULT_SESSION_FILTERS.token_min,
          token_max: DEFAULT_SESSION_FILTERS.token_max,
        }),
    });
  }
  if (value.message_min !== null || value.message_max !== null) {
    activeChips.push({
      key: 'messages',
      label: `${t('filter.messageRange')}: ${value.message_min ?? '...'} - ${value.message_max ?? '...'}`,
      clear: () =>
        applyPatch({
          message_min: DEFAULT_SESSION_FILTERS.message_min,
          message_max: DEFAULT_SESSION_FILTERS.message_max,
        }),
    });
  }
  if (value.automation_band !== 'all') {
    activeChips.push({
      key: 'automation-band',
      label: `${t('filter.automationBand')}: ${t(`filter.automationBand.${value.automation_band}`)}`,
      clear: () => applyPatch({ automation_band: DEFAULT_SESSION_FILTERS.automation_band }),
    });
  }
  if (value.automation_min !== null || value.automation_max !== null) {
    activeChips.push({
      key: 'automation-range',
      label: `${t('filter.automationRange')}: ${value.automation_min ?? '...'} - ${value.automation_max ?? '...'}`,
      clear: () =>
        applyPatch({
          automation_min: DEFAULT_SESSION_FILTERS.automation_min,
          automation_max: DEFAULT_SESSION_FILTERS.automation_max,
        }),
    });
  }

  return (
    <div className="session-filter">
      <div className="filter-row filter-controls">
        <div className="filter-group search-group">
          <label className="filter-label sr-only" htmlFor="session-filter-search">
            {t('filter.searchLabel')}
          </label>
          <input
            id="session-filter-search"
            type="text"
            className="search-input"
            placeholder={t('filter.searchPlaceholder')}
            value={value.search_query}
            onChange={(event) => applyPatch({ search_query: event.target.value })}
          />
        </div>

        <div className="filter-group sort-group">
          <label htmlFor="sort-select" className="sort-label">
            {t('filter.sortBy')}
          </label>
          <select
            id="sort-select"
            className="sort-select"
            value={value.sort_by}
            onChange={(event) => applyPatch({ sort_by: event.target.value as SessionSortOption })}
          >
            <option value="updated">{t('filter.sort.updated')}</option>
            <option value="created">{t('filter.sort.created')}</option>
            <option value="tokens">{t('filter.sort.tokens')}</option>
            <option value="messages">{t('filter.sort.messages')}</option>
            <option value="duration">{t('filter.sort.duration')}</option>
            <option value="automation">{t('filter.sort.automation')}</option>
          </select>
        </div>

        <div className="filter-group sort-direction-group">
          <label htmlFor="sort-direction-select" className="sort-label">
            {t('filter.sortDirection')}
          </label>
          <select
            id="sort-direction-select"
            className="sort-select"
            value={value.sort_direction}
            onChange={(event) =>
              applyPatch({ sort_direction: event.target.value as SessionBrowserFilters['sort_direction'] })
            }
          >
            <option value="desc">{t('filter.sortDirection.desc')}</option>
            <option value="asc">{t('filter.sortDirection.asc')}</option>
          </select>
        </div>

        <div className="filter-group date-range-group">
          <DateRangePicker
            value={{ start_date: value.start_date, end_date: value.end_date }}
            onChange={(range) => applyPatch({ start_date: range.start_date, end_date: range.end_date })}
            onClear={() => applyPatch({ start_date: null, end_date: null })}
          />
        </div>
      </div>

      <div className="filter-row filter-buttons">
        <div className="bottleneck-filter">
          <span className="filter-label">{t('filter.bottleneck')}</span>
          <div className="button-group">
            {bottleneckFilters.map((filter) => (
              <button
                key={filter.value}
                className={`filter-button ${value.bottleneck === filter.value ? 'filter-button--active' : ''} filter-button--${filter.value}`}
                onClick={() => applyPatch({ bottleneck: filter.value })}
                type="button"
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>

        <div className="filter-group ecosystem-group">
          <label htmlFor="ecosystem-select" className="sort-label">
            {t('filter.ecosystem')}
          </label>
          <select
            id="ecosystem-select"
            className="sort-select"
            value={value.ecosystem}
            onChange={(event) =>
              applyPatch({ ecosystem: event.target.value as SessionBrowserFilters['ecosystem'] })
            }
          >
            <option value="all">{t('filter.all')}</option>
            <option value="codex">codex</option>
            <option value="claude_code">claude_code</option>
          </select>
        </div>

        <div className="filter-group clear-group">
          <button
            type="button"
            className="clear-all-button"
            onClick={() => {
              onChange({ ...DEFAULT_SESSION_FILTERS });
            }}
            disabled={!hasActiveSessionFilter(value)}
          >
            {t('filter.clearAll')}
          </button>
        </div>
      </div>

      <div className="filter-row range-row">
        <div className="filter-group range-group">
          <span className="filter-label">{t('filter.tokenRange')}</span>
          <input
            id="token-min-input"
            className="range-input range-input--token-min"
            inputMode="numeric"
            type="number"
            min={0}
            value={value.token_min ?? ''}
            onChange={(event) => applyPatch({ token_min: toNumberOrNull(event.target.value) })}
            placeholder={t('filter.min')}
          />
          <span className="range-separator">-</span>
          <input
            id="token-max-input"
            className="range-input range-input--token-max"
            inputMode="numeric"
            type="number"
            min={0}
            value={value.token_max ?? ''}
            onChange={(event) => applyPatch({ token_max: toNumberOrNull(event.target.value) })}
            placeholder={t('filter.max')}
          />
        </div>

        <div className="filter-group range-group">
          <span className="filter-label">{t('filter.messageRange')}</span>
          <input
            id="message-min-input"
            className="range-input range-input--message-min"
            inputMode="numeric"
            type="number"
            min={0}
            value={value.message_min ?? ''}
            onChange={(event) => applyPatch({ message_min: toNumberOrNull(event.target.value) })}
            placeholder={t('filter.min')}
          />
          <span className="range-separator">-</span>
          <input
            id="message-max-input"
            className="range-input range-input--message-max"
            inputMode="numeric"
            type="number"
            min={0}
            value={value.message_max ?? ''}
            onChange={(event) => applyPatch({ message_max: toNumberOrNull(event.target.value) })}
            placeholder={t('filter.max')}
          />
        </div>

        <div className="filter-group range-group automation-group">
          <label htmlFor="automation-band-select" className="filter-label">
            {t('filter.automationBand')}
          </label>
          <select
            id="automation-band-select"
            className="sort-select"
            value={value.automation_band}
            onChange={(event) =>
              applyPatch({
                automation_band: event.target.value as SessionBrowserFilters['automation_band'],
              })
            }
          >
            <option value="all">{t('filter.automationBand.all')}</option>
            <option value="low">{t('filter.automationBand.low')}</option>
            <option value="medium">{t('filter.automationBand.medium')}</option>
            <option value="high">{t('filter.automationBand.high')}</option>
          </select>
          <span className="filter-label automation-range-label">{t('filter.automationRange')}</span>
          <input
            id="automation-min-input"
            className="range-input range-input--automation-min"
            inputMode="decimal"
            type="number"
            min={0}
            step="0.1"
            value={value.automation_min ?? ''}
            onChange={(event) => applyPatch({ automation_min: toNumberOrNull(event.target.value) })}
            placeholder={t('filter.min')}
          />
          <span className="range-separator">-</span>
          <input
            id="automation-max-input"
            className="range-input range-input--automation-max"
            inputMode="decimal"
            type="number"
            min={0}
            step="0.1"
            value={value.automation_max ?? ''}
            onChange={(event) => applyPatch({ automation_max: toNumberOrNull(event.target.value) })}
            placeholder={t('filter.max')}
          />
        </div>
      </div>

      <div className="filter-row chips-row" aria-live="polite">
        {activeChips.length === 0 && (
          <span className="filter-chip filter-chip--placeholder">{t('filter.noneActive')}</span>
        )}
        {activeChips.map((chip) => (
          <button
            key={chip.key}
            type="button"
            className="filter-chip"
            onClick={chip.clear}
            title={t('filter.removeChip')}
          >
            {chip.label} <span aria-hidden="true">x</span>
          </button>
        ))}
      </div>
    </div>
  );
}
