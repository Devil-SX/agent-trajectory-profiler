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

    const VIEWPORT_MARGIN = 8;
    const GAP_TO_TOGGLE = 8;

    const updatePosition = () => {
      if (!buttonRef.current || !dropdownRef.current) {
        return;
      }

      const buttonRect = buttonRef.current.getBoundingClientRect();
      const dropdownRect = dropdownRef.current.getBoundingClientRect();
      const dropdownContentHeight = dropdownRef.current.scrollHeight;
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;
      const maxPanelWidth = Math.max(220, viewportWidth - VIEWPORT_MARGIN * 2);
      const desiredWidth = Math.min(Math.max(dropdownRect.width || 320, 280), maxPanelWidth);
      const maxUsableHeight = Math.max(220, viewportHeight - VIEWPORT_MARGIN * 2);
      const desiredHeight = Math.min(
        Math.max(dropdownContentHeight || dropdownRect.height || 420, 220),
        maxUsableHeight
      );

      let left = buttonRect.left;
      if (left + desiredWidth > viewportWidth - VIEWPORT_MARGIN) {
        left = viewportWidth - desiredWidth - VIEWPORT_MARGIN;
      }
      if (left < VIEWPORT_MARGIN) {
        left = VIEWPORT_MARGIN;
      }

      const spaceBelow = viewportHeight - buttonRect.bottom - VIEWPORT_MARGIN - GAP_TO_TOGGLE;
      const spaceAbove = buttonRect.top - VIEWPORT_MARGIN - GAP_TO_TOGGLE;
      const preferBelow = spaceBelow >= desiredHeight || spaceBelow >= spaceAbove;

      let top = preferBelow
        ? buttonRect.bottom + GAP_TO_TOGGLE
        : buttonRect.top - desiredHeight - GAP_TO_TOGGLE;
      if (top < VIEWPORT_MARGIN) {
        top = VIEWPORT_MARGIN;
      }
      if (top + desiredHeight > viewportHeight - VIEWPORT_MARGIN) {
        top = Math.max(VIEWPORT_MARGIN, viewportHeight - desiredHeight - VIEWPORT_MARGIN);
      }
      const maxHeight = Math.max(220, viewportHeight - top - VIEWPORT_MARGIN);

      setDropdownStyle({
        top: `${top}px`,
        left: `${left}px`,
        maxWidth: `${maxPanelWidth}px`,
        maxHeight: `${Math.min(maxHeight, maxUsableHeight)}px`,
      });
    };

    updatePosition();
    const rafId = window.requestAnimationFrame(updatePosition);
    window.addEventListener('resize', updatePosition);
    window.addEventListener('scroll', updatePosition, true);

    return () => {
      window.cancelAnimationFrame(rafId);
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
