import { useState, useMemo, useCallback, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Upload,
  Loader2,
  Search,
  Trash2,
  ChevronDown,
  ChevronUp,
  HardDrive,
  Droplet,
  Settings2,
  Layers,
  AlertCircle,
  Plus,
  Pencil,
  Copy,
  Download,
  Code,
  Sliders,
  X,
  Check,
} from 'lucide-react';
import { api } from '../api/client';
import type { LocalPreset, LocalPresetsResponse } from '../api/client';
import { Card, CardContent } from './Card';
import { Button } from './Button';
import { useToast } from '../contexts/ToastContext';
import { useAuth } from '../contexts/AuthContext';

// Known material types for name-parsing fallback
const MATERIAL_TYPES = ['PLA', 'PETG', 'PCTG', 'ABS', 'ASA', 'TPU', 'PC', 'PA', 'PVA', 'HIPS', 'PP', 'PET', 'NYLON'];

const FILAMENT_TYPE_COLORS: Record<string, string> = {
  PLA: '16A34A',
  PETG: '2563EB',
  ABS: 'EA580C',
  ASA: 'D35400',
  TPU: '9333EA',
  PC: 'BDC3C7',
  PA: '2ECC71',
  NYLON: '2ECC71',
  PVA: 'F1C40F',
  HIPS: '95A5A6',
  PP: 'ECF0F1',
  PET: '3498DB',
};

function parseMaterialFromName(name: string): string | null {
  const upper = name.toUpperCase();
  for (const mat of MATERIAL_TYPES) {
    if (new RegExp(`\\b${mat}\\b`).test(upper)) return mat;
  }
  return null;
}

function parseVendorFromName(name: string): string | null {
  const clean = name.replace(/@.+$/, '').trim();
  const upper = clean.toUpperCase();
  for (const mat of MATERIAL_TYPES) {
    const idx = upper.indexOf(mat);
    if (idx > 0) {
      const vendor = clean.slice(0, idx).trim();
      if (vendor && vendor.length > 1) return vendor;
    }
  }
  return null;
}

// ============================================================================
// PRESET CARD
// ============================================================================

