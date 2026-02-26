/**
 * DateRangePicker component for filtering sessions by date range.
 *
 * Features:
 * - Quick filter buttons (Last 7/30/90 days)
 * - Custom date range inputs (start/end date pickers)
 * - Dropdown panel with "Done" and "Clear" actions
 * - Visual "Filtered" state on toggle button
 */

import { useState, useRef, useEffect } from 'react';
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
  const [showPicker, setShowPicker] = useState(false);
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
      return '📅 Date Range';
    }

    const parts = [];
    if (value.start_date) {
      parts.push(`From: ${value.start_date}`);
    }
    if (value.end_date) {
      parts.push(`To: ${value.end_date}`);
    }

    if (parts.length === 0) {
      return '📅 Date Range';
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
        title={isFiltered ? 'Click to modify date filter' : 'Click to filter by date range'}
      >
        {getButtonText()}
      </button>

      {showPicker && (
        <div ref={dropdownRef} className="date-picker-dropdown">
          <div className="date-picker-header">
            <h4>Filter by Date Range</h4>
          </div>

          <div className="quick-filters">
            <h5>Quick Filters</h5>
            <div className="quick-filters-buttons">
              <button
                onClick={() => handleQuickFilter(7)}
                type="button"
                className="quick-filter-button"
              >
                Last 7 days
              </button>
              <button
                onClick={() => handleQuickFilter(30)}
                type="button"
                className="quick-filter-button"
              >
                Last 30 days
              </button>
              <button
                onClick={() => handleQuickFilter(90)}
                type="button"
                className="quick-filter-button"
              >
                Last 90 days
              </button>
            </div>
          </div>

          <div className="custom-range">
            <h5>Custom Range</h5>
            <div className="date-inputs">
              <label className="date-input-label">
                <span className="date-label-text">From:</span>
                <input
                  type="date"
                  value={value.start_date || ''}
                  onChange={handleStartChange}
                  className="date-input"
                />
              </label>
              <label className="date-input-label">
                <span className="date-label-text">To:</span>
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
              Clear
            </button>
            <button
              onClick={handleDone}
              type="button"
              className="picker-action-button picker-action-button--done"
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
