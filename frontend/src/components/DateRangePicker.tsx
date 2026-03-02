/**
 * DateRangePicker component for filtering sessions by date range.
 *
 * Features:
 * - Quick filter buttons (Last 7/30/90 days)
 * - Custom date range inputs (start/end date pickers)
 * - Dropdown panel with "Done" and "Clear" actions
 * - Visual "Filtered" state on toggle button
 */

import { useState, useRef, useEffect, type CSSProperties } from 'react';
import { useI18n } from '../i18n';
import './DateRangePicker.css';

export interface DateRange {
  start_date: string | null;
  end_date: string | null;
}

interface DateRangePickerProps {
  value: DateRange;
  onChange: (range: DateRange) => void;
  onClear: () => void;
}

export function DateRangePicker({ value, onChange, onClear }: DateRangePickerProps) {
  const { t, formatDate } = useI18n();
  const [showPicker, setShowPicker] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState<CSSProperties | undefined>(undefined);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node) &&
        buttonRef.current &&
        !buttonRef.current.contains(event.target as Node)
      ) {
        setShowPicker(false);
      }
    }

    if (showPicker) {
      document.addEventListener('mousedown', handleClickOutside);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
      };
    }
  }, [showPicker]);

  useEffect(() => {
    if (!showPicker) {
      return undefined;
    }

    const updatePosition = () => {
      if (!buttonRef.current || !dropdownRef.current) {
        return;
      }

      const buttonRect = buttonRef.current.getBoundingClientRect();
      const dropdownRect = dropdownRef.current.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const desiredWidth = Math.min(Math.max(dropdownRect.width || 320, 280), viewportWidth - 16);

      let left = buttonRect.left;
      if (left + desiredWidth > viewportWidth - 8) {
        left = viewportWidth - desiredWidth - 8;
      }
      if (left < 8) {
        left = 8;
      }

      let top = buttonRect.bottom + 8;
      let maxHeight = viewportHeight - top - 8;

      if (maxHeight < 220) {
        const desiredHeight = Math.min(dropdownRect.height || 420, viewportHeight - 16);
        top = Math.max(8, buttonRect.top - desiredHeight - 8);
        maxHeight = viewportHeight - top - 8;
      }

      setDropdownStyle({
        top: `${top}px`,
        left: `${left}px`,
        maxWidth: `${viewportWidth - 16}px`,
        maxHeight: `${Math.max(maxHeight, 180)}px`,
      });
    };

    updatePosition();
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.removeEventListener('resize', updatePosition);
      window.removeEventListener('scroll', updatePosition, true);
    };
  }, [showPicker]);

  const handleStartChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...value, start_date: e.target.value || null });
  };

  const handleEndChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...value, end_date: e.target.value || null });
  };

  const handleQuickFilter = (days: number) => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - days);

    onChange({
      start_date: start.toISOString().split('T')[0],
      end_date: end.toISOString().split('T')[0],
    });
    setShowPicker(false);
  };

  const handleClear = () => {
    onClear();
    setShowPicker(false);
  };

  const handleDone = () => {
    setShowPicker(false);
  };

  const isFiltered = value.start_date || value.end_date;

  // Format display text for the button
  const getButtonText = () => {
    if (!isFiltered) {
      return `📅 ${t('dateRange.button')}`;
    }

    const parts = [];
    if (value.start_date) {
      parts.push(`${t('dateRange.from')}: ${formatDate(value.start_date, { year: 'numeric', month: 'short', day: 'numeric' })}`);
    }
    if (value.end_date) {
      parts.push(`${t('dateRange.to')}: ${formatDate(value.end_date, { year: 'numeric', month: 'short', day: 'numeric' })}`);
    }

    if (parts.length === 0) {
      return `📅 ${t('dateRange.button')}`;
    }

    return `📅 ${parts.join(' | ')}`;
  };

  return (
    <div className="date-range-picker">
      <button
        ref={buttonRef}
        className={`date-picker-toggle ${isFiltered ? 'date-picker-toggle--filtered' : ''}`}
        onClick={() => setShowPicker(!showPicker)}
        type="button"
        title={isFiltered ? t('dateRange.modifyTitle') : t('dateRange.filterTitle')}
      >
        {getButtonText()}
      </button>

      {showPicker && (
        <div ref={dropdownRef} className="date-picker-dropdown" style={dropdownStyle}>
          <div className="date-picker-header">
            <h4>{t('dateRange.header')}</h4>
          </div>

          <div className="quick-filters">
            <h5>{t('dateRange.quickFilters')}</h5>
            <div className="quick-filters-buttons">
              <button
                onClick={() => handleQuickFilter(7)}
                type="button"
                className="quick-filter-button"
              >
                {t('dateRange.lastDays', { values: { days: 7 } })}
              </button>
              <button
                onClick={() => handleQuickFilter(30)}
                type="button"
                className="quick-filter-button"
              >
                {t('dateRange.lastDays', { values: { days: 30 } })}
              </button>
              <button
                onClick={() => handleQuickFilter(90)}
                type="button"
                className="quick-filter-button"
              >
                {t('dateRange.lastDays', { values: { days: 90 } })}
              </button>
            </div>
          </div>

          <div className="custom-range">
            <h5>{t('dateRange.customRange')}</h5>
            <div className="date-inputs">
              <label className="date-input-label">
                <span className="date-label-text">{t('dateRange.from')}:</span>
                <input
                  type="date"
                  value={value.start_date || ''}
                  onChange={handleStartChange}
                  className="date-input"
                />
              </label>
              <label className="date-input-label">
                <span className="date-label-text">{t('dateRange.to')}:</span>
                <input
                  type="date"
                  value={value.end_date || ''}
                  onChange={handleEndChange}
                  className="date-input"
                />
              </label>
            </div>
          </div>

          <div className="picker-actions">
            <button
              onClick={handleClear}
              type="button"
              className="picker-action-button picker-action-button--clear"
            >
              {t('dateRange.clear')}
            </button>
            <button
              onClick={handleDone}
              type="button"
              className="picker-action-button picker-action-button--done"
            >
              {t('dateRange.done')}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