function PresetCard({
  preset,
  onDelete,
  onClone,
  onEdit,
  onExport,
  onExpand,
  isExpanded,
}: {
  preset: LocalPreset;
  onDelete: (id: number) => void;
  onClone: (id: number) => void;
  onEdit: (id: number) => void;
  onExport: (id: number, name: string) => void;
  onExpand: (id: number | null) => void;
  isExpanded: boolean;
}) {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();

  const material = preset.filament_type || parseMaterialFromName(preset.name);
  const vendor = preset.filament_vendor || parseVendorFromName(preset.name);

  let colourHex: string | null = null;
  let hasExplicitColour = false;
  if (preset.default_filament_colour) {
    try {
      const parsed = JSON.parse(preset.default_filament_colour);
      const raw = Array.isArray(parsed) ? parsed[0] : parsed;
      if (typeof raw === 'string' && /^#?[0-9a-fA-F]{6,8}$/.test(raw.replace('#', ''))) {
        colourHex = raw.replace('#', '').slice(0, 6);
        hasExplicitColour = true;
      }
    } catch {
      const raw = preset.default_filament_colour;
      if (/^#?[0-9a-fA-F]{6,8}$/.test(raw.replace('#', ''))) {
        colourHex = raw.replace('#', '').slice(0, 6);
        hasExplicitColour = true;
      }
    }
  }
  if (!colourHex && material) {
    colourHex = FILAMENT_TYPE_COLORS[material.toUpperCase()] || null;
  }

  return (
    <Card className="bg-bambu-dark border-bambu-dark-tertiary hover:border-bambu-dark-tertiary/80 transition-colors">
      <CardContent className="p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              {preset.preset_type === 'filament' && (
                <div
                  className={`w-4 h-4 rounded-full border border-black/20 flex-shrink-0 ${
                    !hasExplicitColour && !colourHex ? 'opacity-25' : !hasExplicitColour ? 'opacity-50' : ''
                  }`}
                  style={{ backgroundColor: colourHex ? `#${colourHex}` : '#666' }}
                />
              )}
              {preset.preset_type === 'process' && (
                <Layers className="w-3.5 h-3.5 text-blue-400 flex-shrink-0" />
              )}
              {preset.preset_type === 'printer' && (
                <Settings2 className="w-3.5 h-3.5 text-orange-400 flex-shrink-0" />
              )}
              <span className="text-sm font-medium text-white truncate" title={preset.name}>
                {preset.name}
              </span>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              {material && (
                <span className="text-xs px-1.5 py-0.5 rounded bg-bambu-green/20 text-bambu-green">
                  {material}
                </span>
              )}
              {vendor && (
                <span className="text-xs text-bambu-gray">{vendor}</span>
              )}
              <span className="text-xs px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-500/20 text-blue-700 dark:text-blue-400">
                {preset.source === 'clone' ? t('profiles.localProfiles.cloneBadge', 'Kopie') : t('profiles.localProfiles.badge', 'Lokal')}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-1 flex-shrink-0">
            {/* Bearbeiten */}
            {hasPermission('settings:update') && (
              <button
                type="button"
                onClick={() => onEdit(preset.id)}
                className="p-1 text-bambu-gray hover:text-bambu-green transition-colors"
                title={t('profiles.localProfiles.edit', 'Profil bearbeiten')}
              >
                <Pencil className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Klonen */}
            {hasPermission('settings:update') && (
              <button
                type="button"
                onClick={() => onClone(preset.id)}
                className="p-1 text-bambu-gray hover:text-white transition-colors"
                title={t('profiles.localProfiles.clone', 'Profil duplizieren')}
              >
                <Copy className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Exportieren */}
            <button
              type="button"
              onClick={() => onExport(preset.id, preset.name)}
              className="p-1 text-bambu-gray hover:text-blue-400 transition-colors"
              title={t('profiles.localProfiles.export', 'Als JSON exportieren')}
            >
              <Download className="w-3.5 h-3.5" />
            </button>

            {/* Löschen */}
            {hasPermission('settings:update') && (
              <button
                type="button"
                onClick={() => onDelete(preset.id)}
                className="p-1 text-bambu-gray hover:text-red-600 dark:hover:text-red-400 transition-colors"
                title={t('profiles.localProfiles.delete', 'Löschen')}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            )}

            {/* Details aufklappen */}
            <button
              type="button"
              onClick={() => onExpand(isExpanded ? null : preset.id)}
              className="p-1 text-bambu-gray hover:text-white transition-colors"
              title={isExpanded ? t('common.collapse', 'Einklappen') : t('common.expand', 'Aufklappen')}
            >
              {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          </div>
        </div>

        {/* Ausgeklappte Details */}
        {isExpanded && (
          <div className="mt-3 pt-3 border-t border-bambu-dark-tertiary text-xs space-y-1.5">
            {material && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.filamentType', 'Filament-Typ')}</span>
                <span className="text-white">{material}</span>
              </div>
            )}
            {vendor && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.vendor', 'Hersteller')}</span>
                <span className="text-white">{vendor}</span>
              </div>
            )}
            {preset.nozzle_temp_min != null && preset.nozzle_temp_max != null && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.nozzleTemp', 'Düsentemperatur')}</span>
                <span className="text-white">{preset.nozzle_temp_min}–{preset.nozzle_temp_max}°C</span>
              </div>
            )}
            {preset.filament_cost && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.cost', 'Kosten')}</span>
                <span className="text-white">{preset.filament_cost} €/kg</span>
              </div>
            )}
            {preset.filament_density && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.density', 'Dichte')}</span>
                <span className="text-white">{preset.filament_density} g/cm³</span>
              </div>
            )}
            {preset.pressure_advance && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.pressureAdvance', 'Pressure Advance')}</span>
                <span className="text-white">{preset.pressure_advance}</span>
              </div>
            )}
            {preset.compatible_printers && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.compatiblePrinters', 'Kompatible Drucker')}</span>
                <span className="text-white truncate ml-2">
                  {(() => {
                    try {
                      return JSON.parse(preset.compatible_printers).join(', ');
                    } catch {
                      return preset.compatible_printers;
                    }
                  })()}
                </span>
              </div>
            )}
            {preset.inherits && preset.inherits !== preset.name && (
              <div className="flex justify-between">
                <span className="text-bambu-gray">{t('profiles.localProfiles.inheritsFrom', 'Erbt von')}</span>
                <span className="text-white truncate ml-2">{preset.inherits}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-bambu-gray">{t('profiles.localProfiles.source', 'Herkunft')}</span>
              <span className="text-white capitalize">{preset.source}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ============================================================================
// CREATE PRESET MODAL
// ============================================================================

function CreatePresetModal({
  isOpen,
  onClose,
  onCreated,
}: {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (preset: LocalPreset) => void;
}) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [presetType, setPresetType] = useState<'filament' | 'process'>('filament');
  const [name, setName] = useState('');
  const [selectedTemplateId, setSelectedTemplateId] = useState<string>('');

  const { data: templatesData, isLoading: templatesLoading } = useQuery({
    queryKey: ['localPresetTemplates'],
    queryFn: () => api.getLocalPresetTemplates(),
    enabled: isOpen,
  });

  const availableTemplates = useMemo(() => {
    if (!templatesData) return [];
    return presetType === 'filament' ? templatesData.filament : templatesData.process;
  }, [templatesData, presetType]);

  const createMutation = useMutation({
    mutationFn: async () => {
      let setting: Record<string, unknown> = {};
      const chosenTpl = availableTemplates.find((t) => t.id === selectedTemplateId);
      if (chosenTpl) {
        setting = JSON.parse(JSON.stringify(chosenTpl.setting));
        setting.name = name.trim();
      } else {
        setting = {
          type: presetType,
          name: name.trim(),
          from: 'system',
        };
      }
      return api.createLocalPreset({
        name: name.trim(),
        preset_type: presetType,
        setting,
      });
    },
    onSuccess: (res) => {
      showToast(t('profiles.localProfiles.toast.created', 'Profil erfolgreich erstellt'));
      onCreated(res);
      onClose();
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-xl max-w-lg w-full p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-4 pb-3 border-b border-bambu-dark-tertiary">
          <div className="flex items-center gap-2">
            <Plus className="w-5 h-5 text-bambu-green" />
            <h3 className="text-base font-semibold text-white">
              {t('profiles.localProfiles.modal.createTitle', 'Neues Profil anlegen')}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-bambu-gray hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          {/* Typauswahl */}
          <div>
            <label className="block text-xs font-medium text-bambu-gray mb-1.5">
              {t('profiles.localProfiles.modal.typeLabel', 'Profiltyp')}
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => {
                  setPresetType('filament');
                  setSelectedTemplateId('');
                }}
                className={`flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-sm font-medium border transition-colors ${
                  presetType === 'filament'
                    ? 'border-bambu-green bg-bambu-green/10 text-white'
                    : 'border-bambu-dark-tertiary bg-bambu-dark text-bambu-gray hover:text-white'
                }`}
              >
                <Droplet className="w-4 h-4 text-bambu-green" />
                {t('profiles.localProfiles.filament', 'Filament')}
              </button>
              <button
                type="button"
                onClick={() => {
                  setPresetType('process');
                  setSelectedTemplateId('');
                }}
                className={`flex items-center justify-center gap-2 py-2 px-3 rounded-lg text-sm font-medium border transition-colors ${
                  presetType === 'process'
                    ? 'border-blue-500 bg-blue-500/10 text-white'
                    : 'border-bambu-dark-tertiary bg-bambu-dark text-bambu-gray hover:text-white'
                }`}
              >
                <Layers className="w-4 h-4 text-blue-400" />
                {t('profiles.localProfiles.process', 'Druckprozess')}
              </button>
            </div>
          </div>

          {/* Basis-Vorlage auswählen */}
          <div>
            <label className="block text-xs font-medium text-bambu-gray mb-1.5">
              {t('profiles.localProfiles.modal.templateLabel', 'Basis-Vorlage (Voreinstellung)')}
            </label>
            {templatesLoading ? (
              <div className="flex items-center gap-2 text-xs text-bambu-gray py-2">
                <Loader2 className="w-4 h-4 animate-spin text-bambu-green" />
                Lade Vorlagen...
              </div>
            ) : (
              <select
                value={selectedTemplateId}
                onChange={(e) => {
                  const val = e.target.value;
                  setSelectedTemplateId(val);
                  const found = availableTemplates.find((t) => t.id === val);
                  if (found && !name) {
                    setName(`${found.name} (Mein Profil)`);
                  }
                }}
                className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white focus:outline-none focus:border-bambu-green"
              >
                <option value="">-- Ohne Vorlage (Standardwerte) --</option>
                {availableTemplates.map((tpl) => (
                  <option key={tpl.id} value={tpl.id}>
                    {tpl.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Profilname */}
          <div>
            <label className="block text-xs font-medium text-bambu-gray mb-1.5">
              {t('profiles.localProfiles.modal.nameLabel', 'Profilname')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="z. B. Mein Bambu PLA Matt 0.20mm"
              className="w-full px-3 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-bambu-dark-tertiary">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', 'Abbrechen')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => createMutation.mutate()}
            disabled={!name.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            {t('profiles.localProfiles.modal.createBtn', 'Profil anlegen')}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// EDIT PRESET MODAL
// ============================================================================

function EditPresetModal({
  presetId,
  isOpen,
  onClose,
  onSaved,
}: {
  presetId: number | null;
  isOpen: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState<'form' | 'json'>('form');
  const [profileName, setProfileName] = useState('');
  const [setting, setSetting] = useState<Record<string, unknown>>({});
  const [jsonText, setJsonText] = useState('');
  const [jsonError, setJsonError] = useState<string | null>(null);

  const { data: detail, isLoading } = useQuery({
    queryKey: ['localPresetDetail', presetId],
    queryFn: () => (presetId ? api.getLocalPresetDetail(presetId) : null),
    enabled: isOpen && presetId !== null,
  });

  // Details in Formularstate übernehmen (Effekt: setState darf nicht beim Rendern laufen)
  useEffect(() => {
    if (detail) {
      setProfileName(detail.name);
      setSetting(detail.setting || {});
      setJsonText(JSON.stringify(detail.setting || {}, null, 2));
      setJsonError(null);
    }
  }, [detail]);

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!presetId) return;
      let finalSetting = setting;
      if (activeTab === 'json') {
        try {
          finalSetting = JSON.parse(jsonText);
        } catch {
          throw new Error('Ungültiges JSON-Format');
        }
      }
      return api.updateLocalPreset(presetId, {
        name: profileName.trim(),
        setting: finalSetting,
      });
    },
    onSuccess: () => {
      showToast(t('profiles.localProfiles.toast.updated', 'Profil erfolgreich aktualisiert'));
      onSaved();
      onClose();
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  if (!isOpen || !presetId) return null;

  const isFilament = detail?.preset_type === 'filament';
  const isProcess = detail?.preset_type === 'process';

  // Hilfsfunktion zur einfachen Aktualisierung von Formularfeldern
  const updateSettingKey = (key: string, val: unknown) => {
    setSetting((prev) => {
      const next = { ...prev, [key]: val };
      setJsonText(JSON.stringify(next, null, 2));
      return next;
    });
  };

  const getArrayFirst = (key: string, fallback = ''): string => {
    const val = setting[key];
    if (Array.isArray(val) && val.length > 0) return String(val[0]);
    if (typeof val === 'string' || typeof val === 'number') return String(val);
    return fallback;
  };

  const setArrayFirst = (key: string, val: string) => {
    updateSettingKey(key, [val]);
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-xl max-w-2xl w-full p-6 shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between pb-3 border-b border-bambu-dark-tertiary">
          <div className="flex items-center gap-2">
            <Pencil className="w-5 h-5 text-bambu-green" />
            <h3 className="text-base font-semibold text-white">
              {t('profiles.localProfiles.modal.editTitle', 'Profil bearbeiten')}
            </h3>
            {detail && (
              <span className="text-xs px-2 py-0.5 rounded bg-bambu-dark text-bambu-gray">
                {detail.preset_type}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-bambu-gray hover:text-white transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Tab-Leiste */}
        <div className="flex gap-2 my-3 border-b border-bambu-dark-tertiary pb-2">
          <button
            type="button"
            onClick={() => setActiveTab('form')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeTab === 'form'
                ? 'bg-bambu-green/20 text-bambu-green'
                : 'text-bambu-gray hover:text-white'
            }`}
          >
            <Sliders className="w-3.5 h-3.5" />
            {t('profiles.localProfiles.modal.tabForm', 'Parameter-Editor')}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('json')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
              activeTab === 'json'
                ? 'bg-bambu-green/20 text-bambu-green'
                : 'text-bambu-gray hover:text-white'
            }`}
          >
            <Code className="w-3.5 h-3.5" />
            {t('profiles.localProfiles.modal.tabJson', 'Experten-Modus (JSON)')}
          </button>
        </div>

        {/* Inhalt */}
        <div className="flex-1 overflow-y-auto pr-1 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="w-6 h-6 animate-spin text-bambu-green" />
            </div>
          ) : (
            <>
              {/* Profilname immer oben */}
              <div>
                <label className="block text-xs font-medium text-bambu-gray mb-1">
                  {t('profiles.localProfiles.modal.nameLabel', 'Profilname')}
                </label>
                <input
                  type="text"
                  value={profileName}
                  onChange={(e) => setProfileName(e.target.value)}
                  className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white focus:outline-none focus:border-bambu-green"
                />
              </div>

              {/* Formular-Ansicht */}
              {activeTab === 'form' && (
                <div className="space-y-4">
                  {/* Filament-Felder */}
                  {isFilament && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Filament-Typ
                        </label>
                        <input
                          type="text"
                          value={getArrayFirst('filament_type', 'PLA')}
                          onChange={(e) => setArrayFirst('filament_type', e.target.value.toUpperCase())}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                          placeholder="z. B. PLA, PETG, ABS"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Hersteller (Vendor)
                        </label>
                        <input
                          type="text"
                          value={getArrayFirst('filament_vendor', 'Generic')}
                          onChange={(e) => setArrayFirst('filament_vendor', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                          placeholder="z. B. Bambu Lab, Sunlu"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Düsentemperatur (°C)
                        </label>
                        <input
                          type="number"
                          value={getArrayFirst('nozzle_temperature', '220')}
                          onChange={(e) => setArrayFirst('nozzle_temperature', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Düsentemperatur Erste Schicht (°C)
                        </label>
                        <input
                          type="number"
                          value={getArrayFirst('nozzle_temperature_initial_layer', '220')}
                          onChange={(e) => setArrayFirst('nozzle_temperature_initial_layer', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Druckbett-Temperatur (°C)
                        </label>
                        <input
                          type="number"
                          value={getArrayFirst('hot_plate_temp', '55')}
                          onChange={(e) => setArrayFirst('hot_plate_temp', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Max. Volumen-Geschwindigkeit (mm³/s)
                        </label>
                        <input
                          type="number"
                          step="0.5"
                          value={getArrayFirst('filament_max_volumetric_speed', '15')}
                          onChange={(e) => setArrayFirst('filament_max_volumetric_speed', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Kosten (€/kg)
                        </label>
                        <input
                          type="number"
                          step="0.5"
                          value={getArrayFirst('filament_cost', '20')}
                          onChange={(e) => setArrayFirst('filament_cost', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Dichte (g/cm³)
                        </label>
                        <input
                          type="number"
                          step="0.01"
                          value={getArrayFirst('filament_density', '1.24')}
                          onChange={(e) => setArrayFirst('filament_density', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                    </div>
                  )}

                  {/* Prozess-Felder */}
                  {isProcess && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Schichthöhe (mm)
                        </label>
                        <input
                          type="number"
                          step="0.02"
                          value={String(setting.layer_height || '0.2')}
                          onChange={(e) => updateSettingKey('layer_height', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Schichthöhe Erste Schicht (mm)
                        </label>
                        <input
                          type="number"
                          step="0.02"
                          value={String(setting.initial_layer_print_height || '0.2')}
                          onChange={(e) => updateSettingKey('initial_layer_print_height', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Wandlinien (Wall Loops)
                        </label>
                        <input
                          type="number"
                          value={String(setting.wall_loops || '2')}
                          onChange={(e) => updateSettingKey('wall_loops', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Infill-Dichte
                        </label>
                        <input
                          type="text"
                          value={String(setting.sparse_infill_density || '15%')}
                          onChange={(e) => updateSettingKey('sparse_infill_density', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                          placeholder="z. B. 15%"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Infill-Muster
                        </label>
                        <select
                          value={String(setting.sparse_infill_pattern || 'grid')}
                          onChange={(e) => updateSettingKey('sparse_infill_pattern', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        >
                          <option value="grid">Grid (Gitter)</option>
                          <option value="gyroid">Gyroid</option>
                          <option value="honeycomb">Honeycomb (Wabe)</option>
                          <option value="cubic">Cubic</option>
                          <option value="rectilinear">Rectilinear</option>
                          <option value="line">Line</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Stützstruktur aktivieren
                        </label>
                        <select
                          value={String(setting.enable_support ?? '0')}
                          onChange={(e) => updateSettingKey('enable_support', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        >
                          <option value="0">Aus (Keine Stützen)</option>
                          <option value="1">Aktiviert</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Baumstützen-Wände (Tree Wall Count)
                        </label>
                        <select
                          value={String(setting.tree_support_wall_count ?? '0')}
                          onChange={(e) => updateSettingKey('tree_support_wall_count', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        >
                          <option value="0">0 (Standard OrcaSlicer)</option>
                          <option value="1">1</option>
                          <option value="2">2</option>
                        </select>
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-bambu-gray mb-1">
                          Druckgeschwindigkeit Außenwand (mm/s)
                        </label>
                        <input
                          type="number"
                          value={String(setting.outer_wall_speed || '200')}
                          onChange={(e) => updateSettingKey('outer_wall_speed', e.target.value)}
                          className="w-full px-3 py-1.5 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* JSON-Ansicht */}
              {activeTab === 'json' && (
                <div>
                  <textarea
                    rows={16}
                    value={jsonText}
                    onChange={(e) => {
                      setJsonText(e.target.value);
                      try {
                        const parsed = JSON.parse(e.target.value);
                        setSetting(parsed);
                        setJsonError(null);
                      } catch (err: unknown) {
                        setJsonError(err instanceof Error ? err.message : String(err));
                      }
                    }}
                    className="w-full p-3 bg-bambu-dark font-mono text-xs text-zinc-200 border border-bambu-dark-tertiary rounded-lg focus:outline-none focus:border-bambu-green leading-relaxed"
                  />
                  {jsonError && (
                    <p className="text-xs text-red-400 mt-1 flex items-center gap-1">
                      <AlertCircle className="w-3.5 h-3.5" />
                      JSON-Syntaxfehler: {jsonError}
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-bambu-dark-tertiary">
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('common.cancel', 'Abbrechen')}
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => updateMutation.mutate()}
            disabled={!profileName.trim() || !!jsonError || updateMutation.isPending}
          >
            {updateMutation.isPending ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Check className="w-4 h-4" />
            )}
            {t('common.save', 'Speichern')}
          </Button>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// MAIN LOCAL PROFILES VIEW
// ============================================================================

export function LocalProfilesView() {
  const { t } = useTranslation();
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState<'all' | 'filament' | 'process' | 'printer'>('all');
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editingPresetId, setEditingPresetId] = useState<number | null>(null);

  const { data: presets, isLoading } = useQuery({
    queryKey: ['localPresets'],
    queryFn: () => api.getLocalPresets(),
  });

  const importMutation = useMutation({
    mutationFn: async (files: FileList) => {
      const results = [];
      for (const file of Array.from(files)) {
        const formData = new FormData();
        formData.append('file', file);
        results.push(await api.importLocalPresets(formData));
      }
      return results;
    },
    onSuccess: (results) => {
      queryClient.invalidateQueries({ queryKey: ['localPresets'] });
      queryClient.invalidateQueries({ queryKey: ['slicerPresets'] });
      let totalImported = 0;
      let totalSkipped = 0;
      let totalErrors = 0;
      for (const r of results) {
        totalImported += r.imported;
        totalSkipped += r.skipped;
        totalErrors += r.errors.length;
      }

      if (totalImported > 0) {
        showToast(t('profiles.localProfiles.toast.importSuccess', { count: totalImported }));
      }
      if (totalSkipped > 0) {
        showToast(t('profiles.localProfiles.toast.importSkipped', { count: totalSkipped }), 'warning');
      }
      if (totalErrors > 0) {
        showToast(t('profiles.localProfiles.toast.importError', { count: totalErrors }), 'error');
      }
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  const cloneMutation = useMutation({
    mutationFn: (id: number) => api.cloneLocalPreset(id),
    onSuccess: (cloned) => {
      queryClient.invalidateQueries({ queryKey: ['localPresets'] });
      queryClient.invalidateQueries({ queryKey: ['slicerPresets'] });
      showToast(t('profiles.localProfiles.toast.cloned', 'Profil "{{name}}" dupliziert', { name: cloned.name }));
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteLocalPreset(id),
    onSuccess: (_, id) => {
      queryClient.setQueryData<LocalPresetsResponse>(['localPresets'], (old) => {
        if (!old) return old;
        return {
          filament: old.filament.filter((p) => p.id !== id),
          printer: old.printer.filter((p) => p.id !== id),
          process: old.process.filter((p) => p.id !== id),
        };
      });
      queryClient.invalidateQueries({ queryKey: ['localPresets'] });
      queryClient.invalidateQueries({ queryKey: ['slicerPresets'] });
      setDeleteConfirm(null);
      showToast(t('profiles.localProfiles.toast.deleted'));
    },
    onError: (err: Error) => {
      showToast(err.message, 'error');
    },
  });

  const handleExport = async (id: number, name: string) => {
    try {
      const detail = await api.getLocalPresetDetail(id);
      const blob = new Blob([JSON.stringify(detail.setting, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${name.replace(/[^a-zA-Z0-9_-]/g, '_')}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast(t('profiles.localProfiles.toast.exported', 'Profil exportiert'));
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : String(err), 'error');
    }
  };

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      importMutation.mutate(files);
    },
    [importMutation],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      handleFiles(e.dataTransfer.files);
    },
    [handleFiles],
  );

  const filterPresets = useCallback(
    (list: LocalPreset[]) => {
      if (!searchQuery) return list;
      const q = searchQuery.toLowerCase();
      return list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          p.filament_type?.toLowerCase().includes(q) ||
          p.filament_vendor?.toLowerCase().includes(q),
      );
    },
    [searchQuery],
  );

  const filaments = useMemo(
    () => filterPresets(presets?.filament || []),
    [presets?.filament, filterPresets],
  );
  const printers = useMemo(
    () => filterPresets(presets?.printer || []),
    [presets?.printer, filterPresets],
  );
  const processes = useMemo(
    () => filterPresets(presets?.process || []),
    [presets?.process, filterPresets],
  );

  const totalCount = filaments.length + printers.length + processes.length;
  const hasAnyPresets =
    (presets?.filament?.length ?? 0) +
      (presets?.printer?.length ?? 0) +
      (presets?.process?.length ?? 0) >
    0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Loader2 className="w-8 h-8 text-bambu-green animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Action Bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Kategorie-Filter */}
        <div className="flex items-center gap-1.5 p-1 bg-bambu-dark rounded-lg border border-bambu-dark-tertiary">
          <button
            type="button"
            onClick={() => setSelectedCategory('all')}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              selectedCategory === 'all'
                ? 'bg-bambu-dark-secondary text-white shadow-sm'
                : 'text-bambu-gray hover:text-white'
            }`}
          >
            {t('profiles.localProfiles.tabs.all', 'Alle')} ({totalCount})
          </button>
          <button
            type="button"
            onClick={() => setSelectedCategory('filament')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              selectedCategory === 'filament'
                ? 'bg-bambu-green/20 text-bambu-green shadow-sm'
                : 'text-bambu-gray hover:text-white'
            }`}
          >
            <Droplet className="w-3.5 h-3.5" />
            {t('profiles.localProfiles.filament', 'Filamente')} ({filaments.length})
          </button>
          <button
            type="button"
            onClick={() => setSelectedCategory('process')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              selectedCategory === 'process'
                ? 'bg-blue-500/20 text-blue-400 shadow-sm'
                : 'text-bambu-gray hover:text-white'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            {t('profiles.localProfiles.process', 'Prozesse')} ({processes.length})
          </button>
          <button
            type="button"
            onClick={() => setSelectedCategory('printer')}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
              selectedCategory === 'printer'
                ? 'bg-orange-500/20 text-orange-400 shadow-sm'
                : 'text-bambu-gray hover:text-white'
            }`}
          >
            <Settings2 className="w-3.5 h-3.5" />
            {t('profiles.localProfiles.printer', 'Drucker')} ({printers.length})
          </button>
        </div>

        {/* Neues Profil Button */}
        {hasPermission('settings:update') && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => setCreateModalOpen(true)}
            className="flex items-center gap-1.5 shadow-sm"
          >
            <Plus className="w-4 h-4" />
            {t('profiles.localProfiles.createBtn', 'Neues Profil')}
          </Button>
        )}
      </div>

      {/* Import Zone */}
      {hasPermission('settings:update') && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={`relative border-2 border-dashed rounded-lg p-5 text-center transition-colors ${
            isDragging
              ? 'border-bambu-green bg-bambu-green/10'
              : 'border-bambu-dark-tertiary hover:border-bambu-gray'
          }`}
        >
          <input
            type="file"
            accept=".json,.zip,.orca_filament,.bbscfg,.bbsflmt"
            multiple
            className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
            onChange={(e) => handleFiles(e.target.files)}
          />
          {importMutation.isPending ? (
            <div className="flex items-center justify-center gap-2">
              <Loader2 className="w-5 h-5 text-bambu-green animate-spin" />
              <span className="text-bambu-gray">{t('profiles.localProfiles.importing')}</span>
            </div>
          ) : (
            <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
              <Upload className="w-6 h-6 text-bambu-green flex-shrink-0" />
              <div className="text-left">
                <p className="text-sm text-white font-medium">
                  {t('profiles.localProfiles.import', 'OrcaSlicer / Bambu Studio Profile importieren')}
                </p>
                <p className="text-xs text-bambu-gray">
                  {t('profiles.localProfiles.importDesc', 'Dateien (.json, .zip, .orca_filament, .bbscfg) hier ablegen oder anklicken')}
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Suchleiste */}
      {hasAnyPresets && (
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-bambu-gray" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('profiles.localProfiles.search', 'Profile nach Name, Material oder Hersteller filtern...')}
            className="w-full pl-9 pr-4 py-2 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg text-sm text-white placeholder-bambu-gray focus:outline-none focus:border-bambu-green"
          />
        </div>
      )}

      {/* Keine Profile vorhanden */}
      {!hasAnyPresets && !isLoading && (
        <div className="text-center py-12">
          <HardDrive className="w-12 h-12 text-bambu-gray mx-auto mb-3 opacity-50" />
          <p className="text-bambu-gray">{t('profiles.localProfiles.noPresets', 'Noch keine lokalen Profile vorhanden.')}</p>
          <p className="text-xs text-bambu-gray/60 mt-1">
            Klicke auf „Neues Profil“ oder ziehe eine Profil-Datei in das Import-Feld.
          </p>
        </div>
      )}

      {/* Suche ohne Treffer */}
      {hasAnyPresets && totalCount === 0 && !isLoading && (
        <div className="text-center py-12">
          <Search className="w-12 h-12 text-bambu-gray mx-auto mb-3 opacity-50" />
          <p className="text-bambu-gray">{t('profiles.localProfiles.noSearchResults', 'Keine Profile gefunden.')}</p>
        </div>
      )}

      {/* Profil-Listen */}
      {totalCount > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Filamente */}
          {(selectedCategory === 'all' || selectedCategory === 'filament') && filaments.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Droplet className="w-4 h-4 text-bambu-green" />
                <h3 className="text-sm font-medium text-white">
                  {t('profiles.localProfiles.filament', 'Filamente')}
                </h3>
                <span className="text-xs text-bambu-gray">({filaments.length})</span>
              </div>
              <div className="space-y-2">
                {filaments.map((p) => (
                  <PresetCard
                    key={p.id}
                    preset={p}
                    onDelete={(id) => setDeleteConfirm(id)}
                    onClone={(id) => cloneMutation.mutate(id)}
                    onEdit={(id) => setEditingPresetId(id)}
                    onExport={handleExport}
                    onExpand={setExpandedId}
                    isExpanded={expandedId === p.id}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Prozesse */}
          {(selectedCategory === 'all' || selectedCategory === 'process') && processes.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Layers className="w-4 h-4 text-blue-400" />
                <h3 className="text-sm font-medium text-white">
                  {t('profiles.localProfiles.process', 'Druckprozesse')}
                </h3>
                <span className="text-xs text-bambu-gray">({processes.length})</span>
              </div>
              <div className="space-y-2">
                {processes.map((p) => (
                  <PresetCard
                    key={p.id}
                    preset={p}
                    onDelete={(id) => setDeleteConfirm(id)}
                    onClone={(id) => cloneMutation.mutate(id)}
                    onEdit={(id) => setEditingPresetId(id)}
                    onExport={handleExport}
                    onExpand={setExpandedId}
                    isExpanded={expandedId === p.id}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Drucker */}
          {(selectedCategory === 'all' || selectedCategory === 'printer') && printers.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-3">
                <Settings2 className="w-4 h-4 text-orange-400" />
                <h3 className="text-sm font-medium text-white">
                  {t('profiles.localProfiles.printer', 'Drucker')}
                </h3>
                <span className="text-xs text-bambu-gray">({printers.length})</span>
              </div>
              <div className="space-y-2">
                {printers.map((p) => (
                  <PresetCard
                    key={p.id}
                    preset={p}
                    onDelete={(id) => setDeleteConfirm(id)}
                    onClone={(id) => cloneMutation.mutate(id)}
                    onEdit={(id) => setEditingPresetId(id)}
                    onExport={handleExport}
                    onExpand={setExpandedId}
                    isExpanded={expandedId === p.id}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Modal: Neues Profil erstellen */}
      <CreatePresetModal
        isOpen={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        onCreated={() => {
          queryClient.invalidateQueries({ queryKey: ['localPresets'] });
          queryClient.invalidateQueries({ queryKey: ['slicerPresets'] });
        }}
      />

      {/* Modal: Profil bearbeiten */}
      <EditPresetModal
        presetId={editingPresetId}
        isOpen={editingPresetId !== null}
        onClose={() => setEditingPresetId(null)}
        onSaved={() => {
          queryClient.invalidateQueries({ queryKey: ['localPresets'] });
          queryClient.invalidateQueries({ queryKey: ['slicerPresets'] });
        }}
      />

      {/* Modal: Löschen bestätigen */}
      {deleteConfirm !== null && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-bambu-dark-secondary border border-bambu-dark-tertiary rounded-xl p-6 max-w-sm w-full shadow-2xl">
            <div className="flex items-center gap-2 mb-3">
              <AlertCircle className="w-5 h-5 text-red-500" />
              <h3 className="text-white font-medium">{t('profiles.localProfiles.deleteConfirmTitle', 'Profil löschen')}</h3>
            </div>
            <p className="text-sm text-bambu-gray mb-4">
              {t('profiles.localProfiles.deleteConfirm', 'Möchtest du dieses Profil wirklich endgültig löschen?')}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" size="sm" onClick={() => setDeleteConfirm(null)}>
                {t('common.cancel', 'Abbrechen')}
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => deleteMutation.mutate(deleteConfirm)}
                disabled={deleteMutation.isPending}
              >
                {deleteMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                {t('common.delete', 'Löschen')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
