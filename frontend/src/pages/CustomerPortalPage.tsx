/**
 * Kundenportal 2.0 & Sofort-Kalkulator (Phase 7).
 *
 * Öffentlicher und interner 3D-Druck-Kalkulator:
 * - Drag-and-Drop 3D-Modell-Upload (STL, 3MF, OBJ)
 * - Automatische Mesh-Analyse (Volumen cm³, Bounding-Box mm, Bauraumprüfung)
 * - Dynamische Material- und Staffelpreise
 * - PDF-Export für DIN A4 Lieferschein und Thermo-Versandetiketten (100x150 & 62x29)
 * - Stripe Checkout Integration
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Box,
  CheckCircle2,
  Clock,
  CreditCard,
  Download,
  FileText,
  Layers,
  Printer,
  QrCode,
  RefreshCw,
  Scale,
  ShieldCheck,
  Sparkles,
  Tag,
  Upload,
} from 'lucide-react';
import { api, type InstantQuote, type MaterialProfile, type MeshAnalysisResult } from '../api/client';
import { Button } from '../components/Button';
import { Card, CardContent, CardHeader } from '../components/Card';
import { useToast } from '../contexts/ToastContext';

export function CustomerPortalPage() {
  const [searchParams] = useSearchParams();
  const quoteIdParam = searchParams.get('quote') || '';
  const statusParam = searchParams.get('status') || '';
  const { addToast } = useToast();

  // State
  const [materials, setMaterials] = useState<Record<string, MaterialProfile>>({
    PLA: { name: 'Bambu PLA Basic', density: 1.24, cost_per_kg: 24.9 },
    PETG: { name: 'Bambu PETG HF', density: 1.27, cost_per_kg: 26.9 },
    ABS: { name: 'Bambu ABS', density: 1.04, cost_per_kg: 29.9 },
    ASA: { name: 'Bambu ASA (UV-beständig)', density: 1.05, cost_per_kg: 32.9 },
    TPU: { name: 'Bambu TPU 95A (Flexibel)', density: 1.21, cost_per_kg: 39.9 },
    'PLA-CF': { name: 'Bambu PLA-CF (Carbon)', density: 1.25, cost_per_kg: 44.9 },
  });

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [analyzing, setAnalyzing] = useState<boolean>(false);
  const [calculating, setCalculating] = useState<boolean>(false);
  const [analysis, setAnalysis] = useState<MeshAnalysisResult | null>(null);
  const [quote, setQuote] = useState<InstantQuote | null>(null);

  // Parameter
  const [filamentType, setFilamentType] = useState<string>('PLA');
  const [infillPercent, setInfillPercent] = useState<number>(15);
  const [layerHeight, setLayerHeight] = useState<number>(0.2);
  const [quantity, setQuantity] = useState<number>(1);
  const [customerName, setCustomerName] = useState<string>('');
  const [customerAddress, setCustomerAddress] = useState<string>('');

  // Stripe Checkout
  const [checkoutLoading, setCheckoutLoading] = useState<boolean>(false);

  // Initial Materialien laden
  useEffect(() => {
    api
      .getMaterials()
      .then((res) => {
        if (res?.materials && Object.keys(res.materials).length > 0) {
          setMaterials(res.materials);
        }
      })
      .catch((err) => {
        console.warn('Materialien konnten nicht aktualisiert werden:', err);
      });
  }, []);

  // Falls ein bestehender Quote-Parameter in der URL übergeben wurde
  useEffect(() => {
    if (quoteIdParam) {
      api
        .getQuote(quoteIdParam)
        .then((storedQuote) => {
          setQuote(storedQuote);
          if (storedQuote.filament_type) setFilamentType(storedQuote.filament_type);
          if (storedQuote.infill_percent) setInfillPercent(storedQuote.infill_percent);
          if (storedQuote.layer_height_mm) setLayerHeight(storedQuote.layer_height_mm);
          if (storedQuote.quantity) setQuantity(storedQuote.quantity);
          if (storedQuote.customer_name) setCustomerName(storedQuote.customer_name);
          if (storedQuote.customer_address) setCustomerAddress(storedQuote.customer_address);
          if (storedQuote.analysis) setAnalysis(storedQuote.analysis);
        })
        .catch(() => {
          // Ignorieren, falls nicht gefunden
        });
    }
  }, [quoteIdParam]);

  // Datei-Upload & Mesh-Analyse
  const handleFileChange = useCallback(
    async (file: File) => {
      setSelectedFile(file);
      setAnalyzing(true);
      try {
        const result = await api.analyzeModel(file);
        setAnalysis(result);
        addToast({
          type: 'success',
          message: `3D-Modell "${file.name}" erfolgreich analysiert: ${result.volume_cm3.toFixed(1)} cm³`,
        });

        // Automatisch sofort kalkulieren
        setCalculating(true);
        const instantQuote = await api.quoteFromModel(file, {
          filament_type: filamentType,
          infill_percent: infillPercent,
          layer_height: layerHeight,
          quantity: quantity,
          customer_name: customerName,
          customer_address: customerAddress,
        });
        setQuote(instantQuote);
      } catch (err: any) {
        addToast({
          type: 'error',
          message: err.message || 'Fehler bei der 3D-Modellanalyse.',
        });
      } finally {
        setAnalyzing(false);
        setCalculating(false);
      }
    },
    [filamentType, infillPercent, layerHeight, quantity, customerName, customerAddress, addToast]
  );

  // Manuelle Neukalkulation bei Parameteränderung
  const handleRecalculate = async () => {
    if (!selectedFile) {
      addToast({
        type: 'warning',
        message: 'Bitte laden Sie zuerst ein 3D-Modell (STL, 3MF, OBJ) hoch.',
      });
      return;
    }
    setCalculating(true);
    try {
      const instantQuote = await api.quoteFromModel(selectedFile, {
        filament_type: filamentType,
        infill_percent: infillPercent,
        layer_height: layerHeight,
        quantity: quantity,
        customer_name: customerName,
        customer_address: customerAddress,
      });
      setQuote(instantQuote);
      addToast({
        type: 'success',
        message: 'Angebot aktualisiert.',
      });
    } catch (err: any) {
      addToast({
        type: 'error',
        message: err.message || 'Kalkulationsfehler.',
      });
    } finally {
      setCalculating(false);
    }
  };

  // Stripe Checkout
  const handleCheckout = async () => {
    if (!quote) return;
    setCheckoutLoading(true);
    try {
      const currentUrl = window.location.origin + window.location.pathname;
      const successUrl = `${currentUrl}?quote=${quote.quote_id}&status=success`;
      const cancelUrl = `${currentUrl}?quote=${quote.quote_id}&status=cancelled`;

      const checkout = await api.createCheckout(quote.quote_id, successUrl, cancelUrl);
      if (checkout?.url) {
        window.location.href = checkout.url;
      } else {
        throw new Error('Keine Zahlungs-URL vom Server erhalten.');
      }
    } catch (err: any) {
      addToast({
        type: 'error',
        message: err.message || 'Stripe Checkout konnte nicht gestartet werden.',
      });
    } finally {
      setCheckoutLoading(false);
    }
  };

  const getDiscountTierLabel = (qty: number) => {
    if (qty >= 25) return '15% Mengenrabatt aktiv';
    if (qty >= 10) return '10% Mengenrabatt aktiv';
    if (qty >= 5) return '5% Mengenrabatt aktiv';
    return 'Staffelrabatt ab 5 Stück';
  };

  return (
    <div className="min-h-screen bg-bambu-darkest text-white p-4 md:p-8">
      <div className="max-w-6xl mx-auto space-y-8">
        {/* Banner / Benachrichtigung bei Rückkehr von Stripe */}
        {statusParam === 'success' && (
          <div className="p-4 rounded-lg bg-emerald-500/20 border border-emerald-500/40 flex items-center gap-3">
            <CheckCircle2 className="w-6 h-6 text-emerald-400 shrink-0" />
            <div>
              <div className="font-semibold text-emerald-300">Vielen Dank für Ihre Bestellung!</div>
              <div className="text-sm text-emerald-200/80">
                Die Zahlung wurde erfolgreich bestätigt. Der Druckauftrag ({quoteIdParam}) wurde in unsere Fertigung eingelastet.
              </div>
            </div>
          </div>
        )}

        {statusParam === 'cancelled' && (
          <div className="p-4 rounded-lg bg-amber-500/20 border border-amber-500/40 flex items-center gap-3">
            <AlertTriangle className="w-6 h-6 text-amber-400 shrink-0" />
            <div>
              <div className="font-semibold text-amber-300">Zahlungsvorgang abgebrochen</div>
              <div className="text-sm text-amber-200/80">
                Ihr Angebot bleibt für 60 Minuten gespeichert. Sie können es jederzeit erneut aufrufen und bezahlen.
              </div>
            </div>
          </div>
        )}

        {/* Portal Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-bambu-dark-tertiary pb-6">
          <div>
            <div className="flex items-center gap-2">
              <Sparkles className="w-6 h-6 text-bambu-green" />
              <h1 className="text-2xl md:text-3xl font-bold">PrintLab Kundenportal & Sofort-Kalkulator</h1>
            </div>
            <p className="text-bambu-gray mt-1 text-sm md:text-base">
              Laden Sie Ihr 3D-Modell (STL, 3MF, OBJ) hoch für eine sekundenschnelle Geometrie- & Preiskalkulation.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-bambu-dark border border-bambu-dark-tertiary text-bambu-gray">
              <ShieldCheck className="w-4 h-4 text-bambu-green" />
              Bambu Lab Flottenfertigung
            </span>
            <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-bambu-green/10 border border-bambu-green/30 text-bambu-green">
              Live Preiskalkulation
            </span>
          </div>
        </div>

        {/* Hauptbereich Grid: Links Upload & Parameter, Rechts Zusammenfassung & Aktionen */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          {/* Linke Spalte: Upload & Parameter */}
          <div className="lg:col-span-7 space-y-6">
            {/* 1. 3D Modell Upload Dropzone */}
            <Card>
              <CardHeader className="flex items-center gap-2 font-semibold">
                <Box className="w-5 h-5 text-bambu-green" />
                <span>1. 3D-Modell hochladen (STL, 3MF, OBJ)</span>
              </CardHeader>
              <CardContent className="space-y-4">
                <div
                  role="button"
                  tabIndex={0}
                  aria-label="3D-Modell hochladen (STL, 3MF, OBJ)"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault();
                      document.getElementById('portal-file-input')?.click();
                    }
                  }}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (e.dataTransfer.files?.[0]) {
                      handleFileChange(e.dataTransfer.files[0]);
                    }
                  }}
                  className={`border-2 border-dashed rounded-xl p-6 md:p-8 text-center cursor-pointer transition-colors ${
                    selectedFile
                      ? 'border-bambu-green/60 bg-bambu-green/5'
                      : 'border-bambu-dark-tertiary hover:border-bambu-green/40 hover:bg-bambu-dark-secondary'
                  }`}
                  onClick={() => document.getElementById('portal-file-input')?.click()}
                >
                  <input
                    id="portal-file-input"
                    type="file"
                    accept=".stl,.3mf,.obj"
                    className="hidden"
                    onChange={(e) => {
                      if (e.target.files?.[0]) {
                        handleFileChange(e.target.files[0]);
                      }
                    }}
                  />

                  {analyzing ? (
                    <div className="py-6 flex flex-col items-center justify-center gap-3">
                      <RefreshCw className="w-8 h-8 text-bambu-green animate-spin" />
                      <div className="font-medium text-sm text-white">Geometrie & Volumen werden analysiert...</div>
                    </div>
                  ) : selectedFile ? (
                    <div className="flex flex-col md:flex-row items-center justify-center gap-4">
                      {analysis?.thumbnail_b64 ? (
                        <img
                          src={analysis.thumbnail_b64}
                          alt="3D Modell Vorschau"
                          className="w-24 h-24 object-contain rounded-lg border border-bambu-dark-tertiary bg-black/40"
                        />
                      ) : (
                        <div className="w-16 h-16 rounded-lg bg-bambu-dark border border-bambu-dark-tertiary flex items-center justify-center">
                          <Box className="w-8 h-8 text-bambu-green" />
                        </div>
                      )}
                      <div className="text-left space-y-1">
                        <div className="font-semibold text-white flex items-center gap-2">
                          <span>{selectedFile.name}</span>
                          <span className="text-xs px-2 py-0.5 rounded bg-bambu-dark border border-bambu-dark-tertiary text-bambu-gray">
                            {(selectedFile.size / (1024 * 1024)).toFixed(2)} MB
                          </span>
                        </div>
                        <div className="text-xs text-bambu-gray">
                          Klicken oder andere Datei hineinziehen zum Austauschen
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="py-6 flex flex-col items-center justify-center gap-2">
                      <Upload className="w-10 h-10 text-bambu-gray mb-1" />
                      <div className="font-medium text-white text-base">
                        Dateien hier ablegen oder <span className="text-bambu-green underline">durchsuchen</span>
                      </div>
                      <div className="text-xs text-bambu-gray">
                        Unterstützt Standard-3D-Dateien: STL (ASCII/Binär), 3MF, OBJ (bis 200 MB)
                      </div>
                    </div>
                  )}
                </div>

                {/* Analyse-Ergebnis Badge Grid */}
                {analysis && (
                  <div className="bg-bambu-dark rounded-lg p-4 border border-bambu-dark-tertiary space-y-3">
                    <div className="text-xs font-semibold text-bambu-gray uppercase tracking-wider flex items-center justify-between">
                      <span>Geometriedaten & Machbarkeit</span>
                      {analysis.fits_bed ? (
                        <span className="text-emerald-400 font-medium flex items-center gap-1 normal-case">
                          <CheckCircle2 className="w-3.5 h-3.5" /> Passt auf Bauraum (256x256x256 mm)
                        </span>
                      ) : (
                        <span className="text-amber-400 font-medium flex items-center gap-1 normal-case">
                          <AlertTriangle className="w-3.5 h-3.5" /> Überschreitet Bauraum!
                        </span>
                      )}
                    </div>

                    <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                      <div className="bg-bambu-dark-secondary rounded p-2.5">
                        <div className="text-xs text-bambu-gray flex items-center gap-1">
                          <Scale className="w-3 h-3 text-bambu-green" />
                          Volumen
                        </div>
                        <div className="font-semibold text-white mt-0.5">{analysis.volume_cm3.toFixed(1)} cm³</div>
                      </div>

                      <div className="bg-bambu-dark-secondary rounded p-2.5">
                        <div className="text-xs text-bambu-gray flex items-center gap-1">
                          <Box className="w-3 h-3 text-bambu-green" />
                          Abmessungen (X/Y/Z)
                        </div>
                        <div className="font-semibold text-white mt-0.5">
                          {analysis.dimensions_mm.x} × {analysis.dimensions_mm.y} × {analysis.dimensions_mm.z} mm
                        </div>
                      </div>

                      <div className="bg-bambu-dark-secondary rounded p-2.5">
                        <div className="text-xs text-bambu-gray flex items-center gap-1">
                          <Layers className="w-3 h-3 text-bambu-green" />
                          Oberfläche
                        </div>
                        <div className="font-semibold text-white mt-0.5">{analysis.surface_area_cm2.toFixed(1)} cm²</div>
                      </div>

                      <div className="bg-bambu-dark-secondary rounded p-2.5">
                        <div className="text-xs text-bambu-gray flex items-center gap-1">
                          <ShieldCheck className="w-3 h-3 text-bambu-green" />
                          Struktur
                        </div>
                        <div className="font-semibold text-white mt-0.5">
                          {analysis.is_watertight ? 'Wasserdicht (ok)' : 'Approximiert'}
                        </div>
                      </div>
                    </div>

                    {analysis.warnings && analysis.warnings.length > 0 && (
                      <div className="p-2.5 rounded bg-amber-500/10 border border-amber-500/30 text-xs text-amber-300 space-y-1">
                        {analysis.warnings.map((w, idx) => (
                          <div key={idx} className="flex items-center gap-1.5">
                            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                            <span>{w}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>

            {/* 2. Druck- & Fertigungsparameter */}
            <Card>
              <CardHeader className="flex items-center gap-2 font-semibold">
                <Layers className="w-5 h-5 text-bambu-green" />
                <span>2. Material & Fertigungseinstellungen</span>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* Materialauswahl */}
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-bambu-gray uppercase tracking-wider">
                    Filament-Material
                  </label>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-2.5">
                    {Object.entries(materials).map(([key, mat]) => (
                      <button
                        key={key}
                        type="button"
                        aria-pressed={filamentType === key}
                        onClick={() => {
                          setFilamentType(key);
                        }}
                        className={`p-3 rounded-lg border text-left transition-all ${
                          filamentType === key
                            ? 'border-bambu-green bg-bambu-green/10 text-white'
                            : 'border-bambu-dark-tertiary bg-bambu-dark hover:border-bambu-dark-hover text-bambu-gray'
                        }`}
                      >
                        <div className="font-semibold text-sm flex items-center justify-between">
                          <span>{key}</span>
                          <span className="text-xs font-normal text-bambu-gray">{mat.density} g/cm³</span>
                        </div>
                        <div className="text-xs text-bambu-gray mt-1 truncate">{mat.name}</div>
                        <div className="text-xs text-bambu-green mt-1 font-medium">{mat.cost_per_kg.toFixed(2)} €/kg</div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Infill & Schichthöhe */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Infill Slider */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-xs font-semibold text-bambu-gray uppercase tracking-wider">
                      <span>Füllgrad (Infill)</span>
                      <span className="text-bambu-green font-bold text-sm normal-case">{infillPercent}%</span>
                    </div>
                    <input
                      id="portal-infill-slider"
                      type="range"
                      min={5}
                      max={100}
                      step={5}
                      aria-label="Füllgrad (Infill) in Prozent"
                      aria-valuemin={5}
                      aria-valuemax={100}
                      aria-valuenow={infillPercent}
                      value={infillPercent}
                      onChange={(e) => setInfillPercent(Number(e.target.value))}
                      className="w-full accent-bambu-green cursor-pointer"
                    />
                    <div className="flex justify-between text-[11px] text-bambu-gray">
                      <span>15% (Standard Deko)</span>
                      <span>40% (Funktionsteil)</span>
                      <span>100% (Massiv)</span>
                    </div>
                  </div>

                  {/* Schichthöhe */}
                  <div className="space-y-2">
                    <label className="text-xs font-semibold text-bambu-gray uppercase tracking-wider block">
                      Schichthöhe
                    </label>
                    <select
                      value={layerHeight}
                      onChange={(e) => setLayerHeight(Number(e.target.value))}
                      className="w-full bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                    >
                      <option value={0.12}>0.12 mm - Fein (glatte Konturen)</option>
                      <option value={0.16}>0.16 mm - Optimal (Standard)</option>
                      <option value={0.2}>0.20 mm - Balance (Geschwindigkeit / Detail)</option>
                      <option value={0.28}>0.28 mm - Schnell (Prototypen)</option>
                    </select>
                  </div>
                </div>

                {/* Stückzahl & Mengenstaffel */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-xs font-semibold text-bambu-gray uppercase tracking-wider">
                    <span>Auftragsstückzahl</span>
                    <span className="text-xs font-medium text-emerald-400 normal-case flex items-center gap-1">
                      <Tag className="w-3.5 h-3.5" />
                      {getDiscountTierLabel(quantity)}
                    </span>
                  </div>
                  <div className="flex items-center gap-3">
                    <input
                      id="portal-quantity-input"
                      type="number"
                      min={1}
                      max={1000}
                      aria-label="Auftragsstückzahl"
                      value={quantity}
                      onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value) || 1))}
                      className="w-32 bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm font-semibold text-white focus:outline-none focus:border-bambu-green"
                    />
                    <div className="flex flex-wrap gap-1.5">
                      {[1, 5, 10, 25, 50].map((q) => (
                        <button
                          key={q}
                          type="button"
                          aria-pressed={quantity === q}
                          aria-label={`${q} Stück`}
                          onClick={() => setQuantity(q)}
                          className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                            quantity === q
                              ? 'bg-bambu-green text-black font-bold border-bambu-green'
                              : 'bg-bambu-dark border-bambu-dark-tertiary text-bambu-gray hover:text-white'
                          }`}
                        >
                          {q}x
                        </button>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Kundendaten (optional für Lieferschein & Label) */}
                <div className="pt-2 border-t border-bambu-dark-tertiary space-y-3">
                  <label className="text-xs font-semibold text-bambu-gray uppercase tracking-wider block">
                    Besteller / Lieferanschrift (für Lieferschein & Versand)
                  </label>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <input
                      type="text"
                      placeholder="Name / Firma (z. B. Max Mustermann)"
                      value={customerName}
                      onChange={(e) => setCustomerName(e.target.value)}
                      className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                    />
                    <input
                      type="text"
                      placeholder="Lieferadresse (z. B. Musterstr. 1, 10115 Berlin)"
                      value={customerAddress}
                      onChange={(e) => setCustomerAddress(e.target.value)}
                      className="bg-bambu-dark border border-bambu-dark-tertiary rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-bambu-green"
                    />
                  </div>
                </div>

                {/* Aktualisieren Button */}
                <div className="pt-2">
                  <Button
                    variant="secondary"
                    onClick={handleRecalculate}
                    disabled={!selectedFile || calculating}
                    className="w-full flex items-center justify-center gap-2"
                  >
                    <RefreshCw className={`w-4 h-4 ${calculating ? 'animate-spin' : ''}`} />
                    <span>Angebot mit geänderten Parametern neu berechnen</span>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Rechte Spalte: Preiskalkulation, Stripe Checkout & Dokumente */}
          <div className="lg:col-span-5 space-y-6">
            {/* 3. Kostenaufschlüsselung Card */}
            <Card className="border-bambu-green/30">
              <CardHeader className="flex items-center justify-between font-semibold">
                <div className="flex items-center gap-2">
                  <CreditCard className="w-5 h-5 text-bambu-green" />
                  <span>3. Verbindliche Sofortkalkulation</span>
                </div>
                {quote?.quote_id && (
                  <span className="text-xs px-2 py-0.5 rounded bg-bambu-dark border border-bambu-dark-tertiary text-bambu-gray font-mono">
                    {quote.quote_id}
                  </span>
                )}
              </CardHeader>
              <CardContent className="space-y-5">
                {quote ? (
                  <>
                    {/* Mengenangaben & Gewichte */}
                    <div className="grid grid-cols-2 gap-3 text-xs bg-bambu-dark rounded-lg p-3 border border-bambu-dark-tertiary">
                      <div>
                        <span className="text-bambu-gray">Auftragsgewicht:</span>
                        <div className="font-semibold text-white mt-0.5">
                          {quote.total_weight_grams} g ({quote.single_weight_grams} g/Stk.)
                        </div>
                      </div>
                      <div>
                        <span className="text-bambu-gray">Druckzeit geschätzt:</span>
                        <div className="font-semibold text-white mt-0.5 flex items-center gap-1">
                          <Clock className="w-3.5 h-3.5 text-bambu-green" />
                          {quote.total_print_hours} Std. gesamt
                        </div>
                      </div>
                    </div>

                    {/* Transparente Kostenaufstellung */}
                    <div className="space-y-2 text-sm border-t border-b border-bambu-dark-tertiary py-3">
                      <div className="flex justify-between text-bambu-gray">
                        <span>Materialkosten ({quote.material_name})</span>
                        <span className="font-mono text-white">{quote.pricing.material_cost_eur.toFixed(2)} €</span>
                      </div>
                      <div className="flex justify-between text-bambu-gray">
                        <span>Maschinenlaufzeit (7,20 € / Std.)</span>
                        <span className="font-mono text-white">{quote.pricing.machine_cost_eur.toFixed(2)} €</span>
                      </div>
                      <div className="flex justify-between text-bambu-gray">
                        <span>Rüst- & Vorbereitungspauschale</span>
                        <span className="font-mono text-white">{quote.pricing.setup_cost_eur.toFixed(2)} €</span>
                      </div>

                      {quote.pricing.discount_percent > 0 && (
                        <div className="flex justify-between text-emerald-400 font-medium">
                          <span>Mengenrabatt (-{quote.pricing.discount_percent}%)</span>
                          <span className="font-mono">-{quote.pricing.discount_amount_eur.toFixed(2)} €</span>
                        </div>
                      )}

                      <div className="pt-2 border-t border-bambu-dark-tertiary flex justify-between text-bambu-gray">
                        <span>Nettobetrag</span>
                        <span className="font-mono text-white">{quote.pricing.net_total_eur.toFixed(2)} €</span>
                      </div>
                      <div className="flex justify-between text-bambu-gray text-xs">
                        <span>inkl. 19% MwSt.</span>
                        <span className="font-mono">{quote.pricing.vat_19_eur.toFixed(2)} €</span>
                      </div>

                      <div className="pt-2 border-t border-bambu-dark-tertiary flex justify-between items-baseline font-bold text-lg text-white">
                        <span>Gesamtbetrag (Brutto):</span>
                        <span className="text-2xl text-bambu-green font-mono">
                          {quote.pricing.gross_total_eur.toFixed(2)} €
                        </span>
                      </div>
                    </div>

                    {/* Stripe Checkout Button */}
                    <div className="space-y-2">
                      <Button
                        variant="primary"
                        onClick={handleCheckout}
                        disabled={checkoutLoading}
                        className="w-full py-3 text-base font-bold flex items-center justify-center gap-2 shadow-lg shadow-bambu-green/20"
                      >
                        {checkoutLoading ? (
                          <RefreshCw className="w-5 h-5 animate-spin" />
                        ) : (
                          <ArrowRight className="w-5 h-5" />
                        )}
                        <span>Jetzt online bestellen & zahlen</span>
                      </Button>
                      <p className="text-center text-[11px] text-bambu-gray">
                        Sichere Bezahlung via Stripe (Kreditkarte, Apple Pay, Google Pay, SEPA)
                      </p>
                    </div>
                  </>
                ) : (
                  <div className="py-12 text-center text-bambu-gray space-y-2">
                    <Box className="w-10 h-10 mx-auto text-bambu-gray/50" />
                    <div className="text-sm">Noch kein Modell hochgeladen.</div>
                    <div className="text-xs">Laden Sie links ein 3D-Modell hoch, um das Angebot zu sehen.</div>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* 4. Dokumente & Versandetiketten Card */}
            {quote && (
              <Card>
                <CardHeader className="flex items-center gap-2 font-semibold">
                  <FileText className="w-5 h-5 text-bambu-green" />
                  <span>4. Lieferschein & Versandetiketten</span>
                </CardHeader>
                <CardContent className="space-y-4">
                  <p className="text-xs text-bambu-gray">
                    Druckfertige Begleitdokumente und Etiketten mit QR-Code zur Auftragsverfolgung im Kundenportal:
                  </p>

                  <div className="space-y-2.5">
                    {/* DIN A4 Lieferschein */}
                    <a
                      href={api.getDeliveryNotePdfUrl(quote.quote_id, 'de')}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-between p-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark hover:border-bambu-green/50 hover:bg-bambu-dark-secondary transition-all"
                    >
                      <div className="flex items-center gap-3">
                        <FileText className="w-5 h-5 text-blue-400" />
                        <div>
                          <div className="font-semibold text-sm text-white">Lieferschein (DIN A4 PDF)</div>
                          <div className="text-xs text-bambu-gray">Standard-Warenbegleitblatt mit Positionen & Gewicht</div>
                        </div>
                      </div>
                      <Download className="w-4 h-4 text-bambu-gray hover:text-white" />
                    </a>

                    {/* Thermo-Etikett 100x150 mm */}
                    <a
                      href={api.getShippingLabelPdfUrl(quote.quote_id, '100x150')}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-between p-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark hover:border-bambu-green/50 hover:bg-bambu-dark-secondary transition-all"
                    >
                      <div className="flex items-center gap-3">
                        <QrCode className="w-5 h-5 text-amber-400" />
                        <div>
                          <div className="font-semibold text-sm text-white">Paket-Etikett (100 × 150 mm)</div>
                          <div className="text-xs text-bambu-gray">Standard-Thermo-Versandaufkleber mit Tracking-QR-Code</div>
                        </div>
                      </div>
                      <Download className="w-4 h-4 text-bambu-gray hover:text-white" />
                    </a>

                    {/* Kompakt-Etikett 62x29 mm */}
                    <a
                      href={api.getShippingLabelPdfUrl(quote.quote_id, '62x29')}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center justify-between p-3 rounded-lg border border-bambu-dark-tertiary bg-bambu-dark hover:border-bambu-green/50 hover:bg-bambu-dark-secondary transition-all"
                    >
                      <div className="flex items-center gap-3">
                        <Printer className="w-5 h-5 text-purple-400" />
                        <div>
                          <div className="font-semibold text-sm text-white">Bauteil-Etikett (62 × 29 mm)</div>
                          <div className="text-xs text-bambu-gray">Kompakt-Aufkleber für Brother QL / Dymo Thermo-Drucker</div>
                        </div>
                      </div>
                      <Download className="w-4 h-4 text-bambu-gray hover:text-white" />
                    </a>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
export default CustomerPortalPage;
