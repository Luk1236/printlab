// Aus types.ts ausgelagerte Typen: Spoolman, Inventar, Lieferanten und CSV-Import.

export interface SpoolmanStatus {
  enabled: boolean;
  connected: boolean;
  url: string | null;
}
export interface SkippedSpool {
  location: string;
  reason: string;
  filament_type: string | null;
  color: string | null;
}
export interface SpoolmanSyncResult {
  success: boolean;
  synced_count: number;
  skipped_count: number;
  skipped: SkippedSpool[];
  errors: string[];
}
export interface UnlinkedSpool {
  id: number;
  filament_name: string | null;
  filament_vendor: string | null;
  filament_material: string | null;
  filament_color_hex: string | null;
  remaining_weight: number | null;
  location: string | null;
}
export interface LinkedSpoolInfo {
  id: number;
  remaining_weight: number | null;
  filament_weight: number | null;
}
export interface LinkedSpoolsMap {
  linked: Record<string, LinkedSpoolInfo>; // tag (uppercase) -> spool info
}
export interface SpoolmanVendor {
  id: number;
  name: string;
}
export interface SpoolmanFilamentEntry {
  id: number;
  name: string;
  material: string | null;
  color_hex: string | null;
  color_name: string | null;
  weight: number | null;
  spool_weight: number | null;
  vendor: SpoolmanVendor | null;
}
export type SpoolLabelTemplate =
  | 'ams_holder_74x33'
  | 'ams_holder_75x55'
  | 'box_40x30'
  | 'box_62x29'
  | 'avery_5160'
  | 'avery_l7160';
