/**
 * API-Funktionen der PrintLab-Erweiterungen (Fernzugriff, Angebote, Zustand des Geräts, Meldewege, Sicherungen,
 * Kamera-Einmessung, Checkliste). Aus `client.ts` ausgelagert, damit diese Datei nicht weiter wächst
 * (siehe backend/tests/unit/test_file_size_budget.py). `client.ts` reicht die Hilfen von dort herein und bindet das
 * Ergebnis in `api` ein; die Typen werden von dort weiter ausgegeben.
 */

export interface RemoteAccessStatus {
  supported: boolean;
  installed: boolean;
  managed: boolean;
  daemon_running: boolean;
  state: 'off' | 'stopped' | 'login' | 'connected';
  login_url: string | null;
  ips: string[];
  dns_name: string;
  serving: boolean;
  enabled: boolean;
  slicer: boolean;
  https: boolean;
  https_url: string;
  error: string | null;
  auth_enabled: boolean;
}

export interface CompanyProfile {
  name: string;
  address: string;
  tax_id: string;
  email: string;
  phone: string;
  iban: string;
  bic: string;
  footer: string;
  vat_percent: number;
  vat_note: string;
  valid_days: number;
  number_prefix: string;
  number_format: string;
  invoice_prefix: string;
  invoice_format: string;
  payment_days: number;
  has_logo: boolean;
}

export interface PiHealthWarning {
  level: 'warn' | 'crit';
  code: string;
  text: string;
  params: Record<string, number>;
}

export interface PiHealth {
  cpu_temp_c: number | null;
  throttled: { value: number; flags: string[] } | null;
  disk: { total: number; free: number } | null;
  storage: { device: string; kind: 'sd' | 'usb' | 'nvme' | 'other' } | null;
  memory: { total: number; available: number; swap_total: number; swap_free: number } | null;
  uptime_seconds: number | null;
  backup: { path: string; age_days: number } | null;
  external_backup: { ok: boolean; detail: string; at: string } | null;
  warnings: PiHealthWarning[];
}

export interface AlertChannelsStatus {
  telegram: boolean;
  telegram_chat: string;
  ntfy: boolean;
  ntfy_host: string;
}

export interface SetupStatus {
  items: { id: string; level: 'required' | 'recommended' | 'optional'; done: boolean | null }[];
  done: number;
  total: number;
  required_open: number;
}

export interface UpdateBackup {
  name: string;
  created: string;
  files: string[];
  size_bytes: number;
}

export interface UpdateBackups {
  backups: UpdateBackup[];
  restore_pending: string | null;
  restored: { name: string; restored: string[]; at: string } | null;
  can_restore: boolean;
}

export interface PlateTuningAnalysis {
  empty: { name: string; score: number }[];
  occupied: { name: string; score: number }[];
  suggestion: {
    threshold: number;
    min_confidence: number;
    separable: boolean;
    quality: 'good' | 'ok' | 'weak' | 'overlap';
    missed_objects: number;
    false_alarms: number;
    empty_max: number;
    occupied_min: number;
    message: string;
  };
}

export interface Invoice {
  id: string;
  number: string;
  status: 'open' | 'paid' | 'cancelled';
  quote_id: string;
  quote_number: string;
  issued: string;
  service_date: string;
  due: string;
  paid_at: string | null;
  customer: string;
  customer_address: string;
  description: string;
  currency: string;
  total: number;
}

export interface InvoicesResponse {
  invoices: Invoice[];
  totals: Record<string, { open: number; overdue: number; paid: number }>;
  overdue_ids: string[];
}

export interface ForkApiDeps {
  request: <T>(endpoint: string, options?: RequestInit) => Promise<T>;
  apiBase: string;
  getAuthToken: () => string | null;
}

