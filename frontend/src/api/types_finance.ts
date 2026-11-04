// Aus types.ts ausgelagerte Typen: Kostenstellen, Guthaben und manuelle Drucke; dazu die Fehlererkennung am Bauteil.

export interface LayerAlertStatus {
  enabled: boolean;
  layer: number;
  triggered: boolean;
  last_layer: number;
}
export interface PartWatcherWarning {
  layer: number;
  total_layers: number;
  difference: number;
  printer: string;
  message: string;
}
export interface PartWatcherStatus {
  enabled: boolean;
  threshold: number;
  warning: PartWatcherWarning | null;
  checked: boolean;
  last_layer: number;
  overrides?: PartWatcherOverride[];
}
export interface PartWatcherOverride {
  key_contains: string;
  threshold: number;
  enabled: boolean;
}
export interface FirstLayerResult {
  ok: boolean;
  brightness: number;
  contrast: number;
  edge_density: number;
  message: string;
  layer: number;
  time: string;
}
export interface FirstLayerStatus {
  enabled: boolean;
  pause_on_warning?: boolean;
  result: FirstLayerResult | null;
  checked: boolean;
  last_layer: number;
}
export interface ExternalLink {
  id: number;
  name: string;
  url: string;
  icon: string;
  open_in_new_tab: boolean;
  custom_icon: string | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}
export interface ExternalLinkCreate {
  name: string;
  url: string;
  icon: string;
  open_in_new_tab?: boolean;
}
export interface ExternalLinkUpdate {
  name?: string;
  url?: string;
  icon?: string;
  open_in_new_tab?: boolean;
}
export interface CostCenterSummary {
  id: number;
  name: string;
  is_private: boolean;
  owner_user_id: number | null;
  is_active: boolean;
  total_balance: number;
  total_budget: number | null;
  monthly_budget: number | null;
  budget_mode: 'none' | 'total' | 'monthly';
  budget_limit: number | null;
  budget_used: number | null;
  budget_available: number | null;
  can_print: boolean;
}
export interface CostCenterCreateRequest {
  name: string;
  total_budget?: number | null;
  monthly_budget?: number | null;
  is_active?: boolean;
}
export interface CostCenterBudgetUpdateRequest {
  total_budget?: number | null;
  monthly_budget?: number | null;
}
export interface CostCenterUpdateRequest {
  name?: string;
  is_active?: boolean;
}
export interface CostCenterMemberRequest {
  user_id: number;
  can_print?: boolean;
}
export interface CostCenterMemberResponse {
  id: number;
  cost_center_id: number;
  user_id: number;
  can_print: boolean;
  created_at: string;
}
export interface CostCenterDetail extends CostCenterSummary {
  members: CostCenterMemberResponse[];
}
export interface WalletBalance {
  user_id: number;
  balance: number;
  currency: string;
  updated_at: string | null;
}
export type WalletTransactionType = 'print_charge' | 'deposit' | 'withdraw' | 'manual_adjustment';
export interface WalletTransaction {
  id: number;
  user_id: number;
  cost_center_id: number | null;
  transaction_type: WalletTransactionType;
  amount: number;
  balance_after: number | null;
  description: string | null;
  created_by_user_id: number | null;
  print_run_id: string | null;
  print_archive_id: number | null;
  print_queue_id: number | null;
  created_at: string;
}
export interface WalletTransactionListResponse {
  items: WalletTransaction[];
  total: number;
  limit: number;
  offset: number;
}
export interface WalletAdjustmentRequest {
  amount: number;
  description?: string;
  cost_center_id?: number | null;
}
export interface WalletAdjustmentResponse {
  transaction: WalletTransaction;
  balance: WalletBalance;
}
export interface TransactionEditRequest {
  user_id?: number | null;
  cost_center_id?: number | null;
  amount?: number | null;
  description?: string | null;
}
export interface ManualPrintRequest {
  user_id: number;
  cost_center_id: number;
  amount: number;
  description?: string | null;
  created_at?: string | null;
}
