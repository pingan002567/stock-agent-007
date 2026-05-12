import React from "react";

interface PaginationProps {
  total: number;
  pageSize: number;
  current: number;
  onChange: (page: number) => void;
}

export function Pagination({ total, pageSize, current, onChange }: PaginationProps) {
  const totalPages = Math.ceil(total / pageSize);
  
  if (totalPages <= 1) return null;

  const startItem = (current - 1) * pageSize + 1;
  const endItem = Math.min(current * pageSize, total);

  const getVisiblePages = (): (number | "...")[] => {
    const pages: (number | "...")[] = [];
    
    if (totalPages <= 7) {
      for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
      pages.push(1);
      if (current > 3) pages.push("...");
      for (let i = Math.max(2, current - 1); i <= Math.min(totalPages - 1, current + 1); i++) {
        pages.push(i);
      }
      if (current < totalPages - 2) pages.push("...");
      pages.push(totalPages);
    }
    
    return pages;
  };

  return (
    <div className="pagination">
      <div className="pagination-info">
        显示 {startItem}-{endItem} / 共 {total} 条
      </div>
      <div className="pagination-controls">
        <button
          className="pagination-btn"
          onClick={() => onChange(current - 1)}
          disabled={current <= 1}
        >
          &lt;
        </button>
        {getVisiblePages().map((page, i) => (
          page === "..." ? (
            <span key={`ellipsis-${i}`} className="pagination-ellipsis">...</span>
          ) : (
            <button
              key={page}
              className={`pagination-btn ${page === current ? "active" : ""}`}
              onClick={() => onChange(page)}
            >
              {page}
            </button>
          )
        ))}
        <button
          className="pagination-btn"
          onClick={() => onChange(current + 1)}
          disabled={current >= totalPages}
        >
          &gt;
        </button>
      </div>
    </div>
  );
}

interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type { PaginatedResponse };
