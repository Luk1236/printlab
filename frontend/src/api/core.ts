/**
 * Anfragen, Anmeldung und Fehler der API.
 *
 * Der Kern, den alle Endpunktgruppen benutzen: Basis-URL, Token, ``request``.
 */

import i18n from '../i18n';

export const API_BASE = '/api/v1';

export class ApiError extends Error {
  status: number;
  /** Stable error code from a structured backend detail (`{code, message}`).
   *  Frontend uses this to look up an i18n key instead of showing the raw
   *  English fallback. Null when the backend returned a plain-string detail. */
  code: string | null;
  /** Full structured detail object when the backend returned `{code, ...}`
   *  with additional fields (e.g. the deficit list for 409s on queue
   *  start, #1496). Null for plain-string or array-shaped details. */
  detail: Record<string, unknown> | null;
  constructor(
    message: string,
    status: number,
    code: string | null = null,
    detail: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

// Auth token storage
// By default tokens are stored in sessionStorage (tab-scoped, cleared on close).
// When the token originates from the ?token= URL param (kiosk bootstrap), it is
// additionally persisted in localStorage so the kiosk survives page reloads.
// 'persistent' also writes to localStorage so the token survives tab close
// (used by Remember Me and the ?token= kiosk bootstrap).
export let authToken: string | null =
  sessionStorage.getItem('auth_token') ?? localStorage.getItem('auth_token');

export type TokenPersistence = 'session' | 'persistent';

export function setAuthToken(token: string | null, persistence: TokenPersistence = 'session') {
  authToken = token;
  try {
    if (token) {
      sessionStorage.setItem('auth_token', token);
    } else {
      sessionStorage.removeItem('auth_token');
    }
  } catch (err) {
    // Storage unavailable (quota exceeded, private mode): in-memory token still works for this tab.
    console.warn('setAuthToken: sessionStorage unavailable, token kept in-memory only', err);
  }
  try {
    if (!token) {
      localStorage.removeItem('auth_token');
    } else if (persistence === 'persistent') {
      localStorage.setItem('auth_token', token);
    }
  } catch (err) {
    console.warn('setAuthToken: localStorage operation failed', err);
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

// Query-param tokens for <img>/<video> src URLs, which can't carry an
// Authorization header. There are two, and which one a URL takes is decided
// by what the URL points at, not by convenience:
//
//   streamToken — live camera only. Minting one costs camera:view.
//   mediaToken  — thumbnails, previews, timelapses, covers, icons. Minted by
//                 any signed-in user and carries their identity, so those
//                 routes can apply the same ownership rules as everywhere else.
//
// Before #3025 the stream token served both, which meant a user could not see
// a library thumbnail without also being granted the live feed of the room the
// printer sits in — and, because a stream token names nobody, those routes had
// no identity to scope by and served any row to any holder.
export let streamToken: string | null = null;
export let mediaToken: string | null = null;

export function setStreamToken(token: string | null) {
  streamToken = token;
}

export function getStreamToken(): string | null {
  return streamToken;
}

export function setMediaToken(token: string | null) {
  mediaToken = token;
}

export function getMediaToken(): string | null {
  return mediaToken;
}

/** Append the camera stream token to a URL if available (live camera only). */
export function withStreamToken(url: string): string {
  if (!streamToken) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}token=${encodeURIComponent(streamToken)}`;
}

/** Append the media token to a URL if available (for <img>/<video> src). */
export function withMediaToken(url: string): string {
  if (!mediaToken) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}token=${encodeURIComponent(mediaToken)}`;
}

export function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) return null;
  // RFC 5987: filename*=utf-8''percent-encoded-name
  const rfc5987Match = header.match(/filename\*=(?:UTF-8|utf-8)''(.+?)(?:;|$)/);
  if (rfc5987Match) {
    try { return decodeURIComponent(rfc5987Match[1]); } catch { /* fall through */ }
  }
  // Standard: filename="name" or filename=name
  const standardMatch = header.match(/filename="?([^";\n]+)"?/);
  return standardMatch?.[1] || null;
}

export function buildSlicerUrlFilename(filename: string): string {
  const safe = filename.replace(/[/\\?#]/g, '_');
  return safe.toLowerCase().endsWith('.3mf') ? safe : `${safe}.3mf`;
}

/** POST JSON and return the response body as a Blob (label PDFs and images). */
export async function postForBlob(endpoint: string, data: unknown, signal?: AbortSignal): Promise<Blob> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
  }
  return response.blob();
}

