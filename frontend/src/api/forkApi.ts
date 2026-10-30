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

export interface QuoteItem {
  description: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface QuoteActualsLine {
  archive_id: number;
  filename: string;
  status: string;
  grams: number;
  minutes: number;
  material: number;
  energy: number;
  estimated: boolean;
}

export interface QuoteActuals {
  quote_id: string;
  currency: string;
  linked: number;
  lines: QuoteActualsLine[];
  grams: number;
  minutes: number;
  material: number;
  energy: number;
  labor: number;
  labor_measured: boolean;
  work_minutes: number | null;
  actual_cost: number;
  quoted_cost: number;
  deviation: number;
  revenue: number;
  profit: number;
  missing_ids: number[];
}

export interface AssistantConfig {
  enabled: boolean;
  base_url: string;
  model: string;
  timeout_seconds: number;
  max_tokens: number;
}

export interface AssistantStatus {
  config: AssistantConfig;
  server: { reachable: boolean; models: string[]; model_present: boolean; error: string };
}

export interface AssistantAction {
  type: 'set_priority' | 'set_due_date';
  item_id: number;
  label: string;
  priority?: number;
  due_at?: string | null;
}

export interface AssistantAnswer {
  reply: string;
  actions: AssistantAction[];
  rejected: number;
  seconds: number;
}

export interface QuoteQueueRequest {
  printer_id?: number | null;
  target_model?: string | null;
  priority?: number;
  quantity?: number;
}

export interface QuoteQueueResult {
  quote_id: string;
  queued: { archive_id: number; queue_item_id: number | null }[];
  errors: { archive_id: number; detail: string }[];
  message: string;
}

export interface SelfTestResult {
  id: string;
  title: string;
  status: 'ok' | 'warn' | 'fail' | 'skip';
  detail: string;
  fix: string | null;
}

export interface FailureImage {
  name: string;
  event: string;
  timestamp: string;
  size: number;
  mtime: number;
}

export interface Customer {
  id: number;
  name: string;
  address: string;
  email: string;
  phone: string;
  note?: string | null;
}

export interface MonthlyReportMoney {
  count: number;
  open: number;
  paid: number;
  cancelled: number;
  total: number;
  overdue_count: number;
  overdue: number;
}

export interface MonthlyReport {
  year: number;
  month: number;
  period: { start: string; end: string };
  invoices: Record<string, MonthlyReportMoney>;
  quotes: Record<string, number>;
  profit: {
    quotes: number;
    estimated_quotes: number;
    per_currency: Record<string, { revenue: number; actual_cost: number; profit: number }>;
  };
  production: {
    prints: number;
    failed: number;
    minutes: number;
    grams: number;
    material_cost: number;
    energy_cost: number;
    by_filament_type: { type: string; grams: number }[];
    by_printer: { name: string; prints: number; minutes: number }[];
  };
}

export interface SelfTestReport {
  checked_at: string;
  results: SelfTestResult[];
  summary: { ok: number; warn: number; fail: number; skip: number };
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

export interface ErrorPatternAction {
  id: string;
  title: string;
  title_en: string;
  command: string;
  effect: string;
  effect_en: string;
  requires: string;
}

export interface ErrorPattern {
  id: string;
  category: string;
  title: string;
  title_en: string;
  summary: string;
  summary_en: string;
  causes: string[];
  slicer: string[];
  automation: string[];
  actions: string[];
  rules: string[];
}

export interface ErrorCategory {
  id: string;
  title: string;
  title_en: string;
  hint: string;
  hint_en: string;
}

export interface CountermeasureRuleInfo {
  title: string;
  title_en: string;
  patterns: string[];
}

export interface ErrorHelpCatalog {
  categories: ErrorCategory[];
  patterns: ErrorPattern[];
  manual_actions: ErrorPatternAction[];
  rules: Record<string, CountermeasureRuleInfo>;
}

export interface CountermeasuresConfig {
  enabled: boolean;
  dry_run: boolean;
  printers: Record<string, { enabled: boolean; rules: Record<string, boolean> }>;
  thresholds: { hot_c: number; cold_c: number };
  cooldown_seconds: number;
  max_per_print: number;
}

export interface CountermeasurePrinter {
  id: number;
  name: string;
  model: string | null;
  chamber_supported: boolean;
  enabled: boolean;
  rules: Record<string, boolean>;
  running: boolean;
  state: string | null;
  layer: number;
  material: string | null;
  chamber_c: number | null;
  available_actions: { id: string; command: string }[];
}

export interface CountermeasuresResponse {
  config: CountermeasuresConfig;
  rules: Record<string, CountermeasureRuleInfo>;
  printers: CountermeasurePrinter[];
}

export interface CountermeasureLogEntry {
  ts: string;
  action: string;
  ok: boolean;
  message: string;
  printer_id: number | null;
  details?: Record<string, unknown>;
}

export interface AiScanFinding {
  id: string;
  ts: string;
  pattern_id: string;
  confidence: number;
  reason: string;
  model: string | null;
  duration_ms: number | null;
  source: 'upload' | 'failure_image' | string;
  printer_id: number | null;
  image_name: string | null;
  verdict?: 'correct' | 'wrong' | null;
}

export interface AiScanBatch {
  running: boolean;
  done: number;
  total: number;
  matched: number;
  errors: number;
  started: string | null;
}

export interface AiScanConfigState {
  vision_model: string;
  error_scan_enabled: boolean;
  error_scan_min_confidence: number;
  model: string;
}

export interface AiScanServer {
  reachable: boolean;
  models: string[];
  model_present: boolean;
  error: string;
}

export interface AiScanResult {
  pattern_id: string | null;
  confidence: number;
  reason: string;
  model?: string;
  duration_ms?: number;
}

export interface AiScanResponse {
  config: AiScanConfigState;
  server: AiScanServer;
  vision_model: string;
  vision_present: boolean;
  findings: AiScanFinding[];
  counts: Record<string, number>;
  feedback?: { correct: number; wrong: number };
  batch?: AiScanBatch;
}

export interface ForkApiDeps {
  request: <T>(endpoint: string, options?: RequestInit) => Promise<T>;
  apiBase: string;
  getAuthToken: () => string | null;
}

export function createForkApi({ request, apiBase, getAuthToken }: ForkApiDeps) {
  return {
    runSelfTest: () => request<SelfTestReport>('/selftest', { method: 'POST' }),
  listFailureImages: () => request<FailureImage[]>('/failure-images/'),
  deleteFailureImage: (name: string) =>
    request<{ message: string }>(`/failure-images/${encodeURIComponent(name)}`, { method: 'DELETE' }),
    getAssistantStatus: () => request<AssistantStatus>('/assistant/status'),
    saveAssistantConfig: (update: Record<string, unknown>) =>
      request<AssistantStatus>('/assistant/config', { method: 'PUT', body: JSON.stringify(update) }),
    assistantChat: (messages: { role: 'user' | 'assistant'; content: string }[], lang: string) =>
      request<AssistantAnswer>('/assistant/chat', { method: 'POST', body: JSON.stringify({ messages, lang }) }),
    // Wort-für-Wort-Antwort über SSE (routes/assistant.py chat-stream). Aktionen kommen nur im „done“-Ereignis.
    streamAssistantChat: async (
      messages: { role: 'user' | 'assistant'; content: string }[],
      lang: string,
      onDelta: (text: string) => void,
      signal?: AbortSignal,
    ): Promise<AssistantAnswer> => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (getAuthToken()) headers['Authorization'] = `Bearer ${getAuthToken()}`;
      const response = await fetch(`${apiBase}/assistant/chat-stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify({ messages, lang }),
        signal,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
      }
      if (!response.body) {
        throw new Error('assistant stream aborted');
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffered = '';
      let answer: AssistantAnswer | null = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffered += decoder.decode(value, { stream: true });
        let sep = buffered.indexOf('\n\n');
        while (sep !== -1) {
          const frame = buffered.slice(0, sep);
          buffered = buffered.slice(sep + 2);
          const line = frame.split('\n').find((row) => row.startsWith('data: '));
          if (line) {
            const event = JSON.parse(line.slice(6)) as
              | { type: 'delta'; text: string }
              | (AssistantAnswer & { type: 'done' })
              | { type: 'error'; detail: string };
            if (event.type === 'delta') onDelta(event.text);
            else if (event.type === 'done') answer = event;
            else if (event.type === 'error') throw new Error(event.detail);
          }
          sep = buffered.indexOf('\n\n');
        }
      }
      if (!answer) {
        throw new Error('assistant stream aborted');
      }
      return answer;
    },
    getQuoteActuals: (id: string) => request<QuoteActuals>(`/quote/history/${encodeURIComponent(id)}/actuals`),
    setQuoteWorkMinutes: (id: string, minutes: number | null) =>
      request<Record<string, unknown>>(`/quote/history/${encodeURIComponent(id)}/work-minutes`, {
        method: 'PUT',
        body: JSON.stringify({ work_minutes: minutes }),
      }),
    queueQuotePrints: (id: string, payload: QuoteQueueRequest) =>
      request<QuoteQueueResult>(`/quote/history/${encodeURIComponent(id)}/queue`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    linkQuoteArchives: (id: string, archiveIds: number[]) =>
      request<{ archive_ids: number[] }>(`/quote/history/${encodeURIComponent(id)}/archives`, {
        method: 'PUT',
        body: JSON.stringify({ archive_ids: archiveIds }),
      }),
    getInvoices: () => request<InvoicesResponse>('/quote/invoices'),
    listCustomers: () => request<Customer[]>('/customers/'),
    createCustomer: (data: Omit<Customer, 'id'>) =>
      request<Customer>('/customers/', { method: 'POST', body: JSON.stringify(data) }),
    updateCustomer: (id: number, data: Omit<Customer, 'id'>) =>
      request<Customer>(`/customers/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    deleteCustomer: (id: number) => request<{ message: string }>(`/customers/${id}`, { method: 'DELETE' }),
    getMonthlyReport: (year: number, month: number) => request<MonthlyReport>(`/monthly-report/${year}/${month}`),
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
  downloadMonthlyReportPdf: async (year: number, month: number, lang: string): Promise<{ blob: Blob; filename: string }> => {
    const headers: Record<string, string> = {};
    if (getAuthToken()) headers['Authorization'] = `Bearer ${getAuthToken()}`;
    const response = await fetch(`${apiBase}/monthly-report/${year}/${month}/pdf?lang=${lang}`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
    }
    const match = (response.headers.get('Content-Disposition') ?? '').match(/filename="?([^";]+)"?/);
    return { blob: await response.blob(), filename: match?.[1] ?? 'Monatsreport.pdf' };
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
  getErrorHelp: () => request<ErrorHelpCatalog>('/error-help'),
  getCountermeasures: () => request<CountermeasuresResponse>('/error-help/countermeasures'),
  saveCountermeasures: (update: Partial<CountermeasuresConfig>) =>
    request<CountermeasuresConfig>('/error-help/countermeasures', { method: 'PUT', body: JSON.stringify(update) }),
  runCountermeasure: (printerId: number, actionId: string) =>
    request<{ success: boolean; command: string; message: string }>(
      `/error-help/countermeasures/${printerId}/action`,
      { method: 'POST', body: JSON.stringify({ action_id: actionId }) }
    ),
  getCountermeasureLog: (limit = 30) =>
    request<CountermeasureLogEntry[]>(`/error-help/countermeasures/log?limit=${limit}`),
  getAiScan: () => request<AiScanResponse>('/error-help/ai-scan'),
  saveAiScan: (update: Partial<AiScanConfigState>) =>
    request<AiScanResponse>('/error-help/ai-scan', { method: 'PUT', body: JSON.stringify(update) }),
  scanAiErrorImage: async (file: File): Promise<{ result: AiScanResult; findings: AiScanFinding[]; counts: Record<string, number> }> => {
    const form = new FormData();
    form.append('file', file);
    const headers: Record<string, string> = {};
    if (getAuthToken()) headers['Authorization'] = `Bearer ${getAuthToken()}`;
    const response = await fetch(`${apiBase}/error-help/ai-scan/upload`, { method: 'POST', headers, body: form });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(typeof error.detail === 'string' ? error.detail : `HTTP ${response.status}`);
    }
    return response.json();
  },
  scanFailureImage: (name: string) =>
    request<{ result: AiScanResult; findings: AiScanFinding[]; counts: Record<string, number> }>(
      `/error-help/ai-scan/failure-image/${encodeURIComponent(name)}`,
      { method: 'POST' }
    ),
  getAiFindings: (limit: number, patternId?: string) =>
    request<{ findings: AiScanFinding[]; counts: Record<string, number> }>(
      `/error-help/ai-scan/findings?limit=${limit}${patternId ? `&pattern_id=${encodeURIComponent(patternId)}` : ''}`
    ),
  sendAiFeedback: (findingId: string, verdict: 'correct' | 'wrong') =>
    request<{ findings: AiScanFinding[]; feedback: { correct: number; wrong: number } }>(
      `/error-help/ai-scan/findings/${encodeURIComponent(findingId)}/feedback`,
      { method: 'POST', body: JSON.stringify({ verdict }) }
    ),
  scanAiCollection: (limit = 10) =>
    request<AiScanBatch>('/error-help/ai-scan/scan-collection', {
      method: 'POST',
      body: JSON.stringify({ limit }),
    }),
  };
}
