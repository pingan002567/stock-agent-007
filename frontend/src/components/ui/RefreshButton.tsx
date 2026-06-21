import React from "react";

interface RefreshButtonProps {
  refreshing: boolean;
  onClick: () => void;
  className?: string;
}

/**
 * 统一的刷新按钮组件
 * 带有旋转动画和脉冲效果
 */
export function RefreshButton({ refreshing, onClick, className = "" }: RefreshButtonProps) {
  return (
    <button 
      className={`refresh-btn ${refreshing ? 'refreshing' : ''} ${className}`} 
      onClick={onClick} 
      disabled={refreshing} 
      type="button"
    >
      <svg className="refresh-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
        <polyline points="21 3 21 12 12 12"/>
      </svg>
      {refreshing ? '刷新中...' : '刷新数据'}
    </button>
  );
}

/**
 * 刷新容器组件 - 给子元素添加刷新效果
 */
export function RefreshContainer({ refreshing, children, className = "" }: { 
  refreshing: boolean; 
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`${refreshing ? 'refreshing-module' : ''} ${className}`}>
      {children}
    </div>
  );
}
