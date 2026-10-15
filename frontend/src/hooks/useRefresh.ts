import { useState, useCallback } from "react";

/**
 * 通用刷新状态管理 Hook
 * 提供刷新状态和带刷新效果的异步执行函数
 */
export function useRefresh() {
  const [refreshing, setRefreshing] = useState(false);

  const withRefresh = useCallback(async <T>(fn: () => Promise<T>): Promise<T> => {
    setRefreshing(true);
    try {
      return await fn();
    } finally {
      setRefreshing(false);
    }
  }, []);

  return { refreshing, withRefresh };
}
