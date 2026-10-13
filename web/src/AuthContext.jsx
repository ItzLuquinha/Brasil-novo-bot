import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiRequest, apiUrl, getApiErrorMessage, ApiError, hasCsrfCookie, refreshSession } from './api/client';
import { AuthContext } from './auth/context';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => {
    const expireSession = () => {
      setUser(null);
      setAuthError('Sua sessão expirou. Entre novamente com o Discord.');
      setLoading(false);
    };
    window.addEventListener('bn:session-expired', expireSession);
    return () => window.removeEventListener('bn:session-expired', expireSession);
  }, []);

  useEffect(() => {
    localStorage.removeItem('bn_token');
    const currentUrl = new URL(window.location.href);
    let changed = false;
    if (currentUrl.searchParams.has('token')) {
      currentUrl.searchParams.delete('token');
      changed = true;
    }
    if (new URLSearchParams(currentUrl.hash.slice(1)).has('token')) {
      currentUrl.hash = '';
      changed = true;
    }
    if (changed) window.history.replaceState({}, document.title, `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`);
  }, []);

  useEffect(() => {
    const controller = new AbortController();

    const authenticate = async () => {
      setLoading(true);
      setAuthError(null);
      try {
        let data;
        try {
          data = await apiRequest('/auth/me', { signal: controller.signal });
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 401) throw error;
          if (!hasCsrfCookie()) {
            if (!controller.signal.aborted) setUser(null);
            return;
          }
          const refreshResult = await refreshSession();
          if (refreshResult.ok) {
            data = await apiRequest('/auth/me', { signal: controller.signal });
          } else if (refreshResult.status === 409) {



            let recovered = false;
            for (let attempt = 0; attempt < 4 && !controller.signal.aborted; attempt += 1) {
              await new Promise((resolve) => window.setTimeout(resolve, 100));
              try {
                data = await apiRequest('/auth/me', { signal: controller.signal });
                recovered = true;
                break;
              } catch (retryError) {
                if (!(retryError instanceof ApiError) || retryError.status !== 401) throw retryError;
              }
            }
            if (!recovered) {
              throw new ApiError(
                'A sessão está sendo renovada em outra solicitação. Tente novamente.',
                409,
                refreshResult.payload,
              );
            }
          } else if (refreshResult.status === 401) {
            setUser(null);
            setAuthError(null);
            return;
          } else {
            throw new ApiError(
              getApiErrorMessage(refreshResult.error || new ApiError(
                refreshResult.payload?.detail || 'Não foi possível renovar a sessão.',
                refreshResult.status,
                refreshResult.payload,
              )),
              refreshResult.status,
              refreshResult.payload,
            );
          }
        }
        if (!controller.signal.aborted) setUser(data);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          setUser(null);
          setAuthError(null);
        } else {
          setUser(null);
          setAuthError(getApiErrorMessage(error));
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    };

    authenticate();
    return () => controller.abort();
  }, [retryCount]);

  const login = useCallback(() => {
    window.location.assign(apiUrl('/auth/login'));
  }, []);

  const logout = useCallback(async () => {
    setUser(null);
    setAuthError(null);
    try {
      await apiRequest('/auth/logout', { method: 'POST' });
    } catch (error) {
      setAuthError(`Não foi possível confirmar o encerramento da sessão no servidor. ${getApiErrorMessage(error)}`);
    }
  }, []);

  const retryAuthentication = useCallback(() => setRetryCount((current) => current + 1), []);
  const value = useMemo(() => ({
    user,
    isAuthenticated: Boolean(user),
    loading,
    authError,
    login,
    logout,
    retryAuthentication,
  }), [user, loading, authError, login, logout, retryAuthentication]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
