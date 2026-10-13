const configuredApiUrl = import.meta.env.VITE_API_URL?.trim();
const developmentApiUrl = new URL(window.location.origin);
if (import.meta.env.DEV) developmentApiUrl.port = '8000';
const defaultApiUrl = import.meta.env.DEV ? developmentApiUrl.toString() : window.location.origin;
const resolvedApiUrl = new URL(configuredApiUrl || defaultApiUrl, window.location.origin);
if (window.location.protocol === 'https:' && resolvedApiUrl.protocol !== 'https:') {
  throw new Error('VITE_API_URL deve usar HTTPS quando o dashboard é servido por HTTPS.');
}
export const API_BASE_URL = resolvedApiUrl.toString().replace(/\/+$/, '');
export const API_PREFIX = '/api/v1';

const STATUS_MESSAGES = {
  400: 'A solicitação não pôde ser aceita. Revise os dados e tente novamente.',
  401: 'Sua sessão expirou. Entre novamente com o Discord.',
  403: 'Você não tem permissão para realizar esta operação.',
  404: 'O recurso solicitado não foi encontrado ou não está disponível neste servidor.',
  409: 'Os dados foram alterados em paralelo. Atualize a tela e tente novamente.',
  422: 'Alguns valores são inválidos. Revise os campos e tente novamente.',
  429: 'Muitas solicitações. Aguarde um pouco e tente novamente.',
};

let refreshPromise = null;

export class ApiError extends Error {
  constructor(message, status = 0, details = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

export function apiUrl(path) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${API_PREFIX}${normalizedPath}`;
}

function cookieValue(name) {
  if (typeof document === 'undefined') return '';
  const prefix = `${name}=`;
  const entry = document.cookie.split(';').map((value) => value.trim()).find((value) => value.startsWith(prefix));
  if (!entry) return '';
  try {
    return decodeURIComponent(entry.slice(prefix.length));
  } catch {
    return '';
  }
}

function requestHeaders(options) {
  const headers = new Headers(options.headers || {});
  headers.set('Accept', 'application/json');
  const method = (options.method || 'GET').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) {
    const csrfToken = cookieValue('bn_csrf');
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken);
  }
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;
  if (options.body !== undefined && !isFormData) headers.set('Content-Type', 'application/json');
  return headers;
}

async function parsePayload(response) {
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) return null;
  try {
    return await response.json();
  } catch {
    return null;
  }
}

function messageForResponse(statusCode, payload) {
  if (typeof payload?.detail === 'string' && statusCode >= 400 && statusCode < 500) return payload.detail;
  if (statusCode >= 500) return 'A API encontrou um problema inesperado. Tente novamente mais tarde.';
  return STATUS_MESSAGES[statusCode] || 'A solicitação não pôde ser concluída.';
}

async function rawRequest(path, options) {
  const { body, signal, headers: suppliedHeaders, ...fetchOptions } = options;
  const isFormData = typeof FormData !== 'undefined' && body instanceof FormData;
  let response;
  try {
    response = await fetch(apiUrl(path), {
      ...fetchOptions,
      credentials: 'include',
      headers: requestHeaders({ ...options, headers: suppliedHeaders }),
      signal,
      body: body === undefined || isFormData || typeof body === 'string' ? body : JSON.stringify(body),
    });
  } catch (error) {
    if (error?.name === 'AbortError') throw error;
    throw new ApiError('Não foi possível conectar à API. Verifique a rede e tente novamente.', 0);
  }
  return { response, payload: await parsePayload(response) };
}

export function hasCsrfCookie() {
  return Boolean(cookieValue('bn_csrf'));
}

export async function refreshSession() {
  if (!hasCsrfCookie()) {
    return { ok: false, status: 401, payload: { detail: 'Sessão indisponível.' } };
  }
  if (!refreshPromise) {
    refreshPromise = rawRequest('/auth/refresh', { method: 'POST' })
      .then(({ response, payload }) => ({ ok: response.ok, status: response.status, payload }))
      .catch((error) => ({ ok: false, status: error instanceof ApiError ? error.status : 0, error }))
      .finally(() => { refreshPromise = null; });
  }
  return refreshPromise;
}

function isAuthenticationPath(path) {
  return ['/auth/login', '/auth/callback', '/auth/me', '/auth/refresh', '/auth/logout'].includes(path.split('?')[0]);
}

export async function apiRequest(path, options = {}) {
  let { response, payload } = await rawRequest(path, options);
  if (response.status === 401 && !isAuthenticationPath(path)) {
    const refreshResult = await refreshSession();
    if (refreshResult.ok) {
      ({ response, payload } = await rawRequest(path, options));
    } else if (refreshResult.status && refreshResult.status !== 401) {
      throw new ApiError(messageForResponse(refreshResult.status, refreshResult.payload), refreshResult.status, refreshResult.payload);
    } else if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('bn:session-expired'));
    }
  }
  if (!response.ok) {
    if (response.status === 401 && !isAuthenticationPath(path) && typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('bn:session-expired'));
    }
    throw new ApiError(messageForResponse(response.status, payload), response.status, payload);
  }
  return payload;
}

export function getApiErrorMessage(error) {
  if (error instanceof ApiError) return error.message;
  if (error?.name === 'AbortError') return 'A solicitação foi cancelada.';
  return 'Ocorreu um erro inesperado. Tente novamente.';
}
