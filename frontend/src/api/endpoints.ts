/**
 * Die Endpunkte der API.
 *
 * Jede Methode geht über ``request`` aus core.ts; die Typen kommen aus types.ts.
 */

import { createForkApi } from './forkApi';
import type { ArchivePlatesResponse, LibraryFilePlatesResponse } from '../types/plates';
import { API_BASE, authToken, buildSlicerUrlFilename, parseContentDispositionFilename, postForBlob, request, uploadSpoolsCsv, withMediaToken, withStreamToken } from './core';
import type {
  AMSHistoryResponse,
  APIKey,
  APIKeyCreate,
  APIKeyCreateResponse,
  APIKeyUpdate,
  AddToQueueResponse,
  AdvancedAuthStatus,
  AppSettings,
  AppSettingsUpdate,
  Archive,
  ArchiveComparison,
  ArchiveDuplicate,
  ArchivePrinterMedia,
  ArchivePurgePreview,
  ArchivePurgeSettings,
  ArchiveSlim,
  ArchiveStats,
  AuditEntry,
  AuthStatus,
  AutoPlateChange,
  BOMItem,
  BOMItemCreate,
  BOMItemUpdate,
  BackupCodesResponse,
  BatchThumbnailResponse,
  BedEmptyCheckStatus,
  BuiltinFilament,
  BulkUploadResult,
  CalibrationResult,
  CamWallPrinter,
  CameraDiagnoseResult,
  CloudAccountCounts,
  CloudAuthStatus,
  CloudDevice,
  CloudLoginResponse,
  ColorCatalogEntry,
  ColorLookupResult,
  ConnectAuthorizeInfo,
  ConnectedApp,
  CostCenterBudgetUpdateRequest,
  CostCenterCreateRequest,
  CostCenterDetail,
  CostCenterMemberRequest,
  CostCenterMemberResponse,
  CostCenterSummary,
  CostCenterUpdateRequest,
  CsvImportPreview,
  CsvImportResult,
  DiscoveredTasmotaDevice,
  EncryptionStatus,
  EventVariablesResponse,
  ExternalFolderCreate,
  ExternalLink,
  ExternalLinkCreate,
  ExternalLinkUpdate,
  FailureAnalysis,
  FieldDefinitionsResponse,
  Filament,
  FilamentSkuSettings,
  FirstLayerStatus,
  ForgotPasswordRequest,
  ForgotPasswordResponse,
  GitHubBackupConfig,
  GitHubBackupConfigCreate,
  GitHubBackupLog,
  GitHubBackupStatus,
  GitHubBackupTriggerResponse,
  GitHubCommitListResponse,
  GitHubRestorePreview,
  GitHubRestoreRequest,
  GitHubRestoreResponse,
  GitHubTestConnectionResponse,
  GitProviderType,
  Group,
  GroupCreate,
  GroupDetail,
  GroupUpdate,
  HADisplayEntity,
  HAEntity,
  HASensorEntity,
  HATestConnectionResult,
  HMSActionBody,
  HardwareActionResponse,
  HardwareConfig,
  HardwareStatus,
  ImportResponse,
  InventoryRemainResponse,
  InventorySpool,
  KProfileCreate,
  KProfileDelete,
  KProfileNotesResponse,
  KProfilesResponse,
  LDAPSearchResult,
  LDAPStatus,
  LDAPTestResponse,
  LayerAlertStatus,
  LibraryFile,
  LibraryFileListItem,
  LibraryFileUpdate,
  LibraryFileUploadResponse,
  LibraryFolder,
  LibraryFolderCreate,
  LibraryFolderTree,
  LibraryFolderUpdate,
  LibraryPurgePreview,
  LibraryStats,
  LibraryTag,
  LibraryTagBulkAssignResult,
  LibraryTrashListResponse,
  LibraryTrashSettings,
  LinkedSpoolsMap,
  LocalBackupFile,
  LocalBackupPathCheck,
  LocalBackupStatus,
  LocalPreset,
  LocalPresetDetail,
  LocalPresetsResponse,
  LocationHASensor,
  LocationHASensorCreate,
  LocationHASensorReading,
  LocationHASensorUpdate,
  LoginRequest,
  LoginResponse,
  LongLivedCameraToken,
  LongLivedTokenScope,
  MQTTLogsResponse,
  MQTTStatus,
  MaintenanceHistory,
  MaintenancePrintResponse,
  MaintenanceProgram,
  MaintenanceProgramStartResponse,
  MaintenanceProgramStatus,
  MaintenanceStatus,
  MaintenanceSummary,
  MaintenanceType,
  MaintenanceTypeCreate,
  MakerworldImportResponse,
  MakerworldRecentImport,
  MakerworldResolvedModel,
  MakerworldStatus,
  ManualPrintRequest,
  MaterialNumberStats,
  NetworkInterface,
  NotificationLogEntry,
  NotificationLogStats,
  NotificationProvider,
  NotificationProviderCreate,
  NotificationProviderUpdate,
  NotificationTemplate,
  NotificationTemplateUpdate,
  NotificationTestRequest,
  NotificationTestResponse,
  OIDCLink,
  OIDCProvider,
  OIDCProviderCreate,
  OIDCProviderPublic,
  ObicoPrinterStatus,
  ObicoStatus,
  ObicoTestConnection,
  OrcaAuthStatusResponse,
  OrcaDevicePollResponse,
  OrcaDeviceStartResponse,
  OrcaProfileDetail,
  OrcaProfileListResponse,
  OverlayStatus,
  PartWatcherOverride,
  PartWatcherStatus,
  PartialHardwareSlot,
  PermissionsListResponse,
  PipelineEligibilityReport,
  PipelineRun,
  PipelineRunListResponse,
  PlateCalibrationStatus,
  PlateDetectionResult,
  PlateDetectionStatus,
  PlateReference,
  PresetRef,
  PreviewSpoolLabelRequest,
  PriceListEntry,
  PrintBatch,
  PrintBatchCreate,
  PrintBatchDispatchRequest,
  PrintBatchUpdate,
  PrintLogEntry,
  PrintLogResponse,
  PrintQueueBulkUpdate,
  PrintQueueBulkUpdateResponse,
  PrintQueueItem,
  PrintQueueItemCreate,
  PrintQueueItemUpdate,
  PrintSpoolLabelsRequest,
  Printer,
  PrinterCreate,
  PrinterDiagnosticResult,
  PrinterHASensor,
  PrinterHASensorCreate,
  PrinterHASensorReading,
  PrinterHASensorUpdate,
  PrinterMaintenanceOverview,
  PrinterSensorHistoryResponse,
  PrinterStatus,
  Project,
  ProjectAttachment,
  ProjectCreate,
  ProjectExport,
  ProjectFileProgress,
  ProjectImport,
  ProjectListItem,
  ProjectUpdate,
  QuoteCustomerTotal,
  QuoteHistoryEntry,
  QuoteResponse,
  ResetPasswordRequest,
  ResetPasswordResponse,
  SMTPSettings,
  SameOriginUrl,
  ScheduledDrying,
  SetupRequest,
  SetupResponse,
  ShoppingListItem,
  ShoppingListItemCreate,
  SimilarArchive,
  SliceJobEnqueueResponse,
  SliceJobProgress,
  SliceJobState,
  SliceRequest,
  SlicerPipeline,
  SlicerPipelineCreateRequest,
  SlicerPipelineUpdateRequest,
  SlicerPipelinesListResponse,
  SlicerPresetValues,
  SlicerSetting,
  SlicerSettingCreate,
  SlicerSettingDeleteResponse,
  SlicerSettingDetail,
  SlicerSettingUpdate,
  SlicerSettingsResponse,
  SlotPresetMapping,
  SlotSpoolDefaults,
  SmartPlug,
  SmartPlugCreate,
  SmartPlugStatus,
  SmartPlugTestResult,
  SmartPlugUpdate,
  SpaghettiCheckStatus,
  SpoolAssignment,
  SpoolCatalogEntry,
  SpoolFilamentPreset,
  SpoolFilamentPresetInput,
  SpoolKProfile,
  SpoolKProfileInput,
  SpoolSupplierLink,
  SpoolSupplierLinkInput,
  SpoolUsageRecord,
  SpoolmanBulkCreateResult,
  SpoolmanFilamentEntry,
  SpoolmanStatus,
  SpoolmanSyncResult,
  StorageLocation,
  StorageUsageResponse,
  Supplier,
  SupplierInput,
  SupplierStats,
  SystemHealthResult,
  SystemInfo,
  TOTPEnableResponse,
  TOTPSetupResponse,
  TagInfo,
  TasmotaScanStatus,
  TemplatePreviewRequest,
  TemplatePreviewResponse,
  TestSMTPRequest,
  TestSMTPResponse,
  TimelineEvent,
  TransactionEditRequest,
  TwoFAStatus,
  TwoFAVerifyRequest,
  UnifiedPresetsResponse,
  UnlinkedSpool,
  UpdateCheckResult,
  UpdateStatus,
  UserCreate,
  UserEmailPreferences,
  UserResponse,
  UserSlim,
  UserUpdate,
  VariantGroup,
  VersionInfo,
  WalletAdjustmentRequest,
  WalletAdjustmentResponse,
  WalletBalance,
  WalletTransaction,
  WalletTransactionListResponse,
  ZipExtractResponse,
} from './types';