export const SPOOL_LABEL_FIELDS = [
  'brand',
  'material',
  'hex',
  'name',
  'location',
  'material_number',
  'temps',
  'weight',
  'note',
  'added',
  'qr',
  'spool_id',
] as const;
export type SpoolLabelField = (typeof SPOOL_LABEL_FIELDS)[number];
export interface PrintSpoolLabelsRequest {
  spool_ids: number[];
  template: SpoolLabelTemplate;
  monochrome: boolean;
  starting_position: number;
  fields?: SpoolLabelField[];
  format?: 'pdf' | 'png';
  dpi?: 203 | 300 | 600;
}
export interface PreviewSpoolLabelRequest {
  spool_id: number;
  template: SpoolLabelTemplate;
  monochrome: boolean;
  fields: SpoolLabelField[];
}
export interface InventorySpool {
  id: number;
  material: string;
  subtype: string | null;
  color_name: string | null;
  // True when color_name was synthesised from subtype because Spoolman has no
  // stored value (Spoolman-backed inventory only). The edit form uses this to
  // leave the input blank, so the user doesn't round-trip the synth value
  // back to Spoolman as if it were a real user-set color_name (#1319).
  color_name_is_synthesized?: boolean;
  rgba: string | null;
  // Multi-colour gradient stops (#1154): comma-separated 6/8-char hex.
  extra_colors: string | null;
  // Visual effect overlay: sparkle | wood | marble | glow | matte.
  effect_type: string | null;
  brand: string | null;
  label_weight: number;
  core_weight: number;
  // Spoolman-backed inventory only: true when the spool has no tare of its
  // own and core_weight is the filament type's. Absent for local spools (#2908).
  core_weight_is_inherited?: boolean;
  core_weight_catalog_id: number | null;
  weight_used: number;
  // Anchor for the resettable "Total Consumed" display (#1390). The
  // counter shown on the Inventory page is `weight_used - weight_used_baseline`;
  // remaining is still `label_weight - weight_used`, so "Reset usage to 0"
  // zeroes the counter without disturbing remaining. Optional for back-compat
  // with rows from a pre-migration DB snapshot — default to 0.
  weight_used_baseline?: number;
  slicer_filament: string | null;
  slicer_filament_name: string | null;
  nozzle_temp_min: number | null;
  nozzle_temp_max: number | null;
  note: string | null;
  added_full: boolean | null;
  last_used: string | null;
  encode_time: string | null;
  tag_uid: string | null;
  tray_uuid: string | null;
  data_origin: string | null;
  tag_type: string | null;
  archived_at: string | null;
  created_at: string;
  updated_at: string;
  cost_per_kg: number | null;
  last_scale_weight: number | null;
  last_weighed_at: string | null;
  // User-defined category + per-spool low-stock threshold override (#729).
  category: string | null;
  low_stock_threshold_pct: number | null;
  // Internal material / article number (#2870) — the purchasing identifier
  // shared by all spools of the same product.
  material_number: string | null;
  k_profiles?: SpoolKProfile[];
  storage_location?: string | null;
  location_id?: number | null;
  // Supplier assignments (#2988). Absent in Spoolman mode — Spoolman's
  // vendor is the manufacturer, not the seller, so there is no mapping.
  suppliers?: SpoolSupplierLink[];
}
export interface Supplier {
  id: number;
  name: string;
  website: string | null;
  customer_number: string | null;
  note: string | null;
  /** Spools referencing this supplier; a referenced supplier cannot be deleted. */
  spool_count: number;
  created_at: string;
  updated_at: string;
}
export interface SupplierInput {
  name: string;
  website?: string | null;
  customer_number?: string | null;
  note?: string | null;
}
export interface SpoolSupplierLinkInput {
  supplier_id: number;
  /** The supplier's own article number — NOT the internal material number. */
  supplier_article_number?: string | null;
  /** Quoted price for comparison — never the cost basis (spool.cost_per_kg). */
  quoted_price_per_kg?: number | null;
  /** Marks where this concrete spool was actually bought. */
  is_purchase_source?: boolean;
}
export interface SpoolSupplierLink {
  id: number;
  supplier_id: number;
  supplier_name: string;
  supplier_article_number: string | null;
  quoted_price_per_kg: number | null;
  is_purchase_source: boolean;
}
export interface SupplierStats {
  supplier_id: number;
  supplier_name: string;
  spool_count: number;
  remaining_g: number;
  consumed_g: number;
  cost: number;
}
export interface MaterialNumberStats {
  material_number: string;
  spool_count: number;
  remaining_g: number;
  consumed_g: number;
  cost: number;
}
export interface SpoolmanBulkCreateResult {
  created: InventorySpool[];
  requested_count: number;
  failed_count: number;
}
export interface CsvImportRow {
  row_number: number;
  status: 'valid' | 'error' | 'skipped';
  reason: string | null;
  material: string | null;
  brand: string | null;
  color_name: string | null;
  rgba: string | null;
  /** rgba/extra_colors/effect_type were filled from the Color Catalog. */
  resolved_color: boolean;
  /** The catalog match came from a different material's variant (no exact
   *  material match). Shown as a warning in the preview. */
  cross_material_color: boolean;
  /** An active spool with the same material+brand+color already exists.
   *  Informational only — the import still creates the row. */
  duplicate_of_existing: boolean;
}
export interface CsvImportPreview {
  columns: string[];
  total: number;
  valid_count: number;
  error_count: number;
  skipped_count: number;
  rows: CsvImportRow[];
  warnings: string[];
}
export interface CsvImportResult {
  created: number;
  skipped: number;
  errors: number;
  error_rows: CsvImportRow[];
}
export interface SpoolUsageRecord {
  id: number;
  spool_id: number;
  printer_id: number | null;
  print_name: string | null;
  weight_used: number;
  percent_used: number;
  status: string;
  cost: number | null;
  created_at: string;
}
export interface SpoolKProfile {
  id: number;
  spool_id: number;
  printer_id: number;
  extruder: number;
  nozzle_diameter: string;
  nozzle_type: string | null;
  k_value: number;
  name: string | null;
  cali_idx: number | null;
  setting_id: string | null;
  created_at: string;
}
export interface SpoolKProfileInput {
  printer_id: number;
  extruder?: number;
  nozzle_diameter?: string;
  nozzle_type?: string | null;
  k_value: number;
  name?: string | null;
  cali_idx?: number | null;
  setting_id?: string | null;
}
export interface SlotSpoolDefaults {
  slicer_filament: string | null;
  slicer_filament_name: string | null;
  cali_idx: number | null;
  k_value: number | null;
  profile_name: string | null;
  extruder: number | null;
  nozzle_diameter: string;
}
export interface SpoolFilamentPresetInput {
  printer_model: string;
  nozzle_diameter: string;
  slicer_filament: string | null;
  slicer_filament_name: string | null;
}
export interface SpoolFilamentPreset extends SpoolFilamentPresetInput {
  id: number;
  spool_id: number;
  created_at: string;
}
export interface SlotMaterial {
  ams_id: number;
  tray_id: number;
  global_tray_id: number;
  /** Opaque grouping key from the backend. Two slots back each other up under
   *  AMS Filament Backup only when both `material_key` and `extruder` match.
   *  Never parse it — the format belongs to the backend's identity rule. */
  material_key: string;
  remaining_g: number;
  /** 0 = right / single nozzle, 1 = left. */
  extruder: number;
  /** How the bound spool should be *named* — display only, never matched on.
   *  The printer has no brand field and reports no sub-brand for a
   *  third-party spool, so this is the only place a slot's real identity
   *  exists. Null when the binding resolves to a spool we cannot describe. */
  spool?: SlotSpoolIdentity | null;
}
export interface SlotSpoolIdentity {
  brand: string | null;
  material: string | null;
  subtype: string | null;
  color_name: string | null;
  rgba: string | null;
  /** Comma-separated hex stops for a multi-colour spool, and the effect
   *  overlay — the two things a tray record cannot carry, so a slot swatch
   *  can be drawn the way the inventory row draws it (#3159).
   *
   *  Optional rather than required: the backend sends both keys on every
   *  binding, but a frontend running against an older one gets neither, and
   *  every reader here already falls back to a solid swatch. */
  extra_colors?: string | null;
  effect_type?: string | null;
}
export interface InventoryRemainResponse {
  /** Currently-loaded, inventory-bound slots only — drives the prefer-lowest sort. */
  inventory_remain_g: Record<string, number>;
  /** Every inventory binding on the printer, with identity + extruder side. */
  slot_materials: SlotMaterial[];
}
export interface SpoolAssignment {
  id: number;
  spool_id: number;
  printer_id: number;
  printer_name: string | null;
  ams_id: number;
  tray_id: number;
  fingerprint_color: string | null;
  fingerprint_type: string | null;
  spool?: InventorySpool | null;
  configured: boolean;
  pending_config?: boolean;  // Slot was empty at assign time; will configure on insert
  created_at: string;
  ams_label?: string | null;  // User-defined friendly name for the AMS unit
}
export interface FilamentSkuSettings {
  id: number;
  material: string;
  subtype: string | null;
  brand: string | null;
  color_name: string | null;
  lead_time_days: number;
  safety_margin_value: number;
  safety_margin_unit: 'days' | 'g';
  alerts_snoozed: boolean;
}
export interface ShoppingListItem {
  id: number;
  material: string;
  subtype: string | null;
  brand: string | null;
  color_name: string | null;
  quantity_spools: number;
  note: string | null;
  status: 'pending' | 'purchased' | 'received';
  purchased_at: string | null;
  added_at: string;
}
export interface ShoppingListItemCreate {
  material: string;
  subtype: string | null;
  brand: string | null;
  color_name: string | null;
  quantity_spools: number;
  note?: string | null;
}
