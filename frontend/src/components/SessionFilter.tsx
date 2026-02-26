/**
 * SessionFilter component for filtering and sorting sessions.
 *
 * Features:
 * - Debounced search by project path or session ID
 * - Sort dropdown with 5 options (Updated, Created, Tokens, Duration, Automation)
 * - Bottleneck filter buttons (All, Model, Tool, User)
 * - Responsive layout (desktop/mobile)
 * - Controlled component with callbacks
 */

import { useEffect, useState } from 'react';
import './SessionFilter.css';
import { DateRangePicker, type DateRange } from './DateRangePicker';

export type SortOption = 'updated' | 'created' | 'tokens' | 'duration' | 'automation';
export type BottleneckFilter = 'all' | 'model' | 'tool' | 'user';

export interface SessionFilterProps {
  onSearchChange: (query: string) => void;
  onSortChange: (sortBy: SortOption) => void;
  onBottleneckFilterChange: (filter: BottleneckFilter) => void;
  onDateRangeChange: (range: DateRange) => void;
  searchQuery?: string;
  sortBy?: SortOption;
  bottleneckFilter?: BottleneckFilter;
  dateRange?: DateRange;
}

export function SessionFilter({
  onSearchChange,
  onSortChange,
  onBottleneckFilterChange,
  onDateRangeChange,
  searchQuery = '',
  sortBy = 'updated',
  bottleneckFilter = 'all',
  dateRange = { start_date: null, end_date: null },
}: SessionFilterProps) {
  const [searchInput, setSearchInput] = useState(searchQuery);

  // Debounced search with 300ms delay
  useEffect(() => {
    const timer = setTimeout(() => {
      onSearchChange(searchInput);
    }, 300);

    return () => clearTimeout(timer);
  }, [searchInput, onSearchChange]);

  const handleSearchChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setSearchInput(event.target.value);
  };

  const handleSortChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    onSortChange(event.target.value as SortOption);
  };

  const handleBottleneckFilterChange = (filter: BottleneckFilter) => {
    onBottleneckFilterChange(filter);
  };

  const bottleneckFilters: Array<{ value: BottleneckFilter; label: string }> = [
    { value: 'all', label: 'All' },
    { value: 'model', label: 'Model' },
    { value: 'tool', label: 'Tool' },
    { value: 'user', label: 'User' },
  ];

  return (
    <div className="session-filter">
      {/* Search and Sort Row */}
      <div className="filter-row filter-controls">
        <div className="filter-group search-group">
          <input
            type="text"
            className="search-input"
            placeholder="Search by project path or session ID..."
            value={searchInput}
            onChange={handleSearchChange}
          />
        </div>

        <div className="filter-group sort-group">
          <label htmlFor="sort-select" className="sort-label">
            Sort by:
          </label>
          <select id="sort-select" className="sort-select" value={sortBy} onChange={handleSortChange}>
            <option value="updated">Updated (newest first)</option>
            <option value="created">Created (newest first)</option>
            <option value="tokens">Token usage (highest first)</option>
            <option value="duration">Duration (longest first)</option>
            <option value="automation">Automation ratio (highest first)</option>
          </select>
        </div>

        <div className="filter-group date-range-group">
          <DateRangePicker
            value={dateRange}
            onChange={onDateRangeChange}
            onClear={() => onDateRangeChange({ start_date: null, end_date: null })}
          />
        </div>
      </div>

      {/* Bottleneck Filter Buttons Row */}
      <div className="filter-row filter-buttons">
        <div className="bottleneck-filter">
          <span className="filter-label">Bottleneck:</span>
          <div className="button-group">
            {bottleneckFilters.map((filter) => (
              <button
                key={filter.value}
                className={`filter-button ${bottleneckFilter === filter.value ? 'filter-button--active' : ''} filter-button--${filter.value}`}
                onClick={() => handleBottleneckFilterChange(filter.value)}
                type="button"
              >
                {filter.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