export function createForkApi({ request, apiBase, getAuthToken }: ForkApiDeps) {
  return {
    getInvoices: () => request<InvoicesResponse>('/quote/invoices'),
    createInvoice: (quoteId: string, serviceDate?: string) =>
      request<Invoice>(`/quote/history/${encodeURIComponent(quoteId)}/invoice`, {
        method: 'POST',
        body: JSON.stringify(serviceDate ? { service_date: serviceDate } : {}),
      }),
    markInvoicePaid: (id: string, paidAt?: string) =>
      request<Invoice>(`/quote/invoices/${encodeURIComponent(id)}/paid`, {
        method: 'POST',
        body: JSON.stringify(paidAt ? { paid_at: paidAt } : {}),
      }),
    reopenInvoice: (id: string) => request<Invoice>(`/quote/invoices/${encodeURIComponent(id)}/reopen`, { method: 'POST' }),
    cancelInvoice: (id: string, reason = '') =>
      request<Invoice>(`/quote/invoices/${encodeURIComponent(id)}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
    downloadInvoicePdf: async (id: string, lang: string): Promise<{ blob: Blob; filename: string }> => {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const response = await fetch(`${apiBase}/quote/invoices/${encodeURIComponent(id)}/pdf?lang=${lang}`, { headers });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
      }
      const match = (response.headers.get('Content-Disposition') ?? '').match(/filename="?([^";]+)"?/);
      return { blob: await response.blob(), filename: match?.[1] ?? 'Rechnung.pdf' };
    },
  getPlateTuning: (printerId: number) =>
    request<{ saved: number | null; default: number; effective: number }>(
      `/printers/${printerId}/camera/plate-detection/tuning`
    ),
  analyzePlateTuning: async (printerId: number, empty: File[], occupied: File[]): Promise<PlateTuningAnalysis> => {
    const form = new FormData();
    empty.forEach((file) => form.append('empty', file));
    occupied.forEach((file) => form.append('occupied', file));
    const headers: Record<string, string> = {};
    if (getAuthToken()) headers['Authorization'] = `Bearer ${getAuthToken()}`;
    const response = await fetch(`${apiBase}/printers/${printerId}/camera/plate-detection/tuning/analyze`, {
      method: 'POST',
      headers,
      body: form,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
    }
    return response.json();
  },
  savePlateTuning: (printerId: number, threshold: number) =>
    request<{ saved: number }>(`/printers/${printerId}/camera/plate-detection/tuning`, {
      method: 'PUT',
      body: JSON.stringify({ threshold }),
    }),
  resetPlateTuning: (printerId: number) =>
    request<{ reset: boolean }>(`/printers/${printerId}/camera/plate-detection/tuning`, { method: 'DELETE' }),
  getSetupStatus: () => request<SetupStatus>('/system/setup-status'),
  getAlertChannels: () => request<AlertChannelsStatus>('/system/alerts'),
  saveAlertChannels: (update: Record<string, string>) =>
    request<AlertChannelsStatus>('/system/alerts', { method: 'PUT', body: JSON.stringify(update) }),
  testAlertChannels: () => request<{ sent: string[]; errors: string[] }>('/system/alerts/test', { method: 'POST' }),
  getUpdateBackups: () => request<UpdateBackups>('/updates/backups'),
  restoreUpdateBackup: (name: string) =>
    request<{ success: boolean; name: string }>(`/updates/backups/${encodeURIComponent(name)}/restore`, { method: 'POST' }),
  dismissRestoreNotice: () => request<{ ok: boolean }>('/updates/restore-notice/dismiss', { method: 'POST' }),
  dismissRollbackNotice: () => request<{ ok: boolean }>('/updates/rollback-notice/dismiss', { method: 'POST' }),

  uploadCompanyLogo: async (file: File): Promise<{ has_logo: boolean }> => {
    const form = new FormData();
    form.append('file', file);
    const headers: Record<string, string> = {};
    if (getAuthToken()) headers['Authorization'] = `Bearer ${getAuthToken()}`;
    const response = await fetch(`${apiBase}/quote/company/logo`, { method: 'PUT', headers, body: form });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteCompanyLogo: () => request<{ deleted: boolean }>('/quote/company/logo', { method: 'DELETE' }),
  getCompanyProfile: () => request<CompanyProfile>('/quote/company'),
  saveCompanyProfile: (data: Partial<CompanyProfile>) =>
    request<CompanyProfile>('/quote/company', { method: 'PUT', body: JSON.stringify(data) }),
  downloadQuotePdf: async (id: string, lang: string): Promise<{ blob: Blob; filename: string }> => {
    const headers: Record<string, string> = {};
    if (getAuthToken()) headers['Authorization'] = `Bearer ${getAuthToken()}`;
    const response = await fetch(`${apiBase}/quote/history/${encodeURIComponent(id)}/pdf?lang=${lang}`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
    }
    const match = (response.headers.get('Content-Disposition') ?? '').match(/filename="?([^";]+)"?/);
    return { blob: await response.blob(), filename: match?.[1] ?? 'Angebot.pdf' };
  },
  getPiHealth: () => request<PiHealth>('/system/pi-health'),
  getRemoteAccess: () => request<RemoteAccessStatus>('/remote-access'),
  setupRemoteAccess: () => request<RemoteAccessStatus>('/remote-access/setup', { method: 'POST' }),
  shareRemoteAccess: () => request<RemoteAccessStatus>('/remote-access/share', { method: 'POST' }),
  setRemoteAccessHttps: (enabled: boolean) =>
    request<RemoteAccessStatus>(`/remote-access/https?enabled=${enabled}`, { method: 'POST' }),
  setRemoteAccessSlicer: (enabled: boolean) =>
    request<RemoteAccessStatus>(`/remote-access/slicer?enabled=${enabled}`, { method: 'POST' }),
  disableRemoteAccess: () => request<RemoteAccessStatus>('/remote-access/disable', { method: 'POST' }),
  };
}
