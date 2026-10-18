import { ReactNode } from 'react';
import { ChevronLeft, ChevronRight, ChevronDown } from 'lucide-react';
import './DashboardPagination.css';

export interface DashboardPaginationProps {
  totalItems: number;
  currentPage: number;
  itemsPerPage: number;
  onPageChange: (page: number) => void;
  onItemsPerPageChange: (perPage: number) => void;
  itemLabel?: string;
  /** Optional: content to show after "Showing X–Y of Z" (e.g. selected-count badge) */
  leftExtra?: ReactNode;
}

export function DashboardPagination({
  totalItems,
  currentPage,
  itemsPerPage,
  onPageChange,
  onItemsPerPageChange,
  itemLabel = 'items',
  leftExtra,
}: DashboardPaginationProps) {
  const totalPages = Math.ceil(totalItems / itemsPerPage) || 1;
  const startIndex = totalItems === 0 ? 0 : (currentPage - 1) * itemsPerPage + 1;
  const endIndex = Math.min(currentPage * itemsPerPage, totalItems);

  const pageSizeOptions = [10, 100, 200, 300, 400, 500];
  const options = pageSizeOptions.includes(itemsPerPage)
    ? pageSizeOptions
    : [...pageSizeOptions, itemsPerPage].sort((a, b) => a - b).filter((n) => n >= 10 && n <= 500);

  return (
    <div className="dashboard-pagination">
      <div className="dashboard-pagination-left">
        <span className="dashboard-pagination-showing">
          Showing {totalItems === 0 ? '0-0' : `${startIndex}-${endIndex}`} of {totalItems} {itemLabel}
        </span>
        {leftExtra}
      </div>
      <div className="dashboard-pagination-controls">
        <button
          type="button"
          className="dashboard-pagination-btn"
          onClick={() => currentPage > 1 && onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft size={16} strokeWidth={2} />
        </button>
        <span className="dashboard-pagination-page">Page {currentPage} of {totalPages}</span>
        <button
          type="button"
          className="dashboard-pagination-btn"
          onClick={() => currentPage < totalPages && onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          aria-label="Next page"
        >
          <ChevronRight size={16} strokeWidth={2} />
        </button>
        <span className="dashboard-pagination-show-label">Show</span>
        <div className="dashboard-pagination-select-wrapper">
          <select
            value={itemsPerPage}
            onChange={(e) => {
              onItemsPerPageChange(Number(e.target.value));
              onPageChange(1);
            }}
            className="dashboard-pagination-select"
          >
            {options.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <ChevronDown size={14} strokeWidth={2} className="dashboard-pagination-select-icon" />
        </div>
      </div>
    </div>
  );
}