export async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options.headers as Record<string, string>,
  };

  // Add auth token if available
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  // Sprache der Oberfläche: die PrintLab-Erweiterungen übersetzen ihre Meldungen danach (Deutsch/Englisch).
  if (!headers['Accept-Language']) {
    headers['Accept-Language'] = i18n.language || 'de';
  }

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    cache: 'no-store', // Prevent browser caching of API responses
    credentials: 'include', // Required for HttpOnly cookies (e.g. 2fa_challenge)
    headers,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const detail = error.detail;
    let message: string;
    let code: string | null = null;
    if (typeof detail === 'string') {
      message = detail;
    } else if (Array.isArray(detail)) {
      // FastAPI 422 shape: each entry has `msg` like "Value error, <real msg>".
      // Strip the prefix and join. Fall back to raw JSON if every entry has an
      // empty msg (defensive — shouldn't happen with stock Pydantic, but the
      // previous fallback masked the real cause as a bare "HTTP 422" toast).
      const joined = detail
        .map((e: { msg?: string }) => (e.msg ?? '').replace(/^Value error,\s*/i, ''))
        .filter(Boolean)
        .join('; ');
      message = joined || JSON.stringify(detail) || `HTTP ${response.status}`;
    } else if (detail && typeof detail === 'object') {
      // Structured detail `{code, message, ...}` — frontend uses the code
      // to pick an i18n key, message is the English fallback, any extra
      // fields land on ApiError.detail (e.g. `deficit` for #1496).
      code = typeof detail.code === 'string' ? detail.code : null;
      message = typeof detail.message === 'string' ? detail.message : `HTTP ${response.status}`;
    } else {
      message = `HTTP ${response.status}`;
    }
    const structuredDetail = detail && typeof detail === 'object' && !Array.isArray(detail)
      ? (detail as Record<string, unknown>)
      : null;

    // Handle 401 Unauthorized - only clear token if it's actually invalid
    // Don't clear on "Authentication required" which might be a timing issue
    if (response.status === 401) {
      const invalidTokenMessages = [
        'Could not validate credentials',
        'Token has expired',
        'User not found or inactive',
        'Invalid API key',
        'API key has expired',
      ];
      if (invalidTokenMessages.some(m => message.includes(m))) {
        setAuthToken(null);
        // Notify AuthContext so the protected route guard re-evaluates and
        // redirects to /login on the same tab — without this, AuthContext.user
        // stays cached and the tab silently fails every request until a manual
        // refresh remounts AuthProvider (#1698, reported by @TCL987).
        if (typeof window !== 'undefined') {
          window.dispatchEvent(new CustomEvent('auth:expired'));
        }
      }
    }

    throw new ApiError(message, response.status, code, structuredDetail);
  }

  // Handle empty responses (204 No Content, etc.)
  const contentLength = response.headers.get('content-length');
  if (response.status === 204 || contentLength === '0') {
    return undefined as T;
  }

  return await response.json();
}

/** Upload a CSV to the spool import endpoint (#1576). Multipart, so it bypasses
 *  `request<T>()` (which sends JSON): the browser must set the form-data
 *  boundary itself. `dryRun` toggles preview-only vs. real import. */
export async function uploadSpoolsCsv<T>(file: File, dryRun: boolean): Promise<T> {
  const form = new FormData();
  form.append('file', file);
  const headers: Record<string, string> = {};
  if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
  const response = await fetch(`${API_BASE}/inventory/spools/import${dryRun ? '?dry_run=true' : ''}`, {
    method: 'POST',
    headers,
    body: form,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    // detail may be a plain string or a structured {code, message} object
    // (e.g. the 413 too-large response). Surface the human message either way.
    const detail = error?.detail;
    const message = typeof detail === 'string' ? detail : detail?.message;
    throw new Error(message || `HTTP ${response.status}`);
  }
  return response.json();
}

// Camera diagnostic result (#1395 follow-up). Returned by
// POST /printers/{id}/camera/diagnose; the frontend modal renders one
// row per stage and looks up the summary code in i18n for the user-
// facing remediation hint.