export const api = {
  ...createForkApi({ request, apiBase: API_BASE, getAuthToken: () => authToken }),
  // Authentication
  getAuthStatus: () => request<AuthStatus>('/auth/status'),
  setupAuth: (data: SetupRequest) =>
    request<SetupResponse>('/auth/setup', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  login: (data: LoginRequest) =>
    request<LoginResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  logout: () =>
    request<{ message: string }>('/auth/logout', {
      method: 'POST',
    }),
  getCurrentUser: () => request<UserResponse>('/auth/me'),
  disableAuth: () =>
    request<{ message: string; auth_enabled: boolean }>('/auth/disable', {
      method: 'POST',
    }),

  // Advanced Authentication
  testSMTP: (data: TestSMTPRequest) =>
    request<TestSMTPResponse>('/auth/smtp/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getSMTPSettings: () => request<SMTPSettings | null>('/auth/smtp'),
  saveSMTPSettings: (data: SMTPSettings) =>
    request<{ message: string }>('/auth/smtp', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  enableAdvancedAuth: () =>
    request<{ message: string; advanced_auth_enabled: boolean }>('/auth/advanced-auth/enable', {
      method: 'POST',
    }),
  disableAdvancedAuth: () =>
    request<{ message: string; advanced_auth_enabled: boolean }>('/auth/advanced-auth/disable', {
      method: 'POST',
    }),
  getAdvancedAuthStatus: () => request<AdvancedAuthStatus>('/auth/advanced-auth/status'),
  // LDAP Authentication
  getLDAPStatus: () => request<LDAPStatus>('/auth/ldap/status'),
  getEncryptionStatus: () => request<EncryptionStatus>('/auth/encryption-status'),
  testLDAP: () =>
    request<LDAPTestResponse>('/auth/ldap/test', {
      method: 'POST',
    }),
  searchLDAPDirectory: (q: string) =>
    request<LDAPSearchResult[]>(`/auth/ldap/search?q=${encodeURIComponent(q)}`),
  provisionLDAPUser: (username: string) =>
    request<UserResponse>('/auth/ldap/provision', {
      method: 'POST',
      body: JSON.stringify({ username }),
    }),
  forgotPassword: (data: ForgotPasswordRequest) =>
    request<ForgotPasswordResponse>('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  // H-6: Confirm password reset using the token from the emailed link
  forgotPasswordConfirm: (token: string, newPassword: string) =>
    request<ForgotPasswordResponse>('/auth/forgot-password/confirm', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword }),
    }),
  resetUserPassword: (data: ResetPasswordRequest) =>
    request<ResetPasswordResponse>('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 2FA - status
  get2FAStatus: () => request<TwoFAStatus>('/auth/2fa/status'),

  // 2FA - TOTP
  setupTOTP: () => request<TOTPSetupResponse>('/auth/2fa/totp/setup', { method: 'POST' }),
  enableTOTP: (code: string) =>
    request<TOTPEnableResponse>('/auth/2fa/totp/enable', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  disableTOTP: (code: string) =>
    request<{ message: string }>('/auth/2fa/totp/disable', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
  regenerateBackupCodes: (code: string) =>
    request<BackupCodesResponse>('/auth/2fa/totp/regenerate-backup-codes', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  // 2FA - Email OTP
  // Step 1: send a verification code to the user's email (proof of possession)
  enableEmailOTP: () =>
    request<{ message: string; setup_token: string }>('/auth/2fa/email/enable', { method: 'POST' }),
  // Step 2: confirm with the code received by email
  confirmEnableEmailOTP: (setup_token: string, code: string) =>
    request<{ message: string }>('/auth/2fa/email/enable/confirm', {
      method: 'POST',
      body: JSON.stringify({ setup_token, code }),
    }),
  // Disable requires account password for re-auth
  disableEmailOTP: (password: string) =>
    request<{ message: string }>('/auth/2fa/email/disable', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  sendEmailOTP: (preAuthToken: string) =>
    request<{ message: string; pre_auth_token?: string }>('/auth/2fa/email/send', {
      method: 'POST',
      body: JSON.stringify({ pre_auth_token: preAuthToken }),
    }),

  // 2FA - verify (completes login)
  verify2FA: (data: TwoFAVerifyRequest) =>
    request<LoginResponse>('/auth/2fa/verify', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // 2FA - admin
  admin2FADisable: (userId: number) =>
    request<{ message: string }>(`/auth/2fa/admin/${userId}`, { method: 'DELETE' }),

  // OIDC providers (public list)
  getOIDCProviders: () => request<OIDCProviderPublic[]>('/auth/oidc/providers'),

  // OIDC providers (admin)
  getOIDCProvidersAll: () => request<OIDCProvider[]>('/auth/oidc/providers/all'),
  createOIDCProvider: (data: OIDCProviderCreate) =>
    request<OIDCProvider>('/auth/oidc/providers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateOIDCProvider: (id: number, data: Partial<OIDCProviderCreate>) =>
    request<OIDCProvider>(`/auth/oidc/providers/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteOIDCProvider: (id: number) =>
    request<{ message: string }>(`/auth/oidc/providers/${id}`, { method: 'DELETE' }),

  // OIDC provider icon proxy (#1333) — same-origin path so the strict
  // img-src CSP stays in force. Returns a SameOriginUrl-branded string
  // so a future caller can't accidentally substitute an attacker-
  // controlled URL where this is consumed.
  oidcProviderIconUrl: (id: number): SameOriginUrl =>
    `/api/v1/auth/oidc/providers/${id}/icon` as SameOriginUrl,
  deleteOIDCProviderIcon: (id: number) =>
    request<void>(`/auth/oidc/providers/${id}/icon`, { method: 'DELETE' }),
  refreshOIDCProviderIcon: (id: number) =>
    request<OIDCProvider>(`/auth/oidc/providers/${id}/icon/refresh`, { method: 'POST' }),

  // OIDC authorize URL
  getOIDCAuthorizeUrl: (providerId: number) =>
    request<{ auth_url: string }>(`/auth/oidc/authorize/${providerId}`),

  // OIDC exchange token for JWT
  exchangeOIDCToken: (oidcToken: string) =>
    request<LoginResponse>('/auth/oidc/exchange', {
      method: 'POST',
      body: JSON.stringify({ oidc_token: oidcToken }),
    }),

  // OIDC links for current user
  getOIDCLinks: () => request<OIDCLink[]>('/auth/oidc/links'),
  deleteOIDCLink: (providerId: number) =>
    request<{ message: string }>(`/auth/oidc/links/${providerId}`, { method: 'DELETE' }),

  // Users
  getUsers: () => request<UserResponse[]>('/users/'),
  getUsersSlim: () => request<UserSlim[]>('/users/slim'),
  getUser: (id: number) => request<UserResponse>(`/users/${id}`),
  createUser: (data: UserCreate) =>
    request<UserResponse>('/users/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateUser: (id: number, data: UserUpdate) =>
    request<UserResponse>(`/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteUser: (id: number, deleteItems: boolean = false) =>
    request<void>(`/users/${id}?delete_items=${deleteItems}`, {
      method: 'DELETE',
    }),
  getUserItemsCount: (id: number) =>
    request<{ archives: number; queue_items: number; library_files: number }>(`/users/${id}/items-count`),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ message: string }>('/users/me/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  // User Email Notifications
  getUserEmailPreferences: () =>
    request<UserEmailPreferences>('/user-notifications/preferences'),
  updateUserEmailPreferences: (data: UserEmailPreferences) =>
    request<UserEmailPreferences>('/user-notifications/preferences', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Groups
  getPermissions: () => request<PermissionsListResponse>('/groups/permissions'),
  getGroups: () => request<Group[]>('/groups/'),
  getGroup: (id: number) => request<GroupDetail>(`/groups/${id}`),
  createGroup: (data: GroupCreate) =>
    request<Group>('/groups/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateGroup: (id: number, data: GroupUpdate) =>
    request<Group>(`/groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteGroup: (id: number) =>
    request<void>(`/groups/${id}`, {
      method: 'DELETE',
    }),
  addUserToGroup: (groupId: number, userId: number) =>
    request<void>(`/groups/${groupId}/users/${userId}`, {
      method: 'POST',
    }),
  removeUserFromGroup: (groupId: number, userId: number) =>
    request<void>(`/groups/${groupId}/users/${userId}`, {
      method: 'DELETE',
    }),

  // Printers
  getPrinters: () => request<Printer[]>('/printers/'),
  getPrinter: (id: number) => request<Printer>(`/printers/${id}`),
  createPrinter: (data: PrinterCreate) =>
    request<Printer>('/printers/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updatePrinter: (id: number, data: Partial<PrinterCreate>) =>
    request<Printer>(`/printers/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deletePrinter: (id: number, deleteArchives: boolean = true) =>
    request<{ status: string; archives_deleted: boolean }>(
      `/printers/${id}?delete_archives=${deleteArchives}`,
      { method: 'DELETE' }
    ),
  getDeveloperModeWarnings: () =>
    request<{ printer_id: number; name: string }[]>('/printers/developer-mode-warnings'),
  getAvailableFilaments: (model: string, location?: string) => {
    const params = new URLSearchParams({ model });
    if (location) params.set('location', location);
    return request<Array<{ type: string; color: string; tray_info_idx: string; tray_sub_brands: string; extruder_id: number | null }>>(`/printers/available-filaments?${params}`);
  },
  getPrinterStatus: (id: number) =>
    request<PrinterStatus>(`/printers/${id}/status`),
  refreshPrinterStatus: (id: number) =>
    request<{ status: string }>(`/printers/${id}/refresh-status`, {
      method: 'POST',
    }),
  connectPrinter: (id: number) =>
    request<{ connected: boolean }>(`/printers/${id}/connect`, {
      method: 'POST',
    }),
  disconnectPrinter: (id: number) =>
    request<{ connected: boolean }>(`/printers/${id}/disconnect`, {
      method: 'POST',
    }),
  testExternalCamera: (printerId: number, url: string, cameraType: string) =>
    // `coalesced` is true when the frame came from a capture that was already
    // running (Obico polling, a snapshot) rather than a connection this test
    // opened — a single-reader camera is shared rather than opened twice, so
    // the result is real but says nothing about reaching the camera just now.
    request<{ success: boolean; error?: string; resolution?: string; coalesced?: boolean }>(
      `/printers/${printerId}/camera/external/test?url=${encodeURIComponent(url)}&camera_type=${encodeURIComponent(cameraType)}`,
      { method: 'POST' }
    ),

  // Print Control
  stopPrint: (printerId: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/print/stop`, {
      method: 'POST',
    }),
  pausePrint: (printerId: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/print/pause`, {
      method: 'POST',
    }),
  resumePrint: (printerId: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/print/resume`, {
      method: 'POST',
    }),
  clearPlate: (printerId: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/clear-plate`, {
      method: 'POST',
    }),

  // Get current print user (for reprint tracking - Issue #206)
  getCurrentPrintUser: (printerId: number) =>
    request<{ user_id?: number; username?: string }>(`/printers/${printerId}/current-print-user`),

  // Print Speed Control
  setPrintSpeed: (printerId: number, mode: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/print-speed?mode=${mode}`, {
      method: 'POST',
    }),

  setNozzleTemperature: (printerId: number, target: number, nozzle: number = 0) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/temperature/nozzle?target=${target}&nozzle=${nozzle}`,
      { method: 'POST' }
    ),

  setBedTemperature: (printerId: number, target: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/temperature/bed?target=${target}`, {
      method: 'POST',
    }),

  setChamberTemperature: (printerId: number, target: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/temperature/chamber?target=${target}`, {
      method: 'POST',
    }),

  setFanSpeed: (printerId: number, fan: 'part' | 'aux' | 'aux2' | 'chamber', speed: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/fan-speed?fan=${fan}&speed=${speed}`, {
      method: 'POST',
    }),

  selectExtruder: (printerId: number, extruder: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/select-extruder?extruder=${extruder}`, {
      method: 'POST',
    }),

  setAirductMode: (printerId: number, mode: 'cooling' | 'heating') =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/airduct-mode?mode=${mode}`, {
      method: 'POST',
    }),

  // Bed (Z-axis) jog
  bedJog: (printerId: number, distance: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/bed-jog?distance=${distance}`,
      { method: 'POST' }
    ),
  xyJog: (printerId: number, x: number, y: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/xy-jog?x=${x}&y=${y}`,
      { method: 'POST' }
    ),
  extruderJog: (printerId: number, distance: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/extruder-jog?distance=${distance}`,
      { method: 'POST' }
    ),
  homeAxes: (printerId: number, axes: 'z' | 'xy' | 'all' = 'z') =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/home-axes?axes=${axes}`,
      { method: 'POST' }
    ),

  // Chamber Light Control
  setChamberLight: (printerId: number, on: boolean) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/chamber-light?on=${on}`, {
      method: 'POST',
    }),

  // AMS Drying Control
  startDrying: (printerId: number, amsId: number, temp: number, duration: number, filament: string = '', rotateTray: boolean = false) =>
    request<{ status: string; ams_id: number; temp: number; duration: number }>(
      `/printers/${printerId}/drying/start?ams_id=${amsId}&temp=${temp}&duration=${duration}&filament=${encodeURIComponent(filament)}&rotate_tray=${rotateTray}`,
      { method: 'POST' }
    ),
  stopDrying: (printerId: number, amsId: number) =>
    request<{ status: string; ams_id: number }>(
      `/printers/${printerId}/drying/stop?ams_id=${amsId}`,
      { method: 'POST' }
    ),

  // Scheduled (delayed) drying runs (#2638)
  createScheduledDrying: (data: {
    printer_id: number;
    ams_id: number;
    temp: number;
    duration_hours: number;
    filament?: string;
    rotate_tray?: boolean;
    start_after: string | null;
  }) =>
    request<ScheduledDrying>('/scheduled-dryings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  // Omit printerId for the whole fleet in one request; the printer cards share
  // that single query rather than each polling for its own id.
  listScheduledDryings: (printerId?: number) =>
    request<ScheduledDrying[]>(
      printerId === undefined ? '/scheduled-dryings' : `/scheduled-dryings?printer_id=${printerId}`
    ),
  cancelScheduledDrying: (id: number) =>
    request<{ status: string; id: number }>(`/scheduled-dryings/${id}`, { method: 'DELETE' }),

  // AMS Filament Backup (auto-switch to a backup spool when one runs out)
  setAmsFilamentBackup: (printerId: number, enabled: boolean) =>
    request<{ success: boolean; ams_filament_backup: boolean }>(
      `/printers/${printerId}/ams-backup?enabled=${enabled}`,
      { method: 'POST' }
    ),

  // Per-globalTrayId remaining grams for this printer's inventory-bound slots
  // (#1766). Drives the client-side "Prefer Lowest Remaining Filament" sort
  // when computing the AMS mapping; mirrors backend `_build_inventory_remain_overrides`
  // so internal and Spoolman modes both work uniformly.
  getInventoryRemain: (printerId: number) =>
    request<InventoryRemainResponse>(
      `/printers/${printerId}/inventory-remain`,
    ),

  // Skip Objects
  getPrintableObjects: (printerId: number) =>
    request<{
      objects: Array<{ id: number; name: string; x: number | null; y: number | null; skipped: boolean }>;
      total: number;
      skipped_count: number;
      is_printing: boolean;
      bbox_all: [number, number, number, number] | null;
    }>(`/printers/${printerId}/print/objects`),

  skipObjects: (printerId: number, objectIds: number[]) =>
    request<{ success: boolean; message: string; skipped_objects: number[] }>(
      `/printers/${printerId}/print/skip-objects`,
      {
        method: 'POST',
        body: JSON.stringify(objectIds),
      }
    ),

  // HMS Errors
  clearHMSErrors: (printerId: number) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/hms/clear`, { method: 'POST' }),
  executeHMSAction: (printerId: number, data: HMSActionBody) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/hms/execute-action`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // AMS Control
  refreshAmsSlot: (printerId: number, amsId: number, slotId: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/ams/${amsId}/slot/${slotId}/refresh`,
      { method: 'POST' }
    ),

  // Load filament from a tray. trayId: 0-15 for AMS (amsId*4+slotId), 254 for external spool.
  // extruderId (0 = right, 1 = left) names the hotend to feed. Pass it only on a
  // printer with a Filament Track Switch — there the AMS is bound to a switch
  // inlet rather than a hotend, so the firmware cannot work the target out and
  // drops the command. Omit it everywhere else, as BambuStudio does.
  loadAmsTray: (printerId: number, trayId: number, extruderId?: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/ams/load?tray_id=${trayId}` +
        (extruderId !== undefined ? `&extruder_id=${extruderId}` : ''),
      { method: 'POST' }
    ),

  // Unload filament. trayId names the slot to unload, which is what tells a
  // dual-nozzle printer which of its two hotends to act on; omit it to unload
  // whatever the printer's single tray_now field names.
  unloadAms: (printerId: number, trayId?: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/ams/unload` + (trayId !== undefined ? `?tray_id=${trayId}` : ''),
      { method: 'POST' }
    ),

  // MQTT Debug Logging
  enableMQTTLogging: (printerId: number) =>
    request<{ logging_enabled: boolean }>(`/printers/${printerId}/logging/enable`, {
      method: 'POST',
    }),
  disableMQTTLogging: (printerId: number) =>
    request<{ logging_enabled: boolean }>(`/printers/${printerId}/logging/disable`, {
      method: 'POST',
    }),
  getMQTTLogs: (printerId: number) =>
    request<MQTTLogsResponse>(`/printers/${printerId}/logging`),
  clearMQTTLogs: (printerId: number) =>
    request<{ status: string }>(`/printers/${printerId}/logging`, {
      method: 'DELETE',
    }),

  // Printer File Manager
  getPrinterFiles: (printerId: number, path = '/') =>
    request<{
      path: string;
      files: Array<{
        name: string;
        is_directory: boolean;
        size: number;
        path: string;
        mtime?: string;
      }>;
      warnings: Array<'printer_unavailable'>;
    }>(`/printers/${printerId}/files?path=${encodeURIComponent(path)}`),
  getPrinterFileDownloadUrl: (printerId: number, path: string) =>
    `${API_BASE}/printers/${printerId}/files/download?path=${encodeURIComponent(path)}`,
  getPrinterFileGcodeUrl: (printerId: number, path: string) =>
    `${API_BASE}/printers/${printerId}/files/gcode?path=${encodeURIComponent(path)}`,
  getPrinterFilePlates: (printerId: number, path: string) =>
    request<{
      printer_id: number;
      path: string;
      filename: string;
      plates: Array<{
        index: number;
        name: string | null;
        objects: string[];
        has_thumbnail: boolean;
        thumbnail_url: string | null;
        print_time_seconds: number | null;
        filament_used_grams: number | null;
        filaments: Array<{
          slot_id: number;
          type: string;
          color: string;
          used_grams: number;
          used_meters: number;
        }>;
      }>;
      is_multi_plate: boolean;
    }>(`/printers/${printerId}/files/plates?path=${encodeURIComponent(path)}`),
  getPrinterFilePlateThumbnail: (printerId: number, plateIndex: number, path: string) =>
    withMediaToken(`${API_BASE}/printers/${printerId}/files/plate-thumbnail/${plateIndex}?path=${encodeURIComponent(path)}`),
  downloadPrinterFilesAsZip: async (
    printerId: number,
    paths: string[],
    sizes: Record<string, number>,
    filename = 'printer-files.zip',
    asZip = true,
    signal?: AbortSignal,
    onProgress?: (completed: number, total: number) => void,
  ): Promise<{ requested: number; successful: number; failed: number }> => {
    type JobStatus = {
      job_id: string;
      state: 'queued' | 'preparing' | 'ready' | 'failed' | 'cancelled';
      requested: number;
      successful: number;
      failed: number;
      token: string | null;
      message: string | null;
    };
    let jobId: string | null = null;
    try {
      if (signal?.aborted) throw new DOMException('Download cancelled', 'AbortError');
      let status = await request<JobStatus>(`/printers/${printerId}/files/download-job`, {
        method: 'POST',
        body: JSON.stringify({ paths, sizes, filename, as_zip: asZip }),
        signal,
      });
      jobId = status.job_id;
      let polls = 0;
      while (status.state === 'queued' || status.state === 'preparing') {
        onProgress?.(status.successful + status.failed, status.requested);
        // Small selections finish in the first seconds, so poll quickly there.
        // A large one runs for up to half an hour, where half-second polling is
        // thousands of requests that each re-check the caller's credentials.
        const delay = polls < 10 ? 500 : 2000;
        polls += 1;
        await new Promise<void>((resolve, reject) => {
          if (signal?.aborted) {
            reject(new DOMException('Download cancelled', 'AbortError'));
            return;
          }
          const onAbort = () => {
            window.clearTimeout(timer);
            reject(new DOMException('Download cancelled', 'AbortError'));
          };
          const timer = window.setTimeout(() => {
            signal?.removeEventListener('abort', onAbort);
            resolve();
          }, delay);
          signal?.addEventListener('abort', onAbort, { once: true });
        });
        status = await request<JobStatus>(`/printers/${printerId}/files/download-jobs/${jobId}`, { signal });
      }
      onProgress?.(status.successful + status.failed, status.requested);
      if (status.state !== 'ready' || !status.token) {
        throw new Error(status.message || (status.state === 'cancelled'
          ? 'Download cancelled'
          : 'Printer download preparation failed'));
      }
      const link = document.createElement('a');
      link.href = `${API_BASE}/printers/${printerId}/files/dl/${encodeURIComponent(status.token)}/${encodeURIComponent(filename)}`;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      return {
        requested: status.requested,
        successful: status.successful,
        failed: status.failed,
      };
    } catch (error) {
      if (jobId) {
        await request(`/printers/${printerId}/files/download-jobs/${jobId}`, { method: 'DELETE' }).catch(() => undefined);
      }
      throw error;
    }
  },
  deletePrinterFile: (printerId: number, path: string) =>
    request<{ status: string; path: string }>(`/printers/${printerId}/files?path=${encodeURIComponent(path)}`, {
      method: 'DELETE',
    }),
  getPrinterStorage: (printerId: number) =>
    request<{ used_bytes: number | null; free_bytes: number | null }>(`/printers/${printerId}/storage`),

  // Archives
  getArchives: (printerId?: number, projectId?: number, limit = 10000, offset = 0, dateFrom?: string, dateTo?: string) => {
    const params = new URLSearchParams();
    if (printerId) params.set('printer_id', String(printerId));
    if (projectId) params.set('project_id', String(projectId));
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    return request<Archive[]>(`/archives/?${params}`);
  },
  getArchivesSlim: (dateFrom?: string, dateTo?: string, createdById?: number) => {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    if (createdById !== undefined) params.set('created_by_id', String(createdById));
    const qs = params.toString();
    return request<ArchiveSlim[]>(`/archives/slim${qs ? `?${qs}` : ''}`);
  },
  getArchive: (id: number) => request<Archive>(`/archives/${id}`),
  getArchiveRuns: (id: number) => request<PrintLogResponse>(`/archives/${id}/runs`),
  /**
   * Pre-flight for the delete-confirm modal (#1734). Returns the number of
   * related queue items that will be removed along with the archive AND how
   * many are currently printing (server 409s on delete if > 0).
   */
  getArchiveDeleteImpact: (id: number) =>
    request<{ related_queue_items: number; currently_printing: number }>(
      `/archives/${id}/delete-impact`
    ),
  searchArchives: (query: string, options?: {
    printerId?: number;
    projectId?: number;
    status?: string;
    limit?: number;
    offset?: number;
  }) => {
    const params = new URLSearchParams();
    params.set('q', query);
    if (options?.printerId) params.set('printer_id', String(options.printerId));
    if (options?.projectId) params.set('project_id', String(options.projectId));
    if (options?.status) params.set('status', options.status);
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.offset) params.set('offset', String(options.offset));
    return request<Archive[]>(`/archives/search?${params}`);
  },
  rebuildSearchIndex: () => request<{ message: string }>('/archives/search/rebuild-index', { method: 'POST' }),
  getNo3MFWarning: () =>
    request<{
      has_fallback: boolean;
      reason:
        | 'ftps_cooloff'
        | 'ftp_transfer_failed'
        | 'internal_storage'
        | 'no_external_storage'
        | 'internal_history'
        | null;
    }>(
      '/archives/no-3mf-warning',
    ),
  updateArchive: (id: number, data: {
    printer_id?: number | null;
    project_id?: number | null;
    print_name?: string;
    is_favorite?: boolean;
    tags?: string;
    notes?: string;
    cost?: number;
    failure_reason?: string | null;
    status?: string;
    quantity?: number;
    external_url?: string | null;
    filament_used_grams?: number | null;
    // Post-print outcome verdict (#1898); null clears it
    user_verdict?: 'good' | 'reject' | null;
    // Which surface answered. The backend only accepts the sources a client
    // can honestly claim and defaults to 'api' when none is given.
    user_verdict_source?: 'dialog' | 'printer_card';
  }) =>
    request<Archive>(`/archives/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  toggleFavorite: (id: number) =>
    request<Archive>(`/archives/${id}/favorite`, { method: 'POST' }),
  // Soft-deletes by default (#1343): files removed from disk, row hidden
  // from listings, but its filament / time / cost / energy contribution
  // stays in Quick Stats. Pass purgeStats=true to hard-delete and drop the
  // row from statistics too.
  deleteArchive: (id: number, purgeStats: boolean = false) =>
    request<void>(`/archives/${id}${purgeStats ? '?purge_stats=true' : ''}`, { method: 'DELETE' }),

  // ========== Archive auto-purge (#1008 follow-up) ==========
  previewArchivePurge: (olderThanDays: number, purgeStats: boolean = false) =>
    request<ArchivePurgePreview>(
      `/archives/purge/preview?older_than_days=${olderThanDays}&purge_stats=${purgeStats}`,
    ),
  // #1390: purgeStats=false (default) soft-deletes each old archive — Quick Stats
  // preserved, files removed from disk, row hidden via deleted_at. true matches
  // the single-archive delete's `?purge_stats=true` semantics (hard-deletes the
  // linked PrintLogEntry rows so the contribution drops from /stats too).
  executeArchivePurge: (olderThanDays: number, purgeStats: boolean = false) =>
    request<{ deleted: number; purge_stats: boolean }>('/archives/purge', {
      method: 'POST',
      body: JSON.stringify({ older_than_days: olderThanDays, purge_stats: purgeStats }),
    }),
  getArchivePurgeSettings: () =>
    request<ArchivePurgeSettings>('/archives/purge/settings'),
  updateArchivePurgeSettings: (body: ArchivePurgeSettings) =>
    request<ArchivePurgeSettings>('/archives/purge/settings', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  getArchiveStats: (options?: { dateFrom?: string; dateTo?: string; createdById?: number }) => {
    const params = new URLSearchParams();
    if (options?.dateFrom) params.set('date_from', options.dateFrom);
    if (options?.dateTo) params.set('date_to', options.dateTo);
    if (options?.createdById !== undefined) params.set('created_by_id', String(options.createdById));
    const qs = params.toString();
    return request<ArchiveStats>(`/archives/stats${qs ? `?${qs}` : ''}`);
  },
  // Tag management
  getTags: () => request<TagInfo[]>('/archives/tags'),
  renameTag: (oldName: string, newName: string) =>
    request<{ affected: number }>(`/archives/tags/${encodeURIComponent(oldName)}`, {
      method: 'PUT',
      body: JSON.stringify({ new_name: newName }),
    }),
  deleteTag: (name: string) =>
    request<{ affected: number }>(`/archives/tags/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),
  recalculateCosts: () =>
    request<{ message: string; updated: number }>('/archives/recalculate-costs', { method: 'POST' }),
  getFailureAnalysis: (options?: { days?: number; dateFrom?: string; dateTo?: string; printerId?: number; projectId?: number; createdById?: number }) => {
    const params = new URLSearchParams();
    if (options?.days) params.set('days', String(options.days));
    if (options?.dateFrom) params.set('date_from', options.dateFrom);
    if (options?.dateTo) params.set('date_to', options.dateTo);
    if (options?.printerId) params.set('printer_id', String(options.printerId));
    if (options?.projectId) params.set('project_id', String(options.projectId));
    if (options?.createdById !== undefined) params.set('created_by_id', String(options.createdById));
    const qs = params.toString();
    return request<FailureAnalysis>(`/archives/analysis/failures${qs ? `?${qs}` : ''}`);
  },
  compareArchives: (archiveIds: number[]) =>
    request<ArchiveComparison>(`/archives/compare?archive_ids=${archiveIds.join(',')}`),
  findSimilarArchives: (archiveId: number, limit = 10) =>
    request<SimilarArchive[]>(`/archives/${archiveId}/similar?limit=${limit}`),
  exportArchives: async (options?: {
    format?: 'csv' | 'xlsx';
    fields?: string[];
    printerId?: number;
    projectId?: number;
    status?: string;
    dateFrom?: string;
    dateTo?: string;
    search?: string;
  }): Promise<{ blob: Blob; filename: string }> => {
    const params = new URLSearchParams();
    if (options?.format) params.set('format', options.format);
    if (options?.fields) params.set('fields', options.fields.join(','));
    if (options?.printerId) params.set('printer_id', String(options.printerId));
    if (options?.projectId) params.set('project_id', String(options.projectId));
    if (options?.status) params.set('status', options.status);
    if (options?.dateFrom) params.set('date_from', options.dateFrom);
    if (options?.dateTo) params.set('date_to', options.dateTo);
    if (options?.search) params.set('search', options.search);

    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/export?${params}`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = options?.format === 'xlsx' ? 'archives_export.xlsx' : 'archives_export.csv';
    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    const blob = await response.blob();
    return { blob, filename };
  },
  exportStats: async (options?: {
    format?: 'csv' | 'xlsx';
    days?: number;
    printerId?: number;
    projectId?: number;
    createdById?: number;
  }): Promise<{ blob: Blob; filename: string }> => {
    const params = new URLSearchParams();
    if (options?.format) params.set('format', options.format);
    if (options?.days) params.set('days', String(options.days));
    if (options?.printerId) params.set('printer_id', String(options.printerId));
    if (options?.projectId) params.set('project_id', String(options.projectId));
    if (options?.createdById !== undefined) params.set('created_by_id', String(options.createdById));

    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/stats/export?${params}`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }

    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = options?.format === 'xlsx' ? 'stats_export.xlsx' : 'stats_export.csv';
    if (contentDisposition) {
      const match = contentDisposition.match(/filename="?([^"]+)"?/);
      if (match) filename = match[1];
    }

    const blob = await response.blob();
    return { blob, filename };
  },
  getArchiveDuplicates: (id: number) =>
    request<{ duplicates: ArchiveDuplicate[]; count: number }>(`/archives/${id}/duplicates`),
  backfillContentHashes: () =>
    request<{ updated: number; errors: Array<{ id: number; error: string }> }>('/archives/backfill-hashes', {
      method: 'POST',
    }),
  getArchiveThumbnail: (id: number) => withMediaToken(`${API_BASE}/archives/${id}/thumbnail?v=${Date.now()}`),
  getArchivePlateThumbnail: (id: number, plateIndex: number) =>
    withMediaToken(`${API_BASE}/archives/${id}/plate-thumbnail/${plateIndex}`),
  getArchiveDownload: (id: number) => `${API_BASE}/archives/${id}/download`,
  downloadArchive: async (id: number, filename?: string): Promise<void> => {
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${id}/download`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const disposition = response.headers.get('Content-Disposition');
    const downloadFilename = parseContentDispositionFilename(disposition) || filename || `archive_${id}.3mf`;
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
  getArchiveGcode: (id: number) => `${API_BASE}/archives/${id}/gcode`,
  getArchivePlatePreview: (id: number) => withMediaToken(`${API_BASE}/archives/${id}/plate-preview`),
  getArchiveTimelapse: (id: number) => withMediaToken(`${API_BASE}/archives/${id}/timelapse?v=${Date.now()}`),
  downloadArchiveTimelapse: async (id: number, filename: string): Promise<void> => {
    const prepared = await request<{ token: string; filename: string }>(
      `/archives/${id}/media-download-token`,
      { method: 'POST' },
    );
    const link = document.createElement('a');
    link.href = `${API_BASE}/archives/${id}/media/dl/${encodeURIComponent(prepared.token)}/${encodeURIComponent(filename)}`;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  },
  getArchivePrinterMedia: (id: number) =>
    request<ArchivePrinterMedia>(`/archives/${id}/printer-media`),
  scanArchiveTimelapse: (id: number) =>
    request<{
      status: string;
      message: string;
      filename?: string;
      available_files?: Array<{ name: string; path: string; size: number; mtime: string | null }>;
    }>(`/archives/${id}/timelapse/scan`, {
      method: 'POST',
    }),
  selectArchiveTimelapse: (id: number, filename: string) =>
    request<{ status: string; message: string; filename: string }>(
      `/archives/${id}/timelapse/select?filename=${encodeURIComponent(filename)}`,
      { method: 'POST' }
    ),
  deleteArchiveTimelapse: (id: number) =>
    request<{ status: string }>(`/archives/${id}/timelapse`, {
      method: 'DELETE',
    }),
  uploadArchiveTimelapse: async (archiveId: number, file: File): Promise<{ status: string; filename: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/timelapse/upload`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  // Timelapse Editor
  getTimelapseInfo: (archiveId: number) =>
    request<{
      duration: number;
      width: number;
      height: number;
      fps: number;
      codec: string;
      file_size: number;
      has_audio: boolean;
    }>(`/archives/${archiveId}/timelapse/info`),
  getTimelapseThumbnails: (archiveId: number, count: number = 10) =>
    request<{
      thumbnails: string[];
      timestamps: number[];
    }>(`/archives/${archiveId}/timelapse/thumbnails?count=${count}`),
  processTimelapse: async (
    archiveId: number,
    params: {
      trimStart?: number;
      trimEnd?: number;
      speed?: number;
      saveMode: 'replace' | 'new';
      outputFilename?: string;
    },
    audioFile?: File
  ): Promise<{ status: string; output_path: string | null; message: string }> => {
    const formData = new FormData();
    formData.append('trim_start', String(params.trimStart ?? 0));
    if (params.trimEnd !== undefined) {
      formData.append('trim_end', String(params.trimEnd));
    }
    formData.append('speed', String(params.speed ?? 1));
    formData.append('save_mode', params.saveMode);
    if (params.outputFilename) {
      formData.append('output_filename', params.outputFilename);
    }
    if (audioFile) {
      formData.append('audio', audioFile);
    }
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/timelapse/process`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  // Photos
  getArchivePhotoUrl: (archiveId: number, filename: string) =>
    withMediaToken(`${API_BASE}/archives/${archiveId}/photos/${encodeURIComponent(filename)}`),
  uploadArchivePhoto: async (archiveId: number, file: File): Promise<{ status: string; filename: string; photos: string[] }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/photos`, {
      headers,
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteArchivePhoto: (archiveId: number, filename: string) =>
    request<{ status: string; photos: string[] | null }>(`/archives/${archiveId}/photos/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    }),
  // Source 3MF (original slicer project file)
  getSource3mfDownloadUrl: (archiveId: number) =>
    `${API_BASE}/archives/${archiveId}/source`,
  downloadSource3mf: async (archiveId: number): Promise<void> => {
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/source`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const disposition = response.headers.get('Content-Disposition');
    const filename = parseContentDispositionFilename(disposition) || `source_${archiveId}.3mf`;
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
  getSource3mfForSlicer: (archiveId: number, filename: string) => {
    // Sanitize: slicers url_decode() the entire URL, so / \ ? # in filenames break path routing
    const safe = filename.replace(/[/\\?#]/g, '_');
    return `${API_BASE}/archives/${archiveId}/source/${encodeURIComponent(safe.endsWith('.3mf') ? safe : safe + '.3mf')}`;
  },
  createSourceSlicerToken: (archiveId: number) =>
    request<{ token: string }>(`/archives/${archiveId}/source-slicer-token`, { method: 'POST' }),
  getSourceSlicerDownloadUrl: (archiveId: number, token: string, filename: string) => {
    const safe = filename.replace(/[/\\?#]/g, '_');
    return `${API_BASE}/archives/${archiveId}/source-dl/${token}/${encodeURIComponent(safe.endsWith('.3mf') ? safe : safe + '.3mf')}`;
  },
  uploadSource3mf: async (archiveId: number, file: File): Promise<{ status: string; filename: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/source`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteSource3mf: (archiveId: number) =>
    request<{ status: string }>(`/archives/${archiveId}/source`, {
      method: 'DELETE',
    }),
  // F3D (Fusion 360 design file)
  getF3dDownloadUrl: (archiveId: number) =>
    `${API_BASE}/archives/${archiveId}/f3d`,
  downloadF3d: async (archiveId: number): Promise<void> => {
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/f3d`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const disposition = response.headers.get('Content-Disposition');
    const filename = parseContentDispositionFilename(disposition) || `archive_${archiveId}.f3d`;
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
  uploadF3d: async (archiveId: number, file: File): Promise<{ status: string; filename: string }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/archives/${archiveId}/f3d`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteF3d: (archiveId: number) =>
    request<{ status: string }>(`/archives/${archiveId}/f3d`, {
      method: 'DELETE',
    }),

  // QR Code
  getArchiveQRCodeUrl: (archiveId: number, size = 200) =>
    withMediaToken(`${API_BASE}/archives/${archiveId}/qrcode?size=${size}`),
  getArchiveCapabilities: (id: number) =>
    request<{
      has_model: boolean;
      has_gcode: boolean;
      has_source: boolean;
      build_volume: { x: number; y: number; z: number };
      filament_colors: string[];
    }>(`/archives/${id}/capabilities`),
  // Project Page
  getArchiveProjectPage: (id: number) =>
    request<{
      title: string | null;
      description: string | null;
      designer: string | null;
      designer_user_id: string | null;
      license: string | null;
      copyright: string | null;
      creation_date: string | null;
      modification_date: string | null;
      origin: string | null;
      profile_title: string | null;
      profile_description: string | null;
      profile_cover: string | null;
      profile_user_id: string | null;
      profile_user_name: string | null;
      design_model_id: string | null;
      design_profile_id: string | null;
      design_region: string | null;
      model_pictures: Array<{ name: string; path: string; url: string }>;
      profile_pictures: Array<{ name: string; path: string; url: string }>;
      thumbnails: Array<{ name: string; path: string; url: string }>;
    }>(`/archives/${id}/project-page`),
  updateArchiveProjectPage: (id: number, data: {
    title?: string;
    description?: string;
    designer?: string;
    license?: string;
    copyright?: string;
    profile_title?: string;
    profile_description?: string;
  }) =>
    request(`/archives/${id}/project-page`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  getArchiveProjectImageUrl: (archiveId: number, imagePath: string) =>
    withMediaToken(`${API_BASE}/archives/${archiveId}/project-image/${encodeURIComponent(imagePath)}`),
  getArchiveForSlicer: (id: number, filename: string) => {
    const safe = filename.replace(/[/\\?#]/g, '_');
    return `${API_BASE}/archives/${id}/file/${encodeURIComponent(safe.endsWith('.3mf') ? safe : safe + '.3mf')}`;
  },
  createArchiveSlicerToken: (archiveId: number) =>
    request<{ token: string }>(`/archives/${archiveId}/slicer-token`, { method: 'POST' }),
  getArchiveSlicerDownloadUrl: (archiveId: number, token: string, filename: string) => {
    const safe = filename.replace(/[/\\?#]/g, '_');
    return `${API_BASE}/archives/${archiveId}/dl/${token}/${encodeURIComponent(safe.endsWith('.3mf') ? safe : safe + '.3mf')}`;
  },
  getArchivePlates: (archiveId: number) =>
    request<ArchivePlatesResponse>(`/archives/${archiveId}/plates`),
  getArchiveFilamentRequirements: (
    archiveId: number,
    plateId?: number,
    requestId?: string,
    /** Ask for one entry per project slot instead of only the slots this
     * plate consumes. The slice modal needs it: its filament list is
     * positional, so a source whose only used slot is 4 must still present
     * four rows or the user's pick is bound to slot 1 (#2712). Print-time
     * AMS matching must NOT set this — it wants the used-only list. */
    fullSlots?: boolean,
  ) => {
    const qs = new URLSearchParams();
    if (plateId !== undefined) qs.set('plate_id', String(plateId));
    if (requestId) qs.set('request_id', requestId);
    if (fullSlots) qs.set('full_slots', 'true');
    return request<{
      archive_id: number;
      filename: string;
      plate_id: number | null;
      filaments: Array<{
        slot_id: number;
        type: string;
        color: string;
        used_grams: number;
        used_meters: number;
        used_in_plate?: boolean;
      }>;
    }>(`/archives/${archiveId}/filament-requirements${qs.toString() ? `?${qs}` : ''}`);
  },
  uploadArchive: async (file: File, printerId?: number): Promise<Archive> => {
    const formData = new FormData();
    formData.append('file', file);
    const url = printerId
      ? `${API_BASE}/archives/upload?printer_id=${printerId}`
      : `${API_BASE}/archives/upload`;
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  uploadArchivesBulk: async (files: File[], printerId?: number): Promise<BulkUploadResult> => {
    const formData = new FormData();
    files.forEach((file) => formData.append('files', file));
    const url = printerId
      ? `${API_BASE}/archives/upload-bulk?printer_id=${printerId}`
      : `${API_BASE}/archives/upload-bulk`;
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },

  // Print Log
  getPrintLog: (params?: {
    search?: string;
    printerId?: number;
    username?: string;
    status?: string;
    dateFrom?: string;
    dateTo?: string;
    limit?: number;
    offset?: number;
    // Sorting is server-side because paging is: ordering only the rows the
    // client holds would sort one page, not the log (#2636).
    sortBy?: string;
    sortDir?: 'asc' | 'desc';
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.search) searchParams.set('search', params.search);
    if (params?.printerId) searchParams.set('printer_id', String(params.printerId));
    if (params?.username) searchParams.set('created_by_username', params.username);
    if (params?.status) searchParams.set('status', params.status);
    if (params?.dateFrom) searchParams.set('date_from', params.dateFrom);
    if (params?.dateTo) searchParams.set('date_to', params.dateTo);
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.offset !== undefined) searchParams.set('offset', String(params.offset));
    if (params?.sortBy) searchParams.set('sort_by', params.sortBy);
    if (params?.sortDir) searchParams.set('sort_dir', params.sortDir);
    return request<PrintLogResponse>(`/print-log/?${searchParams}`);
  },
  getPrintLogThumbnail: (id: number) => withMediaToken(`${API_BASE}/print-log/${id}/thumbnail`),
  clearPrintLog: () =>
    request<{ deleted: number }>('/print-log/', { method: 'DELETE' }),
  deletePrintLogEntry: (id: number) =>
    request<{ status: string; id: number }>(`/print-log/${id}`, { method: 'DELETE' }),
  // Edit failure_reason / status on a single Print Log row (#1687 part 4).
  // Distinct from updateArchive: archives describe the model, log entries
  // describe a single print event. Orphan entries (no archive_id) have no
  // archive to reach through and this is the only path to classify them.
  updatePrintLogEntry: (
    id: number,
    body: { failure_reason?: string | null; status?: string },
  ) =>
    request<PrintLogEntry>(`/print-log/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  // Settings
  getSettings: () => request<AppSettings>('/settings/'),
  getDefaultSidebarOrder: () => request<{ default_sidebar_order: string }>('/settings/default-sidebar-order'),
  // Public subset of settings for UI rendering — no settings:read required.
  // Used by pages whose users may not have SETTINGS_READ (e.g. operators with
  // only printers:clear_plate). Keep in sync with _UI_PREFERENCE_FIELDS in
  // backend/app/api/routes/settings.py.
  getUiPreferences: () =>
    request<{
      require_plate_clear?: boolean;
      check_printer_firmware?: boolean;
      camera_view_mode?: 'window' | 'embedded';
      time_format?: 'system' | '12h' | '24h';
      date_format?: string;
      drying_presets?: string;
      ams_humidity_thresholds?: string;
      ams_humidity_good?: number;
      ams_humidity_fair?: number;
      ams_temp_good?: number;
      ams_temp_fair?: number;
      bed_cooled_threshold?: number;
      nozzle_temp_presets?: string;
      bed_temp_presets?: string;
      chamber_temp_presets?: string;
      fan_speed_presets?: string;
    }>('/settings/ui-preferences'),
  // Install configuration the app shell needs, for any signed-in user. Separate
  // from getUiPreferences: that endpoint is public because its fields are
  // defaults shipped with the app, while these describe how this deployment is
  // configured. Neither requires settings:read -- which is the point, since a
  // non-admin reading GET /settings gets a 403 and every gate that consults it
  // silently takes its fallback (#3023). Keep in sync with _UI_FLAG_FIELDS in
  // backend/app/api/routes/settings.py.
  getUiFlags: () =>
    request<{
      billing_enabled?: boolean;
      user_notifications_enabled?: boolean;
      currency?: string;
      check_updates?: boolean;
    }>('/settings/ui-flags'),
  updateSettings: (data: AppSettingsUpdate) =>
    request<AppSettings>('/settings/', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  getMQTTStatus: () => request<MQTTStatus>('/settings/mqtt/status'),
  resetSettings: () =>
    request<AppSettings>('/settings/reset', { method: 'POST' }),
  exportBackup: async (): Promise<{ blob: Blob; filename: string }> => {
    // New simplified backup - complete database + all files
    const url = `${API_BASE}/settings/backup`;
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(url, { headers });

    // Check for errors
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(errorText || `Backup failed with status ${response.status}`);
    }

    // Get filename from Content-Disposition header
    const contentDisposition = response.headers.get('Content-Disposition');
    let filename = 'printlab-backup.zip';
    if (contentDisposition) {
      const match = contentDisposition.match(/filename=([^;]+)/);
      if (match) filename = match[1].trim().replace(/^"(.*)"$/, '$1');
    }

    const blob = await response.blob();
    return { blob, filename };
  },
  importBackup: async (file: File) => {
    // New simplified restore - replaces database + all directories
    const formData = new FormData();
    formData.append('file', file);
    const url = `${API_BASE}/settings/restore`;
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: formData,
    });
    const data = (await response.json().catch(() => null)) as {
      success?: boolean;
      message?: string;
      detail?: string;
    } | null;
    // A refused restore is an HTTPException, so the body is {detail}, not
    // {success, message}. Returning it unmapped made `success` undefined and
    // `message` undefined too — the modal then raised an empty error toast,
    // which is the one case where the reason matters most (e.g. a backup this
    // version cannot import names the columns and both versions).
    if (!response.ok) {
      return { success: false, message: data?.detail ?? data?.message ?? '' };
    }
    return (data ?? { success: false, message: '' }) as {
      success: boolean;
      message: string;
    };
  },
  checkFfmpeg: () =>
    request<{ installed: boolean; path: string | null }>('/settings/check-ffmpeg'),
  getNetworkInterfaces: () =>
    request<{ interfaces: NetworkInterface[] }>('/settings/network-interfaces'),

  // Cloud
  getCloudStatus: () => request<CloudAuthStatus>('/cloud/status'),
  cloudLogin: (email: string, password: string, region = 'global') =>
    request<CloudLoginResponse>('/cloud/login', {
      method: 'POST',
      body: JSON.stringify({ email, password, region }),
    }),
  cloudVerify: (email: string, code: string, tfaKey?: string, region: string = 'global') =>
    request<CloudLoginResponse>('/cloud/verify', {
      method: 'POST',
      body: JSON.stringify({ email, code, tfa_key: tfaKey, region }),
    }),
  cloudSetToken: (access_token: string, region: string = 'global') =>
    request<CloudAuthStatus>('/cloud/token', {
      method: 'POST',
      body: JSON.stringify({ access_token, region }),
    }),
  cloudLogout: () =>
    request<{ success: boolean }>('/cloud/logout', { method: 'POST' }),

  // Orca Cloud — RFC 8628 device pairing. deviceStart() returns a short
  // user_code + verification link; the user approves it in their Orca Cloud
  // settings while the frontend polls devicePoll() every `interval` seconds
  // until the status flips to 'complete' (or a terminal deny/expire).
  orcaCloudDeviceStart: () =>
    request<OrcaDeviceStartResponse>('/orca-cloud/device/start', {
      method: 'POST',
    }),
  orcaCloudDevicePoll: () =>
    request<OrcaDevicePollResponse>('/orca-cloud/device/poll', {
      method: 'POST',
    }),
  orcaCloudStatus: () =>
    request<OrcaAuthStatusResponse>('/orca-cloud/status'),
  orcaCloudLogout: () =>
    request<{ success: boolean }>('/orca-cloud/logout', { method: 'POST' }),
  orcaCloudListProfiles: () =>
    request<OrcaProfileListResponse>('/orca-cloud/profiles'),
  orcaCloudGetProfile: (id: string) =>
    request<OrcaProfileDetail>(`/orca-cloud/profiles/${id}`),
  getCloudSettings: (version = '02.04.00.70') =>
    request<SlicerSettingsResponse>(`/cloud/settings?version=${version}`),
  getBuiltinFilaments: () =>
    request<BuiltinFilament[]>('/cloud/builtin-filaments'),
  getFilamentIdMap: () =>
    request<Record<string, string>>('/cloud/filament-id-map'),

  /** Material-disambiguated hex→name lookup. Same hex can map to different
   *  catalog names depending on material (e.g. #000000 is "Charcoal" in PLA
   *  Matte but "Black" in PLA Basic). The flat ``/inventory/colors/map``
   *  collapses these to the first hit; this endpoint preserves the material
   *  context. Returns ``{color_name: null}`` when the hex isn't in the
   *  catalog at all. #1718. */
  getColorByMaterial: (hex: string, material?: string) => {
    const params = new URLSearchParams({ hex });
    if (material) params.set('material', material);
    return request<{ color_name: string | null }>(
      `/inventory/colors/by-material?${params.toString()}`,
    );
  },

  // MakerWorld URL-paste import flow.
  getMakerworldStatus: () =>
    request<MakerworldStatus>('/makerworld/status'),
  resolveMakerworldUrl: (url: string) =>
    request<MakerworldResolvedModel>('/makerworld/resolve', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  getMakerworldRecentImports: (limit = 10) =>
    request<MakerworldRecentImport[]>(`/makerworld/recent-imports?limit=${limit}`),
  importMakerworldInstance: (
    model_id: number,
    instance_id: number | null,
    profile_id?: number | null,
    folder_id?: number | null,
  ) =>
    request<MakerworldImportResponse>('/makerworld/import', {
      method: 'POST',
      body: JSON.stringify({
        model_id,
        instance_id: instance_id ?? null,
        profile_id: profile_id ?? null,
        folder_id: folder_id ?? null,
      }),
    }),
  getCloudSettingDetail: (settingId: string) =>
    request<SlicerSettingDetail>(`/cloud/settings/${settingId}`),
  createCloudSetting: (data: SlicerSettingCreate) =>
    request<SlicerSettingDetail>('/cloud/settings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateCloudSetting: (settingId: string, data: SlicerSettingUpdate) =>
    request<SlicerSettingDetail>(`/cloud/settings/${settingId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteCloudSetting: (settingId: string) =>
    request<SlicerSettingDeleteResponse>(`/cloud/settings/${settingId}`, {
      method: 'DELETE',
    }),
  getCloudDevices: () => request<CloudDevice[]>('/cloud/devices'),
  getCloudFields: (presetType: 'filament' | 'print' | 'process' | 'printer') =>
    request<FieldDefinitionsResponse>(`/cloud/fields/${presetType}`),
  getAllCloudFields: () =>
    request<Record<string, FieldDefinitionsResponse>>('/cloud/fields'),
  getFilamentInfo: (settingIds: string[]) =>
    request<Record<string, { name: string; k: number | null }>>('/cloud/filament-info', {
      method: 'POST',
      body: JSON.stringify(settingIds),
    }),

  // Smart Plugs
  getSmartPlugs: () => request<SmartPlug[]>('/smart-plugs/'),
  getSmartPlug: (id: number) => request<SmartPlug>(`/smart-plugs/${id}`),
  getSmartPlugByPrinter: (printerId: number) => request<SmartPlug | null>(`/smart-plugs/by-printer/${printerId}`),
  getScriptPlugsByPrinter: (printerId: number) => request<SmartPlug[]>(`/smart-plugs/by-printer/${printerId}/scripts`),
  createSmartPlug: (data: SmartPlugCreate) =>
    request<SmartPlug>('/smart-plugs/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateSmartPlug: (id: number, data: SmartPlugUpdate) =>
    request<SmartPlug>(`/smart-plugs/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteSmartPlug: (id: number) =>
    request<void>(`/smart-plugs/${id}`, { method: 'DELETE' }),
  controlSmartPlug: (id: number, action: 'on' | 'off' | 'toggle') =>
    request<{ success: boolean; action: string }>(`/smart-plugs/${id}/control`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    }),
  getSmartPlugStatus: (id: number) =>
    request<SmartPlugStatus>(`/smart-plugs/${id}/status`),
  testSmartPlugConnection: (ip_address: string, username?: string | null, password?: string | null) =>
    request<SmartPlugTestResult>('/smart-plugs/test-connection', {
      method: 'POST',
      body: JSON.stringify({ ip_address, username, password }),
    }),

  // Tasmota Discovery (auto-detects network)
  startTasmotaScan: () =>
    request<TasmotaScanStatus>('/smart-plugs/discover/scan', { method: 'POST' }),
  getTasmotaScanStatus: () =>
    request<TasmotaScanStatus>('/smart-plugs/discover/status'),
  stopTasmotaScan: () =>
    request<TasmotaScanStatus>('/smart-plugs/discover/stop', { method: 'POST' }),
  getDiscoveredTasmotaDevices: () =>
    request<DiscoveredTasmotaDevice[]>('/smart-plugs/discover/devices'),

  // Home Assistant Integration
  testHAConnection: (url: string, token: string) =>
    request<HATestConnectionResult>('/smart-plugs/ha/test-connection', {
      method: 'POST',
      body: JSON.stringify({ url, token }),
    }),
  getHAEntities: (search?: string) => {
    const params = search ? `?search=${encodeURIComponent(search)}` : '';
    return request<HAEntity[]>(`/smart-plugs/ha/entities${params}`);
  },
  getHASensorEntities: () =>
    request<HASensorEntity[]>('/smart-plugs/ha/sensors'),

  // Home Assistant sensors bound to a printer (#1148, #448)
  getHASensors: (printerId?: number) =>
    request<PrinterHASensor[]>(`/ha-sensors/${printerId ? `?printer_id=${printerId}` : ''}`),
  getHASensorReadings: (printerId: number) =>
    request<PrinterHASensorReading[]>(`/ha-sensors/by-printer/${printerId}/readings`),
  getBindableHAEntities: (search?: string) => {
    const params = search ? `?search=${encodeURIComponent(search)}` : '';
    return request<HADisplayEntity[]>(`/ha-sensors/entities${params}`);
  },
  createHASensor: (data: PrinterHASensorCreate) =>
    request<PrinterHASensor>('/ha-sensors/', { method: 'POST', body: JSON.stringify(data) }),
  updateHASensor: (id: number, data: PrinterHASensorUpdate) =>
    request<PrinterHASensor>(`/ha-sensors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteHASensor: (id: number) =>
    request<{ message: string }>(`/ha-sensors/${id}`, { method: 'DELETE' }),

  getLocationHASensors: (locationId?: number) =>
    request<LocationHASensor[]>(`/location-ha-sensors/${locationId ? `?location_id=${locationId}` : ''}`),
  getLocationHASensorReadings: (locationId: number, showOnCard = true) =>
    request<LocationHASensorReading[]>(
      `/location-ha-sensors/by-location/${locationId}/readings?show_on_card=${showOnCard}`
    ),
  getBindableLocationHAEntities: (search?: string) => {
    const params = search ? `?search=${encodeURIComponent(search)}` : '';
    return request<HADisplayEntity[]>(`/location-ha-sensors/entities${params}`);
  },
  createLocationHASensor: (data: LocationHASensorCreate) =>
    request<LocationHASensor>('/location-ha-sensors/', { method: 'POST', body: JSON.stringify(data) }),
  updateLocationHASensor: (id: number, data: LocationHASensorUpdate) =>
    request<LocationHASensor>(`/location-ha-sensors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteLocationHASensor: (id: number) =>
    request<{ message: string }>(`/location-ha-sensors/${id}`, { method: 'DELETE' }),

  // REST smart plug
  testRESTConnection: (url: string, method: string = 'GET', headers?: string | null) =>
    request<{ success: boolean; error: string | null }>('/smart-plugs/rest/test-connection', {
      method: 'POST',
      body: JSON.stringify({ url, method, headers }),
    }),

  // Print Queue
  getQueue: (printerId?: number, status?: string, targetModel?: string) => {
    const params = new URLSearchParams();
    if (printerId) params.set('printer_id', String(printerId));
    if (status) params.set('status', status);
    if (targetModel) params.set('target_model', targetModel);
    return request<PrintQueueItem[]>(`/queue/?${params}`);
  },
  getQueueItem: (id: number) => request<PrintQueueItem>(`/queue/${id}`),
  addToQueue: (data: PrintQueueItemCreate) =>
    request<PrintQueueItem>('/queue/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateQueueItem: (id: number, data: PrintQueueItemUpdate) =>
    request<PrintQueueItem>(`/queue/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  /** `deleted` is false when the item was kept as cancelled instead: it is the
   *  last run a batch order could re-queue its plate from (#2960). */
  removeFromQueue: (id: number) =>
    request<{ message: string; deleted: boolean }>(`/queue/${id}`, { method: 'DELETE' }),
  reorderQueue: (items: { id: number; position: number }[]) =>
    request<{ message: string }>('/queue/reorder', {
      method: 'POST',
      body: JSON.stringify({ items }),
    }),
  cancelQueueItem: (id: number) =>
    request<{ message: string }>(`/queue/${id}/cancel`, { method: 'POST' }),
  stopQueueItem: (id: number) =>
    request<{ message: string }>(`/queue/${id}/stop`, { method: 'POST' }),
  /**
   * Start a staged queue item. The backend re-checks live filament deficit
   * for the assigned spool and, when short, returns 409 with a structured
   * payload so the caller can confirm and retry. Pass `skipFilamentCheck`
   * after the user confirms "Print Anyway" (#1496).
   */
  startQueueItem: (id: number, opts?: { skipFilamentCheck?: boolean }) => {
    const qs = opts?.skipFilamentCheck ? '?skip_filament_check=true' : '';
    return request<PrintQueueItem>(`/queue/${id}/start${qs}`, { method: 'POST' });
  },
  /**
   * Clear the `require_previous_success` gate for a printer after the user
   * resolves the failure. Acknowledges any failed/aborted predecessors and
   * restores skipped items whose error_message matches the gate string
   * back to pending. Returns counts so the UI can render a precise toast.
   */
  resumeQueueAfterFailure: (printerId: number) =>
    request<{ acknowledged: number; restored: number }>(
      `/queue/printer/${printerId}/resume`,
      { method: 'POST' },
    ),
  bulkUpdateQueue: (data: PrintQueueBulkUpdate) =>
    request<PrintQueueBulkUpdateResponse>('/queue/bulk', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  // Batches
  getBatches: (status?: string) => {
    const params = status ? `?status=${status}` : '';
    return request<PrintBatch[]>(`/queue/batches${params}`);
  },
  getBatch: (id: number) => request<PrintBatch>(`/queue/batches/${id}`),
  cancelBatch: (id: number) =>
    request<{ message: string }>(`/queue/batches/${id}`, { method: 'DELETE' }),
  createBatch: (data: PrintBatchCreate) =>
    request<PrintBatch>('/queue/batches', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateBatch: (id: number, data: PrintBatchUpdate) =>
    request<PrintBatch>(`/queue/batches/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  dispatchBatch: (id: number, data: PrintBatchDispatchRequest = {}) =>
    request<PrintBatch>(`/queue/batches/${id}/dispatch`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  ungroupBatch: (id: number) =>
    request<{ ungrouped_count: number; message: string }>(
      `/queue/batches/${id}/ungroup`,
      { method: 'POST' },
    ),

  // K-Profiles
  getKProfiles: (printerId: number, nozzleDiameter = '0.4') =>
    request<KProfilesResponse>(`/printers/${printerId}/kprofiles/?nozzle_diameter=${nozzleDiameter}`),
  setKProfile: (printerId: number, profile: KProfileCreate) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/kprofiles/`, {
      method: 'POST',
      body: JSON.stringify(profile),
    }),
  deleteKProfile: (printerId: number, profile: KProfileDelete) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/kprofiles/`, {
      method: 'DELETE',
      body: JSON.stringify(profile),
    }),
  setKProfilesBatch: (printerId: number, profiles: KProfileCreate[]) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/kprofiles/batch`, {
      method: 'POST',
      body: JSON.stringify(profiles),
    }),

  // Finance
  getMyBalance: () => request<WalletBalance>('/finance/me/balance'),
  getMyTransactions: (limit = 50, offset = 0) =>
    request<WalletTransactionListResponse>(`/finance/me/transactions?limit=${limit}&offset=${offset}`),
  getAllTransactions: (limit = 50, offset = 0, userId?: number) => {
    const params = new URLSearchParams();
    params.set('limit', String(limit));
    params.set('offset', String(offset));
    if (userId !== undefined) params.set('user_id', String(userId));
    return request<WalletTransactionListResponse>(`/finance/transactions?${params.toString()}`);
  },
  deleteTransaction: (transactionId: number) =>
    request<{ status: string }>(`/finance/transactions/${transactionId}`, {
      method: 'DELETE',
    }),
  editTransaction: (transactionId: number, data: TransactionEditRequest) =>
    request<WalletTransaction>(`/finance/transactions/${transactionId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  createManualPrint: (data: ManualPrintRequest) =>
    request<WalletTransaction>('/finance/transactions/manual', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getMyCostCenters: () => request<CostCenterSummary[]>('/finance/cost-centers/mine'),
  listCostCenters: (includeInactive = false) =>
    request<CostCenterSummary[]>(`/finance/cost-centers?include_inactive=${includeInactive ? 'true' : 'false'}`),
  createCostCenter: (data: CostCenterCreateRequest) =>
    request<CostCenterSummary>('/finance/cost-centers', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateCostCenter: (costCenterId: number, data: CostCenterUpdateRequest) =>
    request<CostCenterSummary>(`/finance/cost-centers/${costCenterId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  updateCostCenterBudgets: (costCenterId: number, data: CostCenterBudgetUpdateRequest) =>
    request<CostCenterSummary>(`/finance/cost-centers/${costCenterId}/budgets`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteCostCenter: (costCenterId: number) =>
    request<{ status: string }>(`/finance/cost-centers/${costCenterId}`, {
      method: 'DELETE',
    }),
  getCostCenter: (costCenterId: number) =>
    request<CostCenterDetail>(`/finance/cost-centers/${costCenterId}`),
  upsertCostCenterMember: (costCenterId: number, data: CostCenterMemberRequest) =>
    request<CostCenterMemberResponse>(`/finance/cost-centers/${costCenterId}/members`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  removeCostCenterMember: (costCenterId: number, userId: number) =>
    request<{ status: string }>(`/finance/cost-centers/${costCenterId}/members/${userId}`, {
      method: 'DELETE',
    }),
  depositUserBalance: (userId: number, data: WalletAdjustmentRequest) =>
    request<WalletAdjustmentResponse>(`/finance/users/${userId}/deposit`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  withdrawUserBalance: (userId: number, data: WalletAdjustmentRequest) =>
    request<WalletAdjustmentResponse>(`/finance/users/${userId}/withdraw`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  rebuildBalanceLedger: () =>
    request<{ status: string }>('/finance/rebuild-balance-ledger', {
      method: 'POST',
    }),

  // K-Profile Notes (stored locally, not on printer)
  getKProfileNotes: (printerId: number) =>
    request<KProfileNotesResponse>(`/printers/${printerId}/kprofiles/notes`),
  setKProfileNote: (printerId: number, settingId: string, note: string) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/kprofiles/notes`, {
      method: 'PUT',
      body: JSON.stringify({ setting_id: settingId, note }),
    }),
  deleteKProfileNote: (printerId: number, settingId: string) =>
    request<{ success: boolean; message: string }>(`/printers/${printerId}/kprofiles/notes/${encodeURIComponent(settingId)}`, {
      method: 'DELETE',
    }),

  // Slot Preset Mappings
  getSlotPresets: (printerId: number) =>
    request<Record<number, SlotPresetMapping>>(`/printers/${printerId}/slot-presets`),
  getSlotPreset: (printerId: number, amsId: number, trayId: number) =>
    request<SlotPresetMapping | null>(`/printers/${printerId}/slot-presets/${amsId}/${trayId}`),
  saveSlotPreset: (printerId: number, amsId: number, trayId: number, presetId: string, presetName: string, presetSource = 'cloud', trayInfoIdx?: string) =>
    request<SlotPresetMapping>(`/printers/${printerId}/slot-presets/${amsId}/${trayId}?preset_id=${encodeURIComponent(presetId)}&preset_name=${encodeURIComponent(presetName)}&preset_source=${encodeURIComponent(presetSource)}${trayInfoIdx ? `&tray_info_idx=${encodeURIComponent(trayInfoIdx)}` : ''}`, {
      method: 'PUT',
    }),
  deleteSlotPreset: (printerId: number, amsId: number, trayId: number) =>
    request<{ success: boolean }>(`/printers/${printerId}/slot-presets/${amsId}/${trayId}`, {
      method: 'DELETE',
    }),

  // AMS Labels (user-defined friendly names)
  getAmsLabels: (printerId: number) =>
    request<Record<number, string>>(`/printers/${printerId}/ams-labels`),
  saveAmsLabel: (printerId: number, amsId: number, label: string, amsSerial = '') =>
    request<{ ams_id: number; label: string }>(
      `/printers/${printerId}/ams-labels/${amsId}`,
      {
        method: 'PUT',
        body: JSON.stringify({ label, ams_serial: amsSerial }),
      }
    ),
  deleteAmsLabel: (printerId: number, amsId: number, amsSerial = '') =>
    request<{ success: boolean }>(`/printers/${printerId}/ams-labels/${amsId}?ams_serial=${encodeURIComponent(amsSerial)}`, {
      method: 'DELETE',
    }),

  configureAmsSlot: (
    printerId: number,
    amsId: number,
    trayId: number,
    config: {
      tray_info_idx: string;
      tray_type: string;
      tray_sub_brands: string;
      tray_color: string;
      nozzle_temp_min: number;
      nozzle_temp_max: number;
      cali_idx: number;
      nozzle_diameter: string;
      setting_id?: string;
      kprofile_filament_id?: string;
      kprofile_setting_id?: string;
      k_value?: number;
      // Orca Cloud profile the slot is set to; the backend looks up its
      // filament id when tray_info_idx is empty (#3216).
      orca_profile_id?: string;
    }
  ) => {
    const params = new URLSearchParams({
      tray_info_idx: config.tray_info_idx,
      tray_type: config.tray_type,
      tray_sub_brands: config.tray_sub_brands,
      tray_color: config.tray_color,
      nozzle_temp_min: config.nozzle_temp_min.toString(),
      nozzle_temp_max: config.nozzle_temp_max.toString(),
      cali_idx: config.cali_idx.toString(),
      nozzle_diameter: config.nozzle_diameter,
    });
    if (config.setting_id) {
      params.set('setting_id', config.setting_id);
    }
    if (config.kprofile_filament_id) {
      params.set('kprofile_filament_id', config.kprofile_filament_id);
    }
    if (config.kprofile_setting_id) {
      params.set('kprofile_setting_id', config.kprofile_setting_id);
    }
    if (config.k_value !== undefined && config.k_value > 0) {
      params.set('k_value', config.k_value.toString());
    }
    if (config.orca_profile_id) {
      params.set('orca_profile_id', config.orca_profile_id);
    }
    return request<{
      success: boolean;
      message: string;
      // The filament id the slot was actually given.
      tray_info_idx?: string;
      // Why an Orca profile went out as the generic for its material, or "".
      orca_fallback_reason?: '' | 'no_filament_id' | 'lookup_failed' | 'no_permission';
    }>(
      `/printers/${printerId}/slots/${amsId}/${trayId}/configure?${params}`,
      { method: 'POST' }
    );
  },
  resetAmsSlot: (printerId: number, amsId: number, trayId: number) =>
    request<{ success: boolean; message: string }>(
      `/printers/${printerId}/ams/${amsId}/tray/${trayId}/reset`,
      { method: 'POST' }
    ),

  // Filament Catalog (material types with cost/temp data)
  listFilaments: () => request<Filament[]>('/filament-catalog/'),
  getFilament: (id: number) => request<Filament>(`/filament-catalog/${id}`),
  getFilamentsByType: (type: string) => request<Filament[]>(`/filament-catalog/by-type/${type}`),

  // Notification Providers
  getNotificationProviders: () => request<NotificationProvider[]>('/notifications/'),
  getNotificationProvider: (id: number) => request<NotificationProvider>(`/notifications/${id}`),
  createNotificationProvider: (data: NotificationProviderCreate) =>
    request<NotificationProvider>('/notifications/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateNotificationProvider: (id: number, data: NotificationProviderUpdate) =>
    request<NotificationProvider>(`/notifications/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteNotificationProvider: (id: number) =>
    request<{ message: string }>(`/notifications/${id}`, { method: 'DELETE' }),
  testNotificationProvider: (id: number) =>
    request<NotificationTestResponse>(`/notifications/${id}/test`, { method: 'POST' }),
  testNotificationConfig: (data: NotificationTestRequest) =>
    request<NotificationTestResponse>('/notifications/test-config', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  testAllNotificationProviders: () =>
    request<{
      tested: number;
      success: number;
      failed: number;
      results: Array<{
        provider_id: number;
        provider_name: string;
        provider_type: string;
        success: boolean;
        message: string;
      }>;
    }>('/notifications/test-all', { method: 'POST' }),

  // Notification Templates
  getNotificationTemplates: () => request<NotificationTemplate[]>('/notification-templates'),
  getNotificationTemplate: (id: number) => request<NotificationTemplate>(`/notification-templates/${id}`),
  updateNotificationTemplate: (id: number, data: NotificationTemplateUpdate) =>
    request<NotificationTemplate>(`/notification-templates/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  resetNotificationTemplate: (id: number) =>
    request<NotificationTemplate>(`/notification-templates/${id}/reset`, {
      method: 'POST',
    }),
  getTemplateVariables: () => request<EventVariablesResponse[]>('/notification-templates/variables'),
  previewTemplate: (data: TemplatePreviewRequest) =>
    request<TemplatePreviewResponse>('/notification-templates/preview', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Notification Logs
  getNotificationLogs: (params?: {
    limit?: number;
    offset?: number;
    provider_id?: number;
    event_type?: string;
    success?: boolean;
    days?: number;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.limit) searchParams.set('limit', String(params.limit));
    if (params?.offset) searchParams.set('offset', String(params.offset));
    if (params?.provider_id) searchParams.set('provider_id', String(params.provider_id));
    if (params?.event_type) searchParams.set('event_type', params.event_type);
    if (params?.success !== undefined) searchParams.set('success', String(params.success));
    if (params?.days) searchParams.set('days', String(params.days));
    return request<NotificationLogEntry[]>(`/notifications/logs?${searchParams}`);
  },
  getNotificationLogStats: (days = 7) =>
    request<NotificationLogStats>(`/notifications/logs/stats?days=${days}`),
  clearNotificationLogs: (olderThanDays = 30) =>
    request<{ deleted: number; message: string }>(
      `/notifications/logs?older_than_days=${olderThanDays}`,
      { method: 'DELETE' }
    ),

  // Spoolman Integration
  getSpoolmanStatus: () => request<SpoolmanStatus>('/spoolman/status'),
  connectSpoolman: () =>
    request<{ success: boolean; message: string }>('/spoolman/connect', {
      method: 'POST',
    }),
  disconnectSpoolman: () =>
    request<{ success: boolean; message: string }>('/spoolman/disconnect', {
      method: 'POST',
    }),
  syncPrinterAms: (printerId: number) =>
    request<SpoolmanSyncResult>(`/spoolman/sync/${printerId}`, {
      method: 'POST',
    }),
  syncAllPrintersAms: () =>
    request<SpoolmanSyncResult>('/spoolman/sync-all', {
      method: 'POST',
    }),
  getSpoolmanSpools: () =>
    request<{ spools: unknown[] }>('/spoolman/spools'),
  /** @deprecated Use getSpoolmanInventoryFilaments() — this endpoint has no SSRF guard */
  getSpoolmanFilaments: () =>
    request<{ filaments: unknown[] }>('/spoolman/filaments'),
  getSpoolmanInventoryFilaments: () =>
    request<SpoolmanFilamentEntry[]>('/spoolman/inventory/filaments'),
  patchSpoolmanFilament: (
    filamentId: number,
    data: { name?: string; spool_weight?: number | null; keep_existing_spools?: boolean },
  ) =>
    request<SpoolmanFilamentEntry>(`/spoolman/inventory/filaments/${filamentId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  getUnlinkedSpools: () =>
    request<UnlinkedSpool[]>('/spoolman/spools/unlinked'),
  getLinkedSpools: () =>
    request<LinkedSpoolsMap>('/spoolman/spools/linked'),
  linkSpool: (
    spoolId: number,
    context: {
      spoolTag: string;
      printerId: number;
      amsId: number;
      trayId: number;
    }
  ) =>
    request<{ success: boolean; message: string }>(`/spoolman/spools/${spoolId}/link`, {
      method: 'POST',
      body: JSON.stringify({
        spool_tag: context.spoolTag,
        printer_id: context.printerId,
        ams_id: context.amsId,
        tray_id: context.trayId,
      }),
    }),
  unlinkSpool: (spoolId: number) =>
    request<{ success: boolean; message: string }>(`/spoolman/spools/${spoolId}/unlink`, {
      method: 'POST',
    }),
  createSpoolmanSpoolFromSlot: (data: { printer_id: number; ams_id: number; tray_id: number }) =>
    request<{ success: boolean; spool_id: number | null }>(`/spoolman/spools/from-slot`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  createSpoolFromSlot: (data: { printer_id: number; ams_id: number; tray_id: number }) =>
    request<InventorySpool>(`/inventory/spools/from-slot`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getSpoolmanSettings: () =>
    request<{ spoolman_enabled: string; spoolman_url: string; spoolman_sync_mode: string; spoolman_disable_weight_sync: string; spoolman_report_partial_usage: string; auto_add_unknown_rfid: string; }>('/settings/spoolman'),
  updateSpoolmanSettings: (data: { spoolman_enabled?: string; spoolman_url?: string; spoolman_sync_mode?: string; spoolman_disable_weight_sync?: string; spoolman_report_partial_usage?: string; auto_add_unknown_rfid?: string; }) =>
    request<{ spoolman_enabled: string; spoolman_url: string; spoolman_sync_mode: string; spoolman_disable_weight_sync: string; spoolman_report_partial_usage: string; auto_add_unknown_rfid: string; }>('/settings/spoolman', {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Inventory
  getSpools: (includeArchived = false) =>
    request<InventorySpool[]>(`/inventory/spools?include_archived=${includeArchived}`),
  getSpool: (id: number) => request<InventorySpool>(`/inventory/spools/${id}`),
  createSpool: (data: Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>) =>
    request<InventorySpool>('/inventory/spools', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  bulkCreateSpools: (data: Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>, quantity: number) =>
    request<InventorySpool[]>('/inventory/spools/bulk', {
      method: 'POST',
      body: JSON.stringify({ spool: data, quantity }),
    }),
  // ── CSV import/export (#1576) ────────────────────────────────────────────
  // dry_run=true → preview (no write); omitted → real import. Both share one
  // multipart upload helper; see `uploadSpoolsCsv` below.
  importSpoolsCsvPreview: (file: File): Promise<CsvImportPreview> => uploadSpoolsCsv<CsvImportPreview>(file, true),
  importSpoolsCsv: (file: File): Promise<CsvImportResult> => uploadSpoolsCsv<CsvImportResult>(file, false),
  exportSpoolsCsv: async (): Promise<void> => {
    const headers: Record<string, string> = {};
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    const response = await fetch(`${API_BASE}/inventory/spools/export`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const disposition = response.headers.get('Content-Disposition');
    const filename = parseContentDispositionFilename(disposition) || 'printlab_inventory.csv';
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
  updateSpool: (id: number, data: Partial<Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>>) =>
    request<InventorySpool>(`/inventory/spools/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteSpool: (id: number) =>
    request<{ status: string }>(`/inventory/spools/${id}`, { method: 'DELETE' }),
  archiveSpool: (id: number) =>
    request<InventorySpool>(`/inventory/spools/${id}/archive`, { method: 'POST' }),
  restoreSpool: (id: number) =>
    request<InventorySpool>(`/inventory/spools/${id}/restore`, { method: 'POST' }),
  resetSpoolConsumedCounter: (id: number) =>
    request<InventorySpool>(`/inventory/spools/${id}/reset-consumed-counter`, { method: 'POST' }),
  bulkResetSpoolConsumedCounter: (spoolIds: number[]) =>
    request<{ reset: number }>(`/inventory/spools/reset-consumed-counter-bulk`, {
      method: 'POST',
      body: JSON.stringify({ spool_ids: spoolIds }),
    }),
  bulkUpdateSpools: (ids: number[], update: Partial<Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>>) =>
    request<{ updated: number; not_found: number[] }>(`/inventory/spools/bulk-update`, {
      method: 'POST',
      body: JSON.stringify({ ids, update }),
    }),
  bulkDeleteSpools: (ids: number[]) =>
    request<{ deleted: number; not_found: number[] }>(`/inventory/spools/bulk-delete`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  bulkArchiveSpools: (ids: number[]) =>
    request<{ archived: number; already_archived: number[]; not_found: number[] }>(`/inventory/spools/bulk-archive`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  bulkRestoreSpools: (ids: number[]) =>
    request<{ restored: number; already_active: number[]; not_found: number[] }>(`/inventory/spools/bulk-restore`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  getSpoolKProfiles: (spoolId: number) =>
    request<SpoolKProfile[]>(`/inventory/spools/${spoolId}/k-profiles`),
  saveSpoolKProfiles: (spoolId: number, profiles: SpoolKProfileInput[]) =>
    request<SpoolKProfile[]>(`/inventory/spools/${spoolId}/k-profiles`, {
      method: 'PUT',
      body: JSON.stringify(profiles),
    }),
  /**
   * What the spool assigned to this slot is configured to use *here* -- its
   * per-printer-model filament preset and the K profile for this slot's hotend.
   * Nulls when the slot holds no known spool.
   */
  getSlotSpoolDefaults: (printerId: number, amsId: number, trayId: number) =>
    request<SlotSpoolDefaults>(`/printers/${printerId}/slots/${amsId}/${trayId}/spool-defaults`),
  getSpoolFilamentPresets: (spoolId: number) =>
    request<SpoolFilamentPreset[]>(`/inventory/spools/${spoolId}/filament-presets`),
  saveSpoolFilamentPresets: (spoolId: number, presets: SpoolFilamentPresetInput[]) =>
    request<SpoolFilamentPreset[]>(`/inventory/spools/${spoolId}/filament-presets`, {
      method: 'PUT',
      body: JSON.stringify(presets),
    }),
  getAssignments: (printerId?: number) =>
    request<SpoolAssignment[]>(`/inventory/assignments${printerId ? `?printer_id=${printerId}` : ''}`),
  assignSpool: (data: { spool_id: number; printer_id: number; ams_id: number; tray_id: number }) =>
    request<SpoolAssignment>('/inventory/assignments', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  unassignSpool: (printerId: number, amsId: number, trayId: number) =>
    request<{ status: string }>(`/inventory/assignments/${printerId}/${amsId}/${trayId}`, { method: 'DELETE' }),
  // ── Spool label printing (#809) ──────────────────────────────────────────
  // The print endpoints return a PDF, a PNG, or a ZIP of PNGs (#2981); the
  // preview endpoints one PNG. Callers get the Blob and decide what to do.
  printSpoolLabels: (data: PrintSpoolLabelsRequest): Promise<Blob> =>
    postForBlob('/inventory/labels', data),
  printSpoolmanSpoolLabels: (data: PrintSpoolLabelsRequest): Promise<Blob> =>
    postForBlob('/spoolman/labels', data),
  previewSpoolLabel: (data: PreviewSpoolLabelRequest, signal?: AbortSignal): Promise<Blob> =>
    postForBlob('/inventory/labels/preview', data, signal),
  previewSpoolmanSpoolLabel: (data: PreviewSpoolLabelRequest, signal?: AbortSignal): Promise<Blob> =>
    postForBlob('/spoolman/labels/preview', data, signal),
  getSpoolCatalog: () =>
    request<SpoolCatalogEntry[]>('/inventory/catalog'),
  addCatalogEntry: (data: { name: string; weight: number }) =>
    request<SpoolCatalogEntry>('/inventory/catalog', { method: 'POST', body: JSON.stringify(data) }),
  updateCatalogEntry: (id: number, data: { name: string; weight: number }) =>
    request<SpoolCatalogEntry>(`/inventory/catalog/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteCatalogEntry: (id: number) =>
    request<{ status: string }>(`/inventory/catalog/${id}`, { method: 'DELETE' }),
  bulkDeleteCatalogEntries: (ids: number[]) =>
    request<{ deleted: number }>('/inventory/catalog/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  resetSpoolCatalog: () =>
    request<{ status: string }>('/inventory/catalog/reset', { method: 'POST' }),
  // ── Suppliers (#2988) — inventory master data, Locations pattern ─────────
  getSuppliers: () =>
    request<Supplier[]>('/inventory/suppliers'),
  createSupplier: (data: SupplierInput) =>
    request<Supplier>('/inventory/suppliers', { method: 'POST', body: JSON.stringify(data) }),
  updateSupplier: (id: number, data: Partial<SupplierInput>) =>
    request<Supplier>(`/inventory/suppliers/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSupplier: (id: number) =>
    request<{ status: string }>(`/inventory/suppliers/${id}`, { method: 'DELETE' }),
  setSpoolSuppliers: (spoolId: number, links: SpoolSupplierLinkInput[]) =>
    request<SpoolSupplierLink[]>(`/inventory/spools/${spoolId}/suppliers`, {
      method: 'PUT',
      body: JSON.stringify(links),
    }),
  // Spoolman parity: the assignment rows live PrintLab-side, keyed by the
  // remote spool id — same request/response shape as the built-in inventory.
  setSpoolmanSpoolSuppliers: (spoolmanSpoolId: number, links: SpoolSupplierLinkInput[]) =>
    request<SpoolSupplierLink[]>(`/spoolman/inventory/spools/${spoolmanSpoolId}/suppliers`, {
      method: 'PUT',
      body: JSON.stringify(links),
    }),
  // date_from/date_to scope the usage half only, so the widget can follow the
  // dashboard timeframe; stock stays point-in-time.
  getSupplierStats: (dateFrom?: string, dateTo?: string) => {
    const params = new URLSearchParams();
    if (dateFrom) params.set('date_from', dateFrom);
    if (dateTo) params.set('date_to', dateTo);
    const qs = params.toString();
    return request<SupplierStats[]>(`/inventory/stats/suppliers${qs ? `?${qs}` : ''}`);
  },
  getLocations: () =>
    request<StorageLocation[]>('/inventory/locations'),
  createLocation: (data: { name: string; identifier?: string | null }) =>
    request<StorageLocation>('/inventory/locations', { method: 'POST', body: JSON.stringify(data) }),
  updateLocation: (id: number, data: { name?: string; identifier?: string | null }) =>
    request<StorageLocation>(`/inventory/locations/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteLocation: (id: number) =>
    request<{ status: string }>(`/inventory/locations/${id}`, { method: 'DELETE' }),
  getColorCatalog: () =>
    request<ColorCatalogEntry[]>('/inventory/colors'),
  /** Flat hex→name map, plus the names collapsing it loses. ``by_material`` is
   *  keyed ``"<material>|<hex>"`` and only carries entries that differ from the
   *  flat answer (e.g. ``"pla matte|ffffff" -> "Ivory White"`` where the flat
   *  map says "Jade White"). #2875. */
  getColorNameMap: () =>
    request<{ colors: Record<string, string>; by_material?: Record<string, string> }>('/inventory/colors/map'),
  addColorEntry: (data: {
    manufacturer: string;
    color_name: string;
    hex_color: string;
    material: string | null;
    extra_colors?: string | null;
    effect_type?: string | null;
  }) =>
    request<ColorCatalogEntry>('/inventory/colors', { method: 'POST', body: JSON.stringify(data) }),
  updateColorEntry: (
    id: number,
    data: {
      manufacturer: string;
      color_name: string;
      hex_color: string;
      material: string | null;
      extra_colors?: string | null;
      effect_type?: string | null;
    },
  ) => request<ColorCatalogEntry>(`/inventory/colors/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteColorEntry: (id: number) =>
    request<{ status: string }>(`/inventory/colors/${id}`, { method: 'DELETE' }),
  bulkDeleteColorEntries: (ids: number[]) =>
    request<{ deleted: number }>('/inventory/colors/bulk-delete', { method: 'POST', body: JSON.stringify({ ids }) }),
  resetColorCatalog: () =>
    request<{ status: string }>('/inventory/colors/reset', { method: 'POST' }),
  lookupColor: (manufacturer: string, colorName: string, material?: string) =>
    request<ColorLookupResult>(`/inventory/colors/lookup?manufacturer=${encodeURIComponent(manufacturer)}&color_name=${encodeURIComponent(colorName)}${material ? `&material=${encodeURIComponent(material)}` : ''}`),
  searchColors: (manufacturer?: string, material?: string) =>
    request<ColorCatalogEntry[]>(`/inventory/colors/search?${manufacturer ? `manufacturer=${encodeURIComponent(manufacturer)}` : ''}${manufacturer && material ? '&' : ''}${material ? `material=${encodeURIComponent(material)}` : ''}`),
  linkTagToSpool: (spoolId: number, data: { tag_uid?: string; tray_uuid?: string; tag_type?: string; data_origin?: string }) =>
    request<InventorySpool>(`/inventory/spools/${spoolId}/link-tag`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  // Per-material-number inventory aggregate (#2870). The date range narrows
  // the usage half only — stock is point-in-time.
  getMaterialNumberStats: (options?: { dateFrom?: string; dateTo?: string }) => {
    const params = new URLSearchParams();
    if (options?.dateFrom) params.set('date_from', options.dateFrom);
    if (options?.dateTo) params.set('date_to', options.dateTo);
    const qs = params.toString();
    return request<MaterialNumberStats[]>(`/inventory/stats/material-numbers${qs ? `?${qs}` : ''}`);
  },
  getSpoolUsageHistory: (spoolId: number, limit = 50) =>
    request<SpoolUsageRecord[]>(`/inventory/spools/${spoolId}/usage?limit=${limit}`),
  getAllUsageHistory: (limit = 100, printerId?: number) =>
    request<SpoolUsageRecord[]>(`/inventory/usage?limit=${limit}${printerId ? `&printer_id=${printerId}` : ''}`),
  clearSpoolUsageHistory: (spoolId: number) =>
    request<{ status: string }>(`/inventory/spools/${spoolId}/usage`, { method: 'DELETE' }),
  syncWeightsFromAms: () =>
    request<{ synced: number; skipped: number }>('/inventory/sync-ams-weights', { method: 'POST' }),
  getSkuSettings: () =>
    request<FilamentSkuSettings[]>('/inventory/sku-settings'),
  upsertSkuSettings: (data: Omit<FilamentSkuSettings, 'id'>) =>
    request<FilamentSkuSettings>('/inventory/sku-settings', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  getShoppingList: () =>
    request<ShoppingListItem[]>('/inventory/shopping-list'),
  addToShoppingList: (data: ShoppingListItemCreate) =>
    request<ShoppingListItem>('/inventory/shopping-list', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  removeFromShoppingList: (id: number) =>
    request<{ status: string }>(`/inventory/shopping-list/${id}`, { method: 'DELETE' }),
  clearShoppingList: () =>
    request<{ deleted: number }>('/inventory/shopping-list', { method: 'DELETE' }),
  updateShoppingListStatus: (id: number, status: 'pending' | 'purchased' | 'received') =>
    request<ShoppingListItem>(`/inventory/shopping-list/${id}/status`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    }),
  getFilamentPresets: () =>
    request<SlicerSetting[]>('/cloud/filaments'),

  // Spoolman Inventory proxy (unified UI when Spoolman is enabled)
  getSpoolmanInventorySpools: (includeArchived = false) =>
    request<InventorySpool[]>(`/spoolman/inventory/spools?include_archived=${includeArchived}`),
  getSpoolmanInventorySpool: (id: number) =>
    request<InventorySpool>(`/spoolman/inventory/spools/${id}`),
  createSpoolmanInventorySpool: (data: Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>) =>
    request<InventorySpool>('/spoolman/inventory/spools', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  bulkCreateSpoolmanInventorySpools: (
    data: Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>,
    quantity: number,
  ) =>
    request<SpoolmanBulkCreateResult | InventorySpool[]>('/spoolman/inventory/spools/bulk', {
      method: 'POST',
      body: JSON.stringify({ spool: data, quantity }),
    }),
  updateSpoolmanInventorySpool: (
    id: number,
    data: Partial<Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>>,
  ) =>
    request<InventorySpool>(`/spoolman/inventory/spools/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteSpoolmanInventorySpool: (id: number) =>
    request<{ status: string }>(`/spoolman/inventory/spools/${id}`, { method: 'DELETE' }),
  archiveSpoolmanInventorySpool: (id: number) =>
    request<InventorySpool>(`/spoolman/inventory/spools/${id}/archive`, { method: 'POST' }),
  restoreSpoolmanInventorySpool: (id: number) =>
    request<InventorySpool>(`/spoolman/inventory/spools/${id}/restore`, { method: 'POST' }),
  resetSpoolmanInventorySpoolConsumedCounter: (id: number) =>
    request<InventorySpool>(`/spoolman/inventory/spools/${id}/reset-consumed-counter`, { method: 'POST' }),
  bulkResetSpoolmanInventorySpoolConsumedCounter: (spoolIds: number[]) =>
    request<{ reset: number }>(`/spoolman/inventory/spools/reset-consumed-counter-bulk`, {
      method: 'POST',
      body: JSON.stringify({ spool_ids: spoolIds }),
    }),
  bulkUpdateSpoolmanInventorySpools: (ids: number[], update: Partial<Omit<InventorySpool, 'id' | 'archived_at' | 'created_at' | 'updated_at' | 'k_profiles'>>) =>
    request<{ updated: number; errors: Array<{ id: number; status: number; detail: string }> }>(`/spoolman/inventory/spools/bulk-update`, {
      method: 'POST',
      body: JSON.stringify({ ids, update }),
    }),
  bulkDeleteSpoolmanInventorySpools: (ids: number[]) =>
    request<{ deleted: number; errors: Array<{ id: number; status: number; detail: string }> }>(`/spoolman/inventory/spools/bulk-delete`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  bulkArchiveSpoolmanInventorySpools: (ids: number[]) =>
    request<{ archived: number; errors: Array<{ id: number; status: number; detail: string }> }>(`/spoolman/inventory/spools/bulk-archive`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  bulkRestoreSpoolmanInventorySpools: (ids: number[]) =>
    request<{ restored: number; errors: Array<{ id: number; status: number; detail: string }> }>(`/spoolman/inventory/spools/bulk-restore`, {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  linkTagToSpoolmanSpool: (spoolId: number, data: { tag_uid?: string; tray_uuid?: string }) =>
    request<InventorySpool>(`/spoolman/inventory/spools/${spoolId}/tag`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  syncSpoolmanSpoolWeight: (spoolId: number, weightGrams: number) =>
    request<{ status: string; weight_used: number }>(`/spoolman/inventory/spools/${spoolId}/weight`, {
      method: 'PATCH',
      body: JSON.stringify({ weight_grams: weightGrams }),
    }),
  assignSpoolmanSlot: (data: { spoolman_spool_id: number; printer_id: number; ams_id: number; tray_id: number }) =>
    request<InventorySpool>('/spoolman/inventory/slot-assignments', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  unassignSpoolmanSlot: (spoolmanSpoolId: number) =>
    request<InventorySpool>(`/spoolman/inventory/slot-assignments/${spoolmanSpoolId}`, { method: 'DELETE' }),
  getSpoolmanSlotAssignment: (printerId: number, amsId: number, trayId: number) =>
    request<InventorySpool | null>(
      `/spoolman/inventory/slot-assignments?printer_id=${printerId}&ams_id=${amsId}&tray_id=${trayId}`,
    ),
  getSpoolmanSlotAssignments: (printerId?: number) =>
    request<Array<{
      printer_id: number;
      printer_name: string | null;
      ams_id: number;
      tray_id: number;
      spoolman_spool_id: number;
      ams_label: string | null;
    }>>(
      printerId !== undefined
        ? `/spoolman/inventory/slot-assignments/all?printer_id=${printerId}`
        : '/spoolman/inventory/slot-assignments/all',
    ),
  syncSpoolmanAmsWeights: () =>
    request<{ synced: number; skipped: number }>('/spoolman/inventory/sync-ams-weights', { method: 'POST' }),

  getSpoolmanKProfiles: (spoolId: number) =>
    request<SpoolKProfile[]>(`/spoolman/inventory/spools/${spoolId}/k-profiles`),

  saveSpoolmanKProfiles: (spoolId: number, profiles: SpoolKProfileInput[]) =>
    request<SpoolKProfile[]>(`/spoolman/inventory/spools/${spoolId}/k-profiles`, {
      method: 'PUT',
      body: JSON.stringify(profiles),
    }),

  getSpoolmanFilamentPresets: (spoolId: number) =>
    request<SpoolFilamentPreset[]>(`/spoolman/inventory/spools/${spoolId}/filament-presets`),

  saveSpoolmanFilamentPresets: (spoolId: number, presets: SpoolFilamentPresetInput[]) =>
    request<SpoolFilamentPreset[]>(`/spoolman/inventory/spools/${spoolId}/filament-presets`, {
      method: 'PUT',
      body: JSON.stringify(presets),
    }),

  // Updates
  getVersion: () => request<VersionInfo>('/updates/version'),
  checkForUpdates: () => request<UpdateCheckResult>('/updates/check'),
  applyUpdate: () =>
    request<{ success: boolean; message: string; status?: UpdateStatus; is_docker?: boolean; is_ha_addon?: boolean; is_windows_installer?: boolean }>('/updates/apply', {
      method: 'POST',
    }),
  getUpdateStatus: () => request<UpdateStatus>('/updates/status'),
  // Maintenance
  getMaintenanceTypes: () => request<MaintenanceType[]>('/maintenance/types'),
  createMaintenanceType: (data: MaintenanceTypeCreate) =>
    request<MaintenanceType>('/maintenance/types', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateMaintenanceType: (id: number, data: Partial<MaintenanceTypeCreate>) =>
    request<MaintenanceType>(`/maintenance/types/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteMaintenanceType: (id: number) =>
    request<{ status: string }>(`/maintenance/types/${id}`, { method: 'DELETE' }),
  restoreDefaultMaintenanceTypes: () =>
    request<{ restored: number }>(`/maintenance/types/restore-defaults`, { method: 'POST' }),
  getMaintenanceOverview: () => request<PrinterMaintenanceOverview[]>('/maintenance/overview'),
  getPrinterMaintenance: (printerId: number) =>
    request<PrinterMaintenanceOverview>(`/maintenance/printers/${printerId}`),
  updateMaintenanceItem: (itemId: number, data: { custom_interval_hours?: number | null; custom_interval_type?: 'hours' | 'days' | null; enabled?: boolean }) =>
    request<MaintenanceStatus>(`/maintenance/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  performMaintenance: (itemId: number, notes?: string) =>
    request<MaintenanceStatus>(`/maintenance/items/${itemId}/perform`, {
      method: 'POST',
      body: JSON.stringify({ notes }),
    }),
  getMaintenanceHistory: (itemId: number) =>
    request<MaintenanceHistory[]>(`/maintenance/items/${itemId}/history`),
  getMaintenanceSummary: () => request<MaintenanceSummary>('/maintenance/summary'),
  setPrinterHours: (printerId: number, totalHours: number) =>
    request<{ printer_id: number; total_hours: number; archive_hours: number; offset_hours: number }>(
      `/maintenance/printers/${printerId}/hours?total_hours=${totalHours}`,
      { method: 'PATCH' }
    ),
  assignMaintenanceType: (printerId: number, typeId: number) =>
    request<MaintenanceStatus>(`/maintenance/printers/${printerId}/assign/${typeId}`, {
      method: 'POST',
    }),
  removeMaintenanceItem: (itemId: number) =>
    request<{ status: string }>(`/maintenance/items/${itemId}`, {
      method: 'DELETE',
    }),

  // Maintenance programs (Bambu-Monitor port): oil / threaded rods
  getMaintenanceProgramStatus: (printerId: number) =>
    request<MaintenanceProgramStatus>(`/printers/${printerId}/maintenance-programs`),
  startMaintenanceProgram: (printerId: number, program: MaintenanceProgram, runs?: number, platteFrei = false) =>
    request<MaintenanceProgramStartResponse>(
      `/printers/${printerId}/maintenance-programs/${program}/start?platte_frei=${platteFrei ? 1 : 0}${runs != null ? `&runs=${runs}` : ''}`,
      { method: 'POST' }
    ),
  stopMaintenanceProgram: (printerId: number) =>
    request<MaintenanceProgramStartResponse>(`/printers/${printerId}/maintenance-programs/stop`, {
      method: 'POST',
    }),

  // Hardware extension: door + plate changer
  getHardwareStatus: (printerId: number) =>
    request<HardwareStatus>(`/printers/${printerId}/hardware`),
  openHardwareDoor: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/door/open`, { method: 'POST' }),
  closeHardwareDoor: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/door/close`, { method: 'POST' }),
  checkDoorStatus: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/door/status`, { method: 'POST' }),
  changeHardwarePlate: (printerId: number, job?: string) =>
    request<HardwareActionResponse>(
      `/printers/${printerId}/hardware/plate/change${job ? `?job=${encodeURIComponent(job)}` : ''}`,
      { method: 'POST' }
    ),
  refillHardwareMagazine: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/magazine/refill`, { method: 'POST' }),
  emergencyStopHardware: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/emergency-stop`, { method: 'POST' }),
  resetEmergencyStop: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/emergency-stop/reset`, { method: 'POST' }),
  resolveIncompleteChange: (printerId: number) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/incomplete/resolve`, { method: 'POST' }),
  cancelAutoPlateChange: (printerId: number) =>
    request<{ success: boolean; cancelled: number }>(`/printers/${printerId}/hardware/auto-plate-change/cancel`, {
      method: 'POST',
    }),
  updateAutoPlateChange: (printerId: number, payload: Partial<AutoPlateChange>) =>
    request<{ auto_plate_change: AutoPlateChange }>(`/printers/${printerId}/hardware/auto-plate-change`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  setMagazineSlots: (printerId: number, slots: PartialHardwareSlot[]) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/magazine`, {
      method: 'PUT',
      body: JSON.stringify({ slots }),
    }),
  getHardwareAuditLog: (printerId: number, limit = 20) =>
    request<AuditEntry[]>(`/printers/${printerId}/hardware/audit-log?limit=${limit}`),
  getHardwareConfig: (printerId: number) =>
    request<HardwareConfig>(`/printers/${printerId}/hardware/config`),
  setHardwareConfig: (printerId: number, payload: Partial<HardwareConfig>) =>
    request<HardwareActionResponse>(`/printers/${printerId}/hardware/config`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  getBedEmptyCheck: (printerId: number) =>
    request<BedEmptyCheckStatus>(`/printers/${printerId}/bed-empty-check`),
  setBedEmptyCheck: (printerId: number, payload: { enabled: boolean; threshold: number }) =>
    request<BedEmptyCheckStatus>(`/printers/${printerId}/bed-empty-check`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),
  captureBedReference: (printerId: number) =>
    request<{ saved: boolean; reference: string }>(`/printers/${printerId}/bed-empty-check/reference`, {
      method: 'POST',
    }),
  getSpaghettiCheck: (printerId: number) =>
    request<SpaghettiCheckStatus>(`/printers/${printerId}/spaghetti-check`),
  setSpaghettiCheck: (printerId: number, payload: { enabled: boolean; max_components: number; min_changed_percent: number }) =>
    request<SpaghettiCheckStatus>(`/printers/${printerId}/spaghetti-check`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    }),

  // Maintenance print (movement-only 3MF, Bambu-Monitor port)
  queueMaintenancePrint: (printerId: number, program: 'oil' | 'rods'): Promise<MaintenancePrintResponse & { library_file_id?: number; queue_item_id?: number }> =>
    request<MaintenancePrintResponse>(`/printers/${printerId}/maintenance-print/${program}?queue=true`, {
      method: 'POST',
    }),
  downloadMaintenancePrint: async (printerId: number, program: 'oil' | 'rods'): Promise<MaintenancePrintResponse> => {
    const created = await request<MaintenancePrintResponse>(
      `/printers/${printerId}/maintenance-print/${program}`,
      { method: 'POST' }
    );
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(created.download_url, { headers });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = created.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
    return created;
  },

  // Layer alert (pause at target layer)
  getLayerAlert: (printerId: number) =>
    request<LayerAlertStatus>(`/printers/${printerId}/layer-alert`),
  setLayerAlert: (printerId: number, data: { enabled: boolean; layer: number }) =>
    request<LayerAlertStatus>(`/printers/${printerId}/layer-alert`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // Part watcher (camera comparison)
  getPartWatcher: (printerId: number) =>
    request<PartWatcherStatus>(`/printers/${printerId}/part-watcher`),
  setPartWatcher: (printerId: number, data: { enabled: boolean; threshold?: number; overrides?: PartWatcherOverride[] }) =>
    request<PartWatcherStatus>(`/printers/${printerId}/part-watcher`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),

  // First-layer inspector
  getFirstLayerInspector: (printerId: number) =>
    request<FirstLayerStatus>(`/printers/${printerId}/first-layer-inspector`),
  setFirstLayerInspector: (printerId: number, enabled: boolean, pause_on_warning?: boolean) =>
    request<FirstLayerStatus>(`/printers/${printerId}/first-layer-inspector`, {
      method: 'PUT',
      body: JSON.stringify(pause_on_warning === undefined ? { enabled } : { enabled, pause_on_warning }),
    }),

  // Camera
  getCameraStreamToken: () =>
    request<{ token: string }>('/printers/camera/stream-token', { method: 'POST' }),

  // Media token (#3025) — the credential for thumbnails, plate previews,
  // timelapses, cover images and link icons. Minted behind plain auth rather
  // than camera:view, and identified, so those routes gate on the resource's
  // own permission and ownership instead of on the camera.
  getMediaToken: () => request<{ token: string }>('/auth/media-token', { method: 'POST' }),

  // WebSocket auth (GHSA-r2qv follow-up) — mint a short-lived token for
  // the /ws connection. Browsers can't attach Authorization headers to a
  // WebSocket handshake, so the token rides in the ?token= query param.
  getWebSocketToken: () =>
    request<{ token: string }>('/auth/ws-token', { method: 'POST' }),

  // Connected apps: sign-in to external applications with PrintLab
  listConnectedApps: () => request<ConnectedApp[]>('/connect/apps'),
  createConnectedApp: (payload: { name: string; redirect_uri: string }) =>
    request<ConnectedApp>('/connect/apps', { method: 'POST', body: JSON.stringify(payload) }),
  updateConnectedApp: (id: number, payload: { name?: string; redirect_uri?: string; enabled?: boolean }) =>
    request<ConnectedApp>(`/connect/apps/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  rotateConnectedAppSecret: (id: number) =>
    request<ConnectedApp>(`/connect/apps/${id}/rotate-secret`, { method: 'POST' }),
  deleteConnectedApp: (id: number) => request<void>(`/connect/apps/${id}`, { method: 'DELETE' }),
  getConnectAuthorizeInfo: (clientId: string, redirectUri: string) =>
    request<ConnectAuthorizeInfo>(
      `/connect/authorize/info?client_id=${encodeURIComponent(clientId)}&redirect_uri=${encodeURIComponent(redirectUri)}`,
    ),
  connectAuthorize: (payload: {
    client_id: string;
    redirect_uri: string;
    code_challenge: string;
    code_challenge_method: 'S256';
  }) =>
    request<{ code: string; redirect_uri: string }>('/connect/authorize', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Long-lived camera tokens (#1108, #2531)
  createLongLivedCameraToken: (payload: {
    name: string;
    expires_in_days: number;
    scope?: LongLivedTokenScope;
  }) =>
    request<LongLivedCameraToken>('/auth/tokens', {
      method: 'POST',
      body: JSON.stringify({ scope: 'camera_stream', ...payload }),
    }),
  listMyLongLivedCameraTokens: () =>
    request<LongLivedCameraToken[]>('/auth/tokens'),
  listAllLongLivedCameraTokens: () =>
    request<LongLivedCameraToken[]>('/auth/tokens/all'),
  listLongLivedCameraTokensForUser: (userId: number) =>
    request<LongLivedCameraToken[]>(`/auth/tokens?user_id=${userId}`),
  revokeLongLivedCameraToken: (tokenId: number) =>
    request<void>(`/auth/tokens/${tokenId}`, { method: 'DELETE' }),
  // Token-authenticated Cam Wall feed (#2531). `token` is omitted only when
  // auth is disabled, where the backend gate is a no-op anyway.
  getCamWallPrinters: (token?: string) =>
    request<CamWallPrinter[]>(
      token ? `/camwall/printers?token=${encodeURIComponent(token)}` : '/camwall/printers',
    ),
  // Token-authenticated streaming-overlay feed (#2613). OBS (or any embed with
  // no login session) loads /overlay/{id}?token=... and this backs it. `token`
  // is omitted only when auth is disabled, where the backend gate is a no-op.
  getOverlayStatus: (printerId: number, token?: string) =>
    request<OverlayStatus>(
      token
        ? `/printers/${printerId}/overlay-status?token=${encodeURIComponent(token)}`
        : `/printers/${printerId}/overlay-status`,
    ),
  getCameraStreamUrl: (printerId: number, fps = 10) =>
    withStreamToken(`${API_BASE}/printers/${printerId}/camera/stream?fps=${fps}`),
  getCameraSnapshotUrl: (printerId: number) =>
    withStreamToken(`${API_BASE}/printers/${printerId}/camera/snapshot`),
  getPlateCalibration: (printerId: number) =>
    request<PlateCalibrationStatus>(`/printers/${printerId}/plate-calibration`),
  setPlateCalibration: (printerId: number, points: Array<[number, number]>) =>
    request<PlateCalibrationStatus>(`/printers/${printerId}/plate-calibration`, {
      method: 'PUT',
      body: JSON.stringify({ points }),
    }),
  clearPlateCalibration: (printerId: number) =>
    request<PlateCalibrationStatus>(`/printers/${printerId}/plate-calibration`, { method: 'DELETE' }),
  getPlateCalibrationPreviewUrl: (printerId: number) =>
    withStreamToken(`${API_BASE}/printers/${printerId}/plate-calibration/preview`),
  getQuote: (params: {
    grams: number;
    duration_minutes: number;
    labor_minutes?: number;
    filament_cost_per_kg?: number;
    currency?: string;
  }) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) query.set(key, String(value));
    });
    return request<QuoteResponse>(`/quote?${query.toString()}`);
  },
  getQuoteForArchive: (archiveId: number, laborMinutes = 0) =>
    request<QuoteResponse & { archive_id: number; grams: number; duration_minutes: number }>(
      `/quote/for-archive/${archiveId}?labor_minutes=${laborMinutes}`
    ),
  getQuoteHistory: (customer?: string) =>
    request<{ entries: QuoteHistoryEntry[]; customers: QuoteCustomerTotal[] }>(
      `/quote/history${customer ? `?customer=${encodeURIComponent(customer)}` : ''}`
    ),
  saveQuote: (payload: Record<string, unknown>) =>
    request<QuoteHistoryEntry>('/quote/history', { method: 'POST', body: JSON.stringify(payload) }),
  deleteQuote: (id: string) => request<{ success: boolean }>(`/quote/history/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  getPriceList: () => request<{ entries: PriceListEntry[] }>('/quote/price-list'),
  setPriceList: (entries: PriceListEntry[]) =>
    request<{ entries: PriceListEntry[] }>('/quote/price-list', {
      method: 'PUT',
      body: JSON.stringify(entries),
    }),
  testCameraConnection: (printerId: number) =>
    request<{ success: boolean; message?: string; error?: string }>(`/printers/${printerId}/camera/test`),
  getCameraStatus: (printerId: number) =>
    request<{ active: boolean; stalled: boolean }>(`/printers/${printerId}/camera/status`),
  diagnoseCamera: (printerId: number) =>
    request<CameraDiagnoseResult>(`/printers/${printerId}/camera/diagnose`, { method: 'POST' }),
  diagnosePrinter: (printerId: number) =>
    request<PrinterDiagnosticResult>(`/printers/${printerId}/diagnostic`),
  diagnoseConnection: (body: {
    ip_address: string;
    serial_number?: string;
    access_code?: string;
  }) =>
    request<PrinterDiagnosticResult>('/printers/diagnostic', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // Plate Detection - Multi-reference calibration (stores up to 5 references per printer)
  checkPlateEmpty: (printerId: number, options?: { useExternal?: boolean; includeDebugImage?: boolean }) => {
    const params = new URLSearchParams();
    // Only forward use_external when the caller explicitly sets it. Omitted →
    // backend derives the default from the printer's external_camera_enabled
    // setting so calibration and runtime checks use the same camera (#1359).
    if (options?.useExternal !== undefined) {
      params.set('use_external', String(options.useExternal));
    }
    params.set('include_debug_image', String(options?.includeDebugImage ?? false));
    return request<PlateDetectionResult>(
      `/printers/${printerId}/camera/check-plate?${params.toString()}`
    );
  },
  getPlateDetectionStatus: (printerId: number) => {
    return request<PlateDetectionStatus & { chamber_light?: boolean }>(
      `/printers/${printerId}/camera/plate-detection/status`
    );
  },
  calibratePlateDetection: (printerId: number, options?: { label?: string; useExternal?: boolean }) => {
    const params = new URLSearchParams();
    if (options?.label) params.set('label', options.label);
    if (options?.useExternal !== undefined) {
      params.set('use_external', String(options.useExternal));
    }
    return request<CalibrationResult & { index: number }>(
      `/printers/${printerId}/camera/plate-detection/calibrate?${params.toString()}`,
      { method: 'POST' }
    );
  },
  deletePlateCalibration: (printerId: number) => {
    return request<CalibrationResult>(
      `/printers/${printerId}/camera/plate-detection/calibrate`,
      { method: 'DELETE' }
    );
  },
  getPlateReferences: (printerId: number) => {
    return request<{
      references: PlateReference[];
      max_references: number;
    }>(`/printers/${printerId}/camera/plate-detection/references`);
  },
  getPlateReferenceThumbnailUrl: (printerId: number, index: number) =>
    withStreamToken(`${API_BASE}/printers/${printerId}/camera/plate-detection/references/${index}/thumbnail`),
  updatePlateReferenceLabel: (printerId: number, index: number, label: string) => {
    const params = new URLSearchParams();
    params.set('label', label);
    return request<{ success: boolean; index: number; label: string }>(
      `/printers/${printerId}/camera/plate-detection/references/${index}?${params.toString()}`,
      { method: 'PUT' }
    );
  },
  deletePlateReference: (printerId: number, index: number) => {
    return request<{ success: boolean; message: string }>(
      `/printers/${printerId}/camera/plate-detection/references/${index}`,
      { method: 'DELETE' }
    );
  },

  // External Links
  getExternalLinks: () => request<ExternalLink[]>('/external-links/'),
  getExternalLink: (id: number) => request<ExternalLink>(`/external-links/${id}`),
  createExternalLink: (data: ExternalLinkCreate) =>
    request<ExternalLink>('/external-links/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateExternalLink: (id: number, data: ExternalLinkUpdate) =>
    request<ExternalLink>(`/external-links/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteExternalLink: (id: number) =>
    request<{ message: string }>(`/external-links/${id}`, { method: 'DELETE' }),
  reorderExternalLinks: (ids: number[]) =>
    request<ExternalLink[]>('/external-links/reorder', {
      method: 'PUT',
      body: JSON.stringify({ ids }),
    }),
  uploadExternalLinkIcon: async (id: number, file: File): Promise<ExternalLink> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/external-links/${id}/icon`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteExternalLinkIcon: (id: number) =>
    request<ExternalLink>(`/external-links/${id}/icon`, { method: 'DELETE' }),
  getExternalLinkIconUrl: (id: number) => withMediaToken(`${API_BASE}/external-links/${id}/icon`),

  // Projects
  getProjects: (status?: string) => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    return request<ProjectListItem[]>(`/projects/?${params}`);
  },
  getProject: (id: number) => request<Project>(`/projects/${id}`),
  createProject: (data: ProjectCreate) =>
    request<Project>('/projects/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateProject: (id: number, data: ProjectUpdate) =>
    request<Project>(`/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteProject: (id: number) =>
    request<{ message: string }>(`/projects/${id}`, { method: 'DELETE' }),
  getProjectArchives: (id: number, limit = 100, offset = 0) =>
    request<Archive[]>(`/projects/${id}/archives?limit=${limit}&offset=${offset}`),
  // Completed-run counts per library file (#1897); files with 0 runs are omitted
  getProjectFileProgress: (id: number) =>
    request<ProjectFileProgress[]>(`/projects/${id}/file-progress`),
  addArchivesToProject: (projectId: number, archiveIds: number[]) =>
    request<{ message: string }>(`/projects/${projectId}/add-archives`, {
      method: 'POST',
      body: JSON.stringify({ archive_ids: archiveIds }),
    }),
  removeArchivesFromProject: (projectId: number, archiveIds: number[]) =>
    request<{ message: string }>(`/projects/${projectId}/remove-archives`, {
      method: 'POST',
      body: JSON.stringify({ archive_ids: archiveIds }),
    }),
  addQueueItemsToProject: (projectId: number, queueItemIds: number[]) =>
    request<{ message: string }>(`/projects/${projectId}/add-queue`, {
      method: 'POST',
      body: JSON.stringify({ queue_item_ids: queueItemIds }),
    }),

  // Project Attachments
  uploadProjectAttachment: async (projectId: number, file: File): Promise<{
    status: string;
    filename: string;
    original_name: string;
    attachments: ProjectAttachment[];
  }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/projects/${projectId}/attachments`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  getProjectAttachmentUrl: (projectId: number, filename: string) =>
    `${API_BASE}/projects/${projectId}/attachments/${encodeURIComponent(filename)}`,
  deleteProjectAttachment: (projectId: number, filename: string) =>
    request<{ status: string; message: string; attachments: ProjectAttachment[] | null }>(
      `/projects/${projectId}/attachments/${encodeURIComponent(filename)}`,
      { method: 'DELETE' }
    ),

  // #1155: Cover image
  // Browsers can't attach `Authorization: Bearer ...` to `<img src>`, so we
  // append the stream-token query string the same way archive thumbnails do.
  // `version` cache-busts the browser copy after a re-upload. It has to go on
  // before the token does: callers used to append their own `?v=` to the
  // returned URL, which already ended in `?token=…`, so the second `?` landed
  // inside the token value and the image 401'd whenever auth was enabled.
  getProjectCoverImageUrl: (projectId: number, version?: string | number) =>
    withMediaToken(
      `${API_BASE}/projects/${projectId}/cover-image${
        version === undefined ? '' : `?v=${encodeURIComponent(String(version))}`
      }`
    ),
  uploadProjectCoverImage: async (
    projectId: number,
    file: File
  ): Promise<{ status: string; filename: string; size: number }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/projects/${projectId}/cover-image`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteProjectCoverImage: (projectId: number) =>
    request<{ status: string }>(`/projects/${projectId}/cover-image`, { method: 'DELETE' }),

  // BOM (Bill of Materials)
  getProjectBOM: (projectId: number) =>
    request<BOMItem[]>(`/projects/${projectId}/bom`),
  createBOMItem: (projectId: number, data: BOMItemCreate) =>
    request<BOMItem>(`/projects/${projectId}/bom`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateBOMItem: (projectId: number, itemId: number, data: BOMItemUpdate) =>
    request<BOMItem>(`/projects/${projectId}/bom/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteBOMItem: (projectId: number, itemId: number) =>
    request<{ status: string; message: string }>(`/projects/${projectId}/bom/${itemId}`, {
      method: 'DELETE',
    }),

  // Templates
  getTemplates: () => request<ProjectListItem[]>('/projects/templates/'),
  createTemplateFromProject: (projectId: number) =>
    request<Project>(`/projects/${projectId}/create-template`, { method: 'POST' }),
  createProjectFromTemplate: (templateId: number, name?: string) =>
    request<Project>(`/projects/from-template/${templateId}${name ? `?name=${encodeURIComponent(name)}` : ''}`, {
      method: 'POST',
    }),

  // Timeline
  getProjectTimeline: (projectId: number, limit = 50) =>
    request<TimelineEvent[]>(`/projects/${projectId}/timeline?limit=${limit}`),

  // Project Export/Import
  exportProjectJson: (projectId: number) =>
    request<ProjectExport>(`/projects/${projectId}/export?format=json`),
  importProject: (data: ProjectImport) =>
    request<Project>('/projects/import', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  importProjectFile: async (file: File): Promise<Project> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/projects/import/file`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  exportProjectZip: async (projectId: number): Promise<{ blob: Blob; filename: string }> => {
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/projects/${projectId}/export`, {
      headers,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const contentDisposition = response.headers.get('Content-Disposition');
    const filename = parseContentDispositionFilename(contentDisposition) || `project_${projectId}.zip`;
    const blob = await response.blob();
    return { blob, filename };
  },

  // API Keys
  getAPIKeys: () => request<APIKey[]>('/api-keys/'),
  createAPIKey: (data: APIKeyCreate) =>
    request<APIKeyCreateResponse>('/api-keys/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateAPIKey: (id: number, data: APIKeyUpdate) =>
    request<APIKey>(`/api-keys/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deleteAPIKey: (id: number) =>
    request<{ message: string }>(`/api-keys/${id}`, { method: 'DELETE' }),

  // AMS History
  getAMSHistory: (printerId: number, amsId: number, hours = 24) =>
    request<AMSHistoryResponse>(`/ams-history/${printerId}/${amsId}?hours=${hours}`),

  // Printer heater (nozzle / bed / chamber) sensor history
  getPrinterSensorHistory: (printerId: number, hours = 24, kinds?: string[]) => {
    const params = new URLSearchParams({ hours: String(hours) });
    if (kinds && kinds.length > 0) params.set('kinds', kinds.join(','));
    return request<PrinterSensorHistoryResponse>(`/printer-sensor-history/${printerId}?${params.toString()}`);
  },

  // System Info
  getSystemInfo: () => request<SystemInfo>('/system/info'),
  getSystemHealth: () => request<SystemHealthResult>('/system/health'),
  getStorageUsage: (options?: { refresh?: boolean }) => {
    const params = new URLSearchParams();
    if (options?.refresh) {
      params.set('refresh', 'true');
    }
    const query = params.toString();
    return request<StorageUsageResponse>(`/system/storage-usage${query ? `?${query}` : ''}`);
  },

  // Library (File Manager)
  getLibraryFolders: () => request<LibraryFolderTree[]>('/library/folders'),
  createLibraryFolder: (data: LibraryFolderCreate) =>
    request<LibraryFolder>('/library/folders', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateLibraryFolder: (id: number, data: LibraryFolderUpdate) =>
    request<LibraryFolder>(`/library/folders/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteLibraryFolder: (id: number) =>
    request<{ status: string; message: string }>(`/library/folders/${id}`, { method: 'DELETE' }),
  createExternalFolder: (data: ExternalFolderCreate) =>
    request<LibraryFolder>('/library/folders/external', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  scanExternalFolder: (folderId: number) =>
    request<{ status: string; added: number; removed: number }>(`/library/folders/${folderId}/scan`, {
      method: 'POST',
    }),
  getLibraryFoldersByProject: (projectId: number) =>
    request<LibraryFolder[]>(`/library/folders/by-project/${projectId}`),
  getLibraryFoldersByArchive: (archiveId: number) =>
    request<LibraryFolder[]>(`/library/folders/by-archive/${archiveId}`),

  getLibraryFiles: (
    folderId?: number | null,
    includeRoot = true,
    projectId?: number,
    scope?: 'internal' | 'external',
    recursive = false,
    tagIds: number[] = [],
  ) => {
    const params = new URLSearchParams();
    if (folderId !== undefined && folderId !== null) {
      params.set('folder_id', String(folderId));
    }
    if (projectId !== undefined) {
      params.set('project_id', String(projectId));
    }
    params.set('include_root', String(includeRoot));
    if (scope === 'internal') params.set('internal_only', 'true');
    else if (scope === 'external') params.set('external_only', 'true');
    // recursive=true expands the folder_id filter to include every descendant
    // folder (#1268). Only meaningful when folder_id is set; ignored server-side
    // otherwise. Off by default so non-search callers keep folder-scoped behavior.
    if (recursive) params.set('recursive', 'true');
    // Tag filter (#1268). Repeated ?tag_ids=N&tag_ids=M form for AND semantics
    // — backend joins the association table and HAVING COUNT(DISTINCT) matches
    // the array length. Tag filter intentionally bypasses folder scoping
    // server-side (cross-cutting design decision).
    for (const tagId of tagIds) {
      params.append('tag_ids', String(tagId));
    }
    return request<LibraryFileListItem[]>(`/library/files?${params}`);
  },
  getLibraryFolderReadme: (folderId: number) =>
    request<{ filename: string; content: string; truncated: boolean }>(
      `/library/folders/${folderId}/readme`,
    ),

  // ============ Library tag catalog (#1268) ============
  getLibraryTags: () =>
    request<LibraryTag[]>('/library/tags'),
  createLibraryTag: (name: string) =>
    request<LibraryTag>('/library/tags', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  updateLibraryTag: (id: number, name: string) =>
    request<LibraryTag>(`/library/tags/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),
  deleteLibraryTag: (id: number) =>
    request<void>(`/library/tags/${id}`, { method: 'DELETE' }),
  bulkAssignLibraryTags: (
    fileIds: number[],
    tagIds: number[],
    action: 'add' | 'remove' | 'replace',
  ) =>
    request<LibraryTagBulkAssignResult>('/library/tags/bulk-assign', {
      method: 'POST',
      body: JSON.stringify({ file_ids: fileIds, tag_ids: tagIds, action }),
    }),
  // ============ Variant groups (#671 / #2570) ============
  // "These files are the same job sliced for different printers." Consumed from
  // both ends: the queue picks a printer and needs the matching file, the File
  // Manager's print action has the printer and needs the same match.
  createVariantGroup: (
    members: { library_file_id: number; target_model?: string }[],
    name?: string,
  ) =>
    request<VariantGroup>('/library/variant-groups', {
      method: 'POST',
      body: JSON.stringify({ members, ...(name ? { name } : {}) }),
    }),
  getVariantGroup: (groupId: number) =>
    request<VariantGroup>(`/library/variant-groups/${groupId}`),
  /** Returns null when the file is not grouped, rather than throwing on the 404. */
  getVariantGroupForFile: async (fileId: number): Promise<VariantGroup | null> => {
    try {
      return await request<VariantGroup>(`/library/variant-groups/by-file/${fileId}`);
    } catch {
      return null;
    }
  },
  updateVariantGroup: (groupId: number, body: { name?: string; member_file_ids?: number[] }) =>
    request<VariantGroup>(`/library/variant-groups/${groupId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  addVariantGroupMember: (
    groupId: number,
    libraryFileId: number,
    targetModel?: string,
  ) =>
    request<VariantGroup>(`/library/variant-groups/${groupId}/members`, {
      method: 'POST',
      body: JSON.stringify({
        library_file_id: libraryFileId,
        ...(targetModel ? { target_model: targetModel } : {}),
      }),
    }),
  removeVariantGroupMember: (groupId: number, fileId: number) =>
    request<void>(`/library/variant-groups/${groupId}/members/${fileId}`, { method: 'DELETE' }),
  deleteVariantGroup: (groupId: number) =>
    request<void>(`/library/variant-groups/${groupId}`, { method: 'DELETE' }),

  getLibraryFile: (id: number) => request<LibraryFile>(`/library/files/${id}`),
  uploadLibraryFile: async (
    file: File,
    folderId?: number | null,
    generateStlThumbnails: boolean = true
  ): Promise<LibraryFileUploadResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (folderId) params.set('folder_id', String(folderId));
    params.set('generate_stl_thumbnails', String(generateStlThumbnails));
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/library/files?${params}`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  extractZipFile: async (
    file: File,
    folderId?: number | null,
    preserveStructure: boolean = true,
    createFolderFromZip: boolean = false,
    generateStlThumbnails: boolean = true
  ): Promise<ZipExtractResponse> => {
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (folderId) params.set('folder_id', String(folderId));
    params.set('preserve_structure', String(preserveStructure));
    params.set('create_folder_from_zip', String(createFolderFromZip));
    params.set('generate_stl_thumbnails', String(generateStlThumbnails));
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/library/files/extract-zip?${params}`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  updateLibraryFile: (id: number, data: LibraryFileUpdate) =>
    request<LibraryFile>(`/library/files/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteLibraryFile: (id: number) =>
    request<{ status: string; message: string; trashed: boolean }>(`/library/files/${id}`, { method: 'DELETE' }),

  // ========== Library Trash (#1008) ==========
  previewLibraryPurge: (olderThanDays: number, includeNeverPrinted: boolean = true) =>
    request<LibraryPurgePreview>(
      `/library/purge/preview?older_than_days=${olderThanDays}&include_never_printed=${includeNeverPrinted}`,
    ),
  executeLibraryPurge: (olderThanDays: number, includeNeverPrinted: boolean = true) =>
    request<{ moved_to_trash: number }>('/library/purge', {
      method: 'POST',
      body: JSON.stringify({ older_than_days: olderThanDays, include_never_printed: includeNeverPrinted }),
    }),
  listLibraryTrash: (limit: number = 100, offset: number = 0) =>
    request<LibraryTrashListResponse>(`/library/trash?limit=${limit}&offset=${offset}`),
  restoreLibraryTrash: (fileId: number) =>
    request<{ status: string; id: number }>(`/library/trash/${fileId}/restore`, { method: 'POST' }),
  hardDeleteLibraryTrash: (fileId: number) =>
    request<{ status: string }>(`/library/trash/${fileId}`, { method: 'DELETE' }),
  emptyLibraryTrash: () => request<{ deleted: number }>('/library/trash', { method: 'DELETE' }),
  getLibraryTrashSettings: () =>
    request<LibraryTrashSettings>('/library/trash/settings'),
  updateLibraryTrashSettings: (body: LibraryTrashSettings) =>
    request<LibraryTrashSettings>('/library/trash/settings', {
      method: 'PUT',
      body: JSON.stringify(body),
    }),
  getLibraryFileDownloadUrl: (id: number) => `${API_BASE}/library/files/${id}/download`,
  createLibrarySlicerToken: (fileId: number) =>
    request<{ token: string }>(`/library/files/${fileId}/slicer-token`, { method: 'POST' }),
  getLibrarySlicerDownloadUrl: (fileId: number, token: string, filename: string) =>
    `${API_BASE}/library/files/${fileId}/dl/${token}/${encodeURIComponent(buildSlicerUrlFilename(filename))}`,
  downloadLibraryFile: async (id: number, filename?: string): Promise<void> => {
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/library/files/${id}/download`, { headers });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    const disposition = response.headers.get('Content-Disposition');
    const downloadFilename = parseContentDispositionFilename(disposition) || filename || `file_${id}`;
    const blob = await response.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadFilename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
  },
  getLibraryFileThumbnailUrl: (id: number) => withMediaToken(`${API_BASE}/library/files/${id}/thumbnail`),
  // Client-rendered preview thumbnail upload (#2976). STEP/PDF/spreadsheet
  // previews render in the browser; the first render is posted back so the
  // grid gets a thumbnail without a server-side renderer for those formats.
  uploadLibraryPreviewThumbnail: async (fileId: number, thumbnail: Blob): Promise<{ updated: boolean }> => {
    const formData = new FormData();
    formData.append('thumbnail', thumbnail, 'preview.png');
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/library/files/${fileId}/preview-thumbnail`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  getLibraryFilePlateThumbnail: (id: number, plateIndex: number) =>
    withMediaToken(`${API_BASE}/library/files/${id}/plate-thumbnail/${plateIndex}`),
  // Photos of the printed result (#3077) — same shape as the archive photo API.
  getLibraryFilePhotoUrl: (fileId: number, filename: string) =>
    withMediaToken(`${API_BASE}/library/files/${fileId}/photos/${encodeURIComponent(filename)}`),
  uploadLibraryFilePhoto: async (fileId: number, file: File): Promise<{ status: string; filename: string; photos: string[] }> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/library/files/${fileId}/photos`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },
  deleteLibraryFilePhoto: (fileId: number, filename: string) =>
    request<{ status: string; photos: string[] }>(`/library/files/${fileId}/photos/${encodeURIComponent(filename)}`, {
      method: 'DELETE',
    }),
  getLibraryFileGcodeUrl: (id: number) => `${API_BASE}/library/files/${id}/gcode`,
  moveLibraryFiles: (fileIds: number[], folderId: number | null) =>
    request<{ status: string; moved: number }>('/library/files/move', {
      method: 'POST',
      body: JSON.stringify({ file_ids: fileIds, folder_id: folderId }),
    }),
  bulkDeleteLibrary: (fileIds: number[], folderIds: number[]) =>
    request<{ deleted_files: number; deleted_folders: number }>('/library/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds }),
    }),
  getLibraryStats: () => request<LibraryStats>('/library/stats'),
  batchGenerateStlThumbnails: (options: {
    file_ids?: number[];
    folder_id?: number;
    all_missing?: boolean;
  }) =>
    request<BatchThumbnailResponse>('/library/generate-stl-thumbnails', {
      method: 'POST',
      body: JSON.stringify(options),
    }),
  combineLibraryFiles: (items: { file_id: number; copies: number }[], filename: string, folderId: number | null) =>
    request<LibraryFileUploadResponse>('/library/files/combine', {
      method: 'POST',
      body: JSON.stringify({ items, filename, folder_id: folderId }),
    }),
  addLibraryFilesToQueue: (fileIds: number[]) =>
    request<AddToQueueResponse>('/library/files/add-to-queue', {
      method: 'POST',
      body: JSON.stringify({ file_ids: fileIds }),
    }),
  getLibraryFilePlates: (fileId: number) =>
    request<LibraryFilePlatesResponse>(`/library/files/${fileId}/plates`),
  getLibraryFileFilamentRequirements: (
    fileId: number,
    plateId?: number,
    requestId?: string,
    /** Ask for one entry per project slot instead of only the slots this
     * plate consumes. The slice modal needs it: its filament list is
     * positional, so a source whose only used slot is 4 must still present
     * four rows or the user's pick is bound to slot 1 (#2712). Print-time
     * AMS matching must NOT set this — it wants the used-only list. */
    fullSlots?: boolean,
  ) => {
    const qs = new URLSearchParams();
    if (plateId !== undefined) qs.set('plate_id', String(plateId));
    if (requestId) qs.set('request_id', requestId);
    if (fullSlots) qs.set('full_slots', 'true');
    return request<{
      file_id: number;
      filename: string;
      filaments: Array<{
        slot_id: number;
        type: string;
        color: string;
        used_grams: number;
        used_meters: number;
        used_in_plate?: boolean;
      }>;
    }>(`/library/files/${fileId}/filament-requirements${qs.toString() ? `?${qs}` : ''}`);
  },

  /** Poll the sidecar's per-request progress snapshot via the PrintLab
   * proxy. Used by the SliceModal's filament-discovery path so the inline
   * spinner + persistent toast can show "Generating G-code (45%)" while
   * the preview slice runs. Returns null on 404 (sidecar doesn't yet
   * have an entry — early race window — or it expired) so the poller
   * can keep trying. */
  getPreviewSliceProgress: async (requestId: string): Promise<SliceJobProgress | null> => {
    try {
      return await request<SliceJobProgress>(`/slicer/preview-progress/${encodeURIComponent(requestId)}`);
    } catch {
      return null;
    }
  },

  // GitHub Backup
  getGitHubBackupConfig: () =>
    request<GitHubBackupConfig | null>('/github-backup/config'),

  getGitHubBackupCloudAccounts: () =>
    request<CloudAccountCounts>('/github-backup/cloud-accounts'),

  saveGitHubBackupConfig: (config: GitHubBackupConfigCreate) =>
    request<GitHubBackupConfig>('/github-backup/config', {
      method: 'POST',
      body: JSON.stringify(config),
    }),

  updateGitHubBackupConfig: (config: Partial<GitHubBackupConfigCreate>) =>
    request<GitHubBackupConfig>('/github-backup/config', {
      method: 'PATCH',
      body: JSON.stringify(config),
    }),

  deleteGitHubBackupConfig: () =>
    request<{ message: string }>('/github-backup/config', { method: 'DELETE' }),

  testGitHubConnection: (repoUrl: string, token: string, provider: GitProviderType = 'github') =>
    request<GitHubTestConnectionResponse>(
      `/github-backup/test?repo_url=${encodeURIComponent(repoUrl)}&token=${encodeURIComponent(token)}&provider=${encodeURIComponent(provider)}`,
      { method: 'POST' }
    ),

  testGitHubStoredConnection: () =>
    request<GitHubTestConnectionResponse>('/github-backup/test-stored', { method: 'POST' }),

  triggerGitHubBackup: () =>
    request<GitHubBackupTriggerResponse>('/github-backup/run', { method: 'POST' }),

  getGitHubBackupStatus: () =>
    request<GitHubBackupStatus>('/github-backup/status'),

  getGitHubBackupLogs: (limit: number = 50) =>
    request<GitHubBackupLog[]>(`/github-backup/logs?limit=${limit}`),

  clearGitHubBackupLogs: (keepLast: number = 10) =>
    request<{ deleted: number; message: string }>(`/github-backup/logs?keep_last=${keepLast}`, { method: 'DELETE' }),

  // Restore from a Git backup (#2656)
  getGitHubBackupCommits: (limit: number = 20) =>
    request<GitHubCommitListResponse>(`/github-backup/commits?limit=${limit}`),

  getGitHubRestorePreview: (ref: string = 'HEAD') =>
    request<GitHubRestorePreview>(`/github-backup/restore/preview?ref=${encodeURIComponent(ref)}`),

  restoreFromGitHub: (payload: GitHubRestoreRequest) =>
    request<GitHubRestoreResponse>('/github-backup/restore', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // Scheduled local backups
  getLocalBackupStatus: () =>
    request<LocalBackupStatus>('/local-backup/status'),

  triggerLocalBackup: () =>
    request<{ success: boolean; message: string; filename?: string }>('/local-backup/run', { method: 'POST' }),

  checkLocalBackupPath: () =>
    request<LocalBackupPathCheck>('/local-backup/path-check'),

  getLocalBackups: () =>
    request<LocalBackupFile[]>('/local-backup/backups'),

  downloadLocalBackup: async (filename: string): Promise<{ blob: Blob; filename: string }> => {
    const response = await fetch(`${API_BASE}/local-backup/backups/${encodeURIComponent(filename)}/download`, {
      headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
    });
    if (!response.ok) throw new Error('Download failed');
    const blob = await response.blob();
    return { blob, filename };
  },

  restoreLocalBackup: (filename: string) =>
    request<{ success: boolean; message: string }>(`/local-backup/backups/${encodeURIComponent(filename)}/restore`, { method: 'POST' }),

  deleteLocalBackup: (filename: string) =>
    request<{ success: boolean; message: string }>(`/local-backup/backups/${encodeURIComponent(filename)}`, { method: 'DELETE' }),

  // Obico AI failure detection
  getObicoStatus: () =>
    request<ObicoStatus>('/obico/status'),

  getObicoPrinterStatus: () =>
    request<ObicoPrinterStatus>('/obico/printer-status'),

  // `token` is sent as-is, so an empty string tests with no token at all.
  // Omitting the argument makes the backend fall back to the saved token.
  testObicoConnection: (url: string, token?: string) =>
    request<ObicoTestConnection>('/obico/test-connection', {
      method: 'POST',
      body: JSON.stringify(token === undefined ? { url } : { url, token }),
    }),

  // Slicer API — slice in the background. Both endpoints return 202 + a
  // job_id; poll /slice-jobs/{id} until status is `completed` or `failed`.
  sliceLibraryFile: (fileId: number, body: SliceRequest) =>
    request<SliceJobEnqueueResponse>(`/library/files/${fileId}/slice`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  sliceArchive: (archiveId: number, body: SliceRequest) =>
    request<SliceJobEnqueueResponse>(`/archives/${archiveId}/slice`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  getSliceJob: (jobId: number) =>
    request<SliceJobState>(`/slice-jobs/${jobId}`),

  // Unified slicer-preset listing — cloud + local + standard, deduped by name.
  // Used by the SliceModal; see UnifiedPresetsResponse for the shape and
  // backend/app/api/routes/slicer_presets.py for the priority rules.
  // `refresh` bypasses the in-process cloud and bundled-preset caches on the
  // backend; the SliceModal's Refresh button passes true so a preset deleted
  // in Bambu Studio or Bambu Handy shows up without the 5-min TTL wait.
  getSlicerPresets: (options?: { refresh?: boolean }) =>
    request<UnifiedPresetsResponse>(
      options?.refresh ? '/slicer/presets?refresh=true' : '/slicer/presets',
    ),

  // Slicer Pipelines (#1425) — preset bundles the SliceModal can apply in
  // one click. CRUD is gated on PIPELINES_READ / PIPELINES_WRITE.
  listSlicerPipelines: () =>
    request<SlicerPipelinesListResponse>('/slicer-pipelines/'),
  getSlicerPipeline: (id: number) =>
    request<SlicerPipeline>(`/slicer-pipelines/${id}`),
  createSlicerPipeline: (data: SlicerPipelineCreateRequest) =>
    request<SlicerPipeline>('/slicer-pipelines/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateSlicerPipeline: (id: number, data: SlicerPipelineUpdateRequest) =>
    request<SlicerPipeline>(`/slicer-pipelines/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteSlicerPipeline: (id: number) =>
    request<void>(`/slicer-pipelines/${id}`, { method: 'DELETE' }),
  checkPipelineEligibility: (
    pipelineId: number,
    source: { kind: 'libraryFile'; id: number } | { kind: 'archive'; id: number },
  ) =>
    request<PipelineEligibilityReport>(`/slicer-pipelines/${pipelineId}/check-eligibility`, {
      method: 'POST',
      body: JSON.stringify(
        source.kind === 'libraryFile'
          ? { source_library_file_id: source.id }
          : { source_archive_id: source.id },
      ),
    }),
  runPipeline: (
    pipelineId: number,
    source: { kind: 'libraryFile'; id: number } | { kind: 'archive'; id: number },
    force = false,
    copies = 1,
  ) =>
    request<PipelineRun>(`/slicer-pipelines/${pipelineId}/run`, {
      method: 'POST',
      body: JSON.stringify({
        ...(source.kind === 'libraryFile'
          ? { source_library_file_id: source.id }
          : { source_archive_id: source.id }),
        force,
        copies,
      }),
    }),
  listPipelineRuns: (pipelineId: number, limit = 5) =>
    request<PipelineRunListResponse>(
      `/slicer-pipelines/${pipelineId}/runs?limit=${limit}`,
    ),
  // Dashboard list across all pipelines (#1425 PR C).
  listAllPipelineRuns: (params: {
    limit?: number;
    offset?: number;
    pipelineId?: number;
    status?: string;
    targetPrinterId?: number;
    targetModelClass?: string;
  } = {}) => {
    const search = new URLSearchParams();
    if (params.limit) search.set('limit', String(params.limit));
    if (params.offset) search.set('offset', String(params.offset));
    if (params.pipelineId) search.set('pipeline_id', String(params.pipelineId));
    if (params.status) search.set('status', params.status);
    if (params.targetPrinterId) search.set('target_printer_id', String(params.targetPrinterId));
    if (params.targetModelClass) search.set('target_model_class', params.targetModelClass);
    const q = search.toString();
    return request<PipelineRunListResponse>(
      `/pipeline-runs${q ? '?' + q : ''}`,
    );
  },
  // Clear terminal pipeline runs (#1425 PR C polish). Deletes all runs in
  // a terminal state (completed/failed/cancelled/partial_failure); in-flight
  // runs are preserved.
  clearTerminalPipelineRuns: () =>
    request<{ deleted: number }>('/pipeline-runs/clear', { method: 'POST' }),
  getPipelineRun: (runId: number) =>
    request<PipelineRun>(`/pipeline-runs/${runId}`),
  cancelPipelineRun: (runId: number) =>
    request<PipelineRun>(`/pipeline-runs/${runId}/cancel`, { method: 'POST' }),
  retryFailedPipelineRun: (runId: number) =>
    request<PipelineRun>(`/pipeline-runs/${runId}/retry-failed`, { method: 'POST' }),

  // Canonical Bambu printer-model registry — "Bambu Lab <model>" → short code.
  // Single source of truth shared with backend (PRINTER_MODEL_MAP); the
  // SliceModal uses this to classify cloud / standard presets by their
  // `@BBL <code>` suffix against the selected printer-preset name (#1325).
  getSlicerPrinterModels: () =>
    request<Record<string, string>>('/slicer/printer-models'),

  /**
   * Effective values of a process preset, with its `inherits:` chain flattened
   * by the slicer sidecar. Powers the slice modal's settings panel, which would
   * otherwise show the option schema's compiled-in defaults (a preset setting a
   * 0.42mm line width appears as the C++ default of 0).
   *
   * `resolved: false` means the values could not be obtained -- sidecar offline,
   * too old for the endpoint, or slicing not configured -- and the caller should
   * fall back to schema defaults rather than treat it as a failure.
   */
  getSlicerPresetValues: (ref: PresetRef) =>
    request<SlicerPresetValues>(
      `/slicer/preset-values?source=${encodeURIComponent(ref.source)}&id=${encodeURIComponent(ref.id)}`,
    ),

  // Local Presets (OrcaSlicer imports)
  getLocalPresets: () =>
    request<LocalPresetsResponse>('/local-presets/'),
  getLocalPresetDetail: (id: number) =>
    request<LocalPresetDetail>(`/local-presets/${id}`),
  importLocalPresets: (formData: FormData) =>
    fetch(`${API_BASE}/local-presets/import`, {
      method: 'POST',
      headers: authToken ? { 'Authorization': `Bearer ${authToken}` } : {},
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return res.json() as Promise<ImportResponse>;
    }),
  createLocalPreset: (data: { name: string; preset_type: string; setting: Record<string, unknown> }) =>
    request<LocalPreset>('/local-presets/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateLocalPreset: (id: number, data: { name?: string; setting?: Record<string, unknown> }) =>
    request<LocalPreset>(`/local-presets/${id}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  deleteLocalPreset: (id: number) =>
    request<{ success: boolean }>(`/local-presets/${id}`, { method: 'DELETE' }),
  refreshBaseProfileCache: () =>
    request<{ refreshed: number; failed: number; total: number }>('/local-presets/base-cache/refresh', { method: 'POST' }),
};
