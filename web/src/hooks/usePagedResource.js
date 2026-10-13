import { useEffect, useState } from 'react';
import { apiRequest, getApiErrorMessage } from '../api/client';

export function usePagedResource(path, page = 1, pageSize = 25) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    Promise.resolve()
      .then(() => {
        if (controller.signal.aborted) return null;
        setLoading(true);
        setError(null);
        return apiRequest(`${path}?page=${page}&page_size=${pageSize}`, { signal: controller.signal });
      })
      .then((payload) => {
        if (!controller.signal.aborted && payload !== null) setData(payload);
      })
      .catch((failure) => {
        if (!controller.signal.aborted) setError(getApiErrorMessage(failure));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, page, pageSize, retryCount]);

  return {
    data,
    loading,
    error,
    retry: () => setRetryCount((current) => current + 1),
  };
}
