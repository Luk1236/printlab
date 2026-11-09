/**
 * Kundenportal & Sofort-Kalkulator API Endpunkte (Phase 7).
 */

import { API_BASE, authToken, request } from './core';
import type { InstantQuote, MaterialProfile, MeshAnalysisResult } from './types_finance';

export const portalEndpoints = {
  /**
   * Verfügbare Materialien mit Dichten und Preisen laden.
   */
  getMaterials: () =>
    request<{ materials: Record<string, MaterialProfile> }>('/portal/materials'),

  /**
   * 3D-Modell (STL, 3MF, OBJ) hochladen und Geometrie/Volumen analysieren.
   */
  analyzeModel: async (file: File): Promise<MeshAnalysisResult> => {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/portal/analyze-model`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },

  /**
   * 3D-Modell mit Druckparametern hochladen und Sofortangebot generieren.
   */
  quoteFromModel: async (
    file: File,
    params: {
      filament_type: string;
      infill_percent: number;
      layer_height: number;
      quantity: number;
      customer_name?: string;
      customer_address?: string;
    }
  ): Promise<InstantQuote> => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('filament_type', params.filament_type);
    formData.append('infill_percent', String(params.infill_percent));
    formData.append('layer_height', String(params.layer_height));
    formData.append('quantity', String(params.quantity));
    if (params.customer_name) {
      formData.append('customer_name', params.customer_name);
    }
    if (params.customer_address) {
      formData.append('customer_address', params.customer_address);
    }

    const headers: Record<string, string> = {};
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`;
    }
    const response = await fetch(`${API_BASE}/portal/quote-from-model`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${response.status}`);
    }
    return response.json();
  },

  /**
   * Gespeichertes Sofortangebot abrufen.
   */
  getPortalQuote: (quoteId: string) =>
    request<InstantQuote>(`/portal/quote/${quoteId}`),

  /**
   * Stripe-Checkout Session anfordern.
   */
  createCheckout: (quoteId: string, successUrl: string, cancelUrl: string) =>
    request<{ url: string; session_id: string }>('/portal/checkout', {
      method: 'POST',
      body: JSON.stringify({
        quote_id: quoteId,
        success_url: successUrl,
        cancel_url: cancelUrl,
      }),
    }),

  /**
   * URL für Lieferschein-PDF Download.
   */
  getDeliveryNotePdfUrl: (quoteId: string, lang = 'de') =>
    `${API_BASE}/portal/delivery-note/${quoteId}/pdf?lang=${lang}`,

  /**
   * URL für Thermo-Paket-Etikett PDF Download (100x150 mm oder 62x29 mm).
   */
  getShippingLabelPdfUrl: (quoteId: string, format = '100x150') =>
    `${API_BASE}/portal/shipping-label/${quoteId}/pdf?format=${format}`,
  /**
   * Live-Auftragsstatus per Tracking-Token abrufen.
   */
  getTrackingStatus: (token: string) =>
    request<{
      token: string;
      order_number: string;
      order_status: string;
      current_stage: { stage: string; title: string; desc: string };
      stages: Array<{ stage: string; title: string; desc: string }>;
      part_name: string;
      quantity: number;
      material: string;
      printer_name: string;
      progress_percent: number;
      current_layer: number;
      total_layers: number;
      remaining_minutes: number;
      estimated_completion: string;
      carrier: string;
      tracking_number: string;
      is_express: boolean;
    }>('/portal/tracking/' + encodeURIComponent(token)),

  /**
   * Mengenstaffelpreise und Nachbearbeitungsoptionen berechnen.
   */
  calculateTiers: (payload: {
    base_unit_price_cents: number;
    quantity: number;
    selected_options?: string[];
    option_quantities?: Record<string, number>;
  }) =>
    request<{
      pricing_tier: {
        base_unit_price_cents: number;
        quantity: number;
        discount_percent: number;
        active_tier_name: string;
        unit_price_cents: number;
        unit_price_eur: number;
        total_parts_cents: number;
        total_parts_eur: number;
        savings_cents: number;
        savings_eur: number;
        tiers_overview: Array<Record<string, unknown>>;
      };
      post_processing: Array<Record<string, unknown>>;
      options_total_cents: number;
      options_total_eur: number;
      is_express: boolean;
      net_total_cents: number;
      net_total_eur: number;
      vat_19_cents: number;
      vat_19_eur: number;
      gross_total_cents: number;
      gross_total_eur: number;
    }>('/portal/pricing/calculate-tiers', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
};
