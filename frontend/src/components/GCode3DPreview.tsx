import React, { useEffect, useRef, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Play,
  Pause,
  RotateCcw,
  ZoomIn,
  ZoomOut,
  Upload,
  FileCode,
} from 'lucide-react';
import { Card, CardContent } from './Card';
import {
  generateDemoLayers,
  parseGCodeText,
  type BoundingBox,
  type LayerData,
} from './gcodeParser';

export function GCode3DPreview({
  modelName = 'PrintLab_TestCube_P2S.gcode.3mf',
  initialLayerHeight = 0.2,
}: {
  modelName?: string;
  initialLayerHeight?: number;
}) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const defaultDemo = useMemo(() => generateDemoLayers(50, initialLayerHeight), [initialLayerHeight]);
  const [activeModel, setActiveModel] = useState<{
    name: string;
    layers: LayerData[];
    bounds: BoundingBox;
    isCustom: boolean;
  }>({
    name: modelName,
    layers: defaultDemo.layers,
    bounds: defaultDemo.bounds,
    isCustom: false,
  });

  const totalLayers = activeModel.layers.length;
  const [currentLayer, setCurrentLayer] = useState<number>(Math.min(25, totalLayers));
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [rotationX, setRotationX] = useState<number>(55); // Grad
  const [rotationZ, setRotationZ] = useState<number>(45);
  const [zoom, setZoom] = useState<number>(1.0);
  const [showTravelMoves, setShowTravelMoves] = useState<boolean>(false);
  const [filamentColor, setFilamentColor] = useState<string>('#00AE42'); // Bambu Grün

  // Maus-Gesten Zustand
  const [isDragging, setIsDragging] = useState<boolean>(false);
  const [lastMouse, setLastMouse] = useState<{ x: number; y: number } | null>(null);

  // Animation der Schichten (Play-Button)
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isPlaying) {
      timer = setInterval(() => {
        setCurrentLayer((prev) => {
          if (prev >= totalLayers) {
            setIsPlaying(false);
            return totalLayers;
          }
          return prev + 1;
        });
      }, 90);
    }
    return () => clearInterval(timer);
  }, [isPlaying, totalLayers]);

  // Echten G-Code aus Datei laden
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target?.result;
      if (typeof text === 'string') {
        const parsed = parseGCodeText(text);
        setActiveModel({
          name: file.name,
          layers: parsed.layers,
          bounds: parsed.bounds,
          isCustom: true,
        });
        setCurrentLayer(parsed.layers.length);
        setIsPlaying(false);
      }
    };
    reader.readAsText(file);
  };

  const handleResetToDemo = () => {
    setActiveModel({
      name: modelName,
      layers: defaultDemo.layers,
      bounds: defaultDemo.bounds,
      isCustom: false,
    });
    setCurrentLayer(Math.min(25, defaultDemo.layers.length));
    setIsPlaying(false);
    setRotationX(55);
    setRotationZ(45);
    setZoom(1.0);
  };

  // 3D-Canvas Zeichnung
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    // Hintergrund (Dunkelgrau Werkstatt-Look)
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, width, height);

    // Projektions-Parameter
    const radX = (rotationX * Math.PI) / 180;
    const radZ = (rotationZ * Math.PI) / 180;
    const scale = (Math.min(width, height) / 360) * zoom;
    const originX = width / 2;
    const originY = height / 2 + 30;

    // 3D zu 2D Projektionsfunktion (Bambu P2S Bett: 256 x 256 mm)
    const project = (x: number, y: number, z: number) => {
      const nx = x - 128;
      const ny = y - 128;
      const nz = z * 2.2; // Z überhöht für bessere Schichtsichtbarkeit

      const rx = nx * Math.cos(radZ) - ny * Math.sin(radZ);
      const ry = nx * Math.sin(radZ) + ny * Math.cos(radZ);
      const rz = nz;

      const px = rx;
      const py = ry * Math.cos(radX) - rz * Math.sin(radX);

      return {
        x: originX + px * scale,
        y: originY + py * scale,
      };
    };

    // 1. Druckbett (256 x 256 mm Gitternetz)
    const bedSize = 256;
    ctx.lineWidth = 1;

    // Bett-Grundplatte
    ctx.beginPath();
    const p1 = project(0, 0, 0);
    const p2 = project(bedSize, 0, 0);
    const p3 = project(bedSize, bedSize, 0);
    const p4 = project(0, bedSize, 0);
    ctx.moveTo(p1.x, p1.y);
    ctx.lineTo(p2.x, p2.y);
    ctx.lineTo(p3.x, p3.y);
    ctx.lineTo(p4.x, p4.y);
    ctx.closePath();
    ctx.fillStyle = '#1e293b'; // PEI Textured Plate Farbe
    ctx.fill();
    ctx.strokeStyle = '#334155';
    ctx.stroke();

    // Gitterlinien alle 32 mm
    ctx.strokeStyle = '#273549';
    for (let x = 32; x < bedSize; x += 32) {
      const a = project(x, 0, 0);
      const b = project(x, bedSize, 0);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
    for (let y = 32; y < bedSize; y += 32) {
      const a = project(0, y, 0);
      const b = project(bedSize, y, 0);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }

    // Bambu Beschriftung "Bambu Lab 256x256 PEI"
    const bedCenter = project(128, 12, 0);
    ctx.font = '10px monospace';
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'center';
    ctx.fillText('BAMBU LAB P2S (256×256)', bedCenter.x, bedCenter.y);

    // 2. Schichten (Toolpaths) zeichnen
    const visibleLayers = activeModel.layers.slice(0, currentLayer);

    for (let i = 0; i < visibleLayers.length; i++) {
      const layer = visibleLayers[i];
      const isTop = i === visibleLayers.length - 1;
      const alpha = isTop ? 1.0 : Math.max(0.12, (i / visibleLayers.length) * 0.7);

      ctx.lineWidth = isTop ? 2.0 : 1.2;

      for (let p = 1; p < layer.points.length; p++) {
        const pt1 = layer.points[p - 1];
        const pt2 = layer.points[p];

        const isTravel = pt2.e === 0;
        if (isTravel && !showTravelMoves) continue;

        const p2d1 = project(pt1.x, pt1.y, pt1.z);
        const p2d2 = project(pt2.x, pt2.y, pt2.z);

        ctx.beginPath();
        ctx.moveTo(p2d1.x, p2d1.y);
        ctx.lineTo(p2d2.x, p2d2.y);

        if (isTravel) {
          ctx.strokeStyle = 'rgba(239, 68, 68, 0.35)'; // Rot für Leerfahrt
          ctx.setLineDash([2, 4]);
        } else {
          ctx.strokeStyle = isTop ? filamentColor : `${filamentColor}${Math.floor(alpha * 255).toString(16).padStart(2, '0')}`;
          ctx.setLineDash([]);
        }

        ctx.stroke();
      }

      // Nozzle / Druckkopf-Position auf oberster Schicht
      if (isTop && layer.points.length > 0) {
        const lastPt = layer.points[layer.points.length - 1];
        const nPos = project(lastPt.x, lastPt.y, lastPt.z);
        ctx.beginPath();
        ctx.arc(nPos.x, nPos.y, 4, 0, 2 * Math.PI);
        ctx.fillStyle = '#38bdf8'; // Cyan Nozzle
        ctx.fill();
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }, [activeModel.layers, currentLayer, rotationX, rotationZ, zoom, filamentColor, showTravelMoves]);

  // Maus-Gesten (3D Orbit Rotation)
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    setLastMouse({ x: e.clientX, y: e.clientY });
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDragging || !lastMouse) return;
    const dx = e.clientX - lastMouse.x;
    const dy = e.clientY - lastMouse.y;
    setRotationZ((prev) => (prev + dx * 0.6) % 360);
    setRotationX((prev) => Math.max(10, Math.min(85, prev - dy * 0.4)));
    setLastMouse({ x: e.clientX, y: e.clientY });
  };

  const handleMouseUp = () => {
    setIsDragging(false);
    setLastMouse(null);
  };

  const currentZ = (currentLayer * initialLayerHeight).toFixed(2);
  const widthMm = (activeModel.bounds.maxX - activeModel.bounds.minX).toFixed(1);
  const depthMm = (activeModel.bounds.maxY - activeModel.bounds.minY).toFixed(1);
  const heightMm = (activeModel.bounds.maxZ).toFixed(1);

  return (
    <Card className="border border-bambu-dark-tertiary overflow-hidden">
      <CardContent className="p-4 space-y-4">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-bambu-dark-tertiary">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-bambu-green/10 text-bambu-green rounded-lg">
              {activeModel.isCustom ? <FileCode className="w-5 h-5" /> : <Box className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                {t('slicer.3dPreviewTitle', '3D-Schicht- & Werkzeugbahn-Vorschau')}
                <span className="text-[10px] bg-bambu-green/20 text-bambu-green font-mono px-2 py-0.5 rounded-full">
                  P2S Engine v1.27
                </span>
                {activeModel.isCustom && (
                  <span className="text-[10px] bg-blue-500/20 text-blue-400 font-mono px-2 py-0.5 rounded-full">
                    Eigener G-Code
                  </span>
                )}
              </h3>
              <p className="text-xs text-bambu-gray font-mono truncate max-w-[280px]">{activeModel.name}</p>
            </div>
          </div>

          {/* Quick Stats Badges & Upload Button */}
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2.5 py-1 rounded bg-bambu-dark-tertiary text-white font-mono">
              Z: <strong className="text-bambu-green">{currentZ} mm</strong>
            </span>
            <span className="px-2.5 py-1 rounded bg-bambu-dark-tertiary text-white font-mono">
              Layer: <strong className="text-bambu-green">{currentLayer}</strong> / {totalLayers}
            </span>

            <input
              ref={fileInputRef}
              type="file"
              accept=".gcode,.txt,.3mf"
              onChange={handleFileUpload}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-bambu-green/20 text-bambu-green hover:bg-bambu-green/30 transition-colors font-medium"
              title="Eigenen G-Code zur Vorschau laden"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>G-Code laden</span>
            </button>
            {activeModel.isCustom && (
              <button
                onClick={handleResetToDemo}
                className="px-2 py-1 rounded bg-bambu-dark-tertiary text-bambu-gray hover:text-white transition-colors"
                title="Zurück zum Testwürfel"
              >
                Reset
              </button>
            )}
          </div>
        </div>

        {/* 3D Canvas Box */}
        <div
          className="relative w-full h-[320px] rounded-xl overflow-hidden border border-bambu-dark-tertiary cursor-grab active:cursor-grabbing select-none"
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          <canvas
            ref={canvasRef}
            width={640}
            height={320}
            className="w-full h-full block"
          />

          {/* Overlay Buttons (Zoom & Reset) */}
          <div className="absolute top-3 right-3 flex flex-col gap-1.5 bg-bambu-dark-secondary/80 backdrop-blur p-1 rounded-lg border border-bambu-dark-tertiary">
            <button
              onClick={() => setZoom((z) => Math.min(2.5, z + 0.15))}
              className="p-1.5 text-bambu-gray hover:text-white rounded hover:bg-bambu-dark transition-colors"
              title="Heranzoomen"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
            <button
              onClick={() => setZoom((z) => Math.max(0.5, z - 0.15))}
              className="p-1.5 text-bambu-gray hover:text-white rounded hover:bg-bambu-dark transition-colors"
              title="Herauszoomen"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <button
              onClick={() => {
                setRotationX(55);
                setRotationZ(45);
                setZoom(1.0);
              }}
              className="p-1.5 text-bambu-gray hover:text-white rounded hover:bg-bambu-dark transition-colors"
              title="Ansicht zurücksetzen"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
          </div>

          {/* Filament Color Selector Pill */}
          <div className="absolute bottom-3 left-3 flex items-center gap-2 bg-bambu-dark-secondary/80 backdrop-blur px-2.5 py-1.5 rounded-lg border border-bambu-dark-tertiary text-xs">
            <span className="text-bambu-gray">Filament:</span>
            {['#00AE42', '#ffffff', '#2563eb', '#dc2626', '#f59e0b', '#8b5cf6'].map((c) => (
              <button
                key={c}
                onClick={() => setFilamentColor(c)}
                className={`w-3.5 h-3.5 rounded-full border transition-transform ${
                  filamentColor === c ? 'scale-125 border-white' : 'border-transparent opacity-80'
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>

          <div className="absolute bottom-3 right-3 text-[11px] text-bambu-gray/80 bg-black/40 px-2 py-0.5 rounded pointer-events-none">
            Maus ziehen zum Drehen
          </div>
        </div>

        {/* Timeline & Scrubber Controls */}
        <div className="space-y-2 bg-bambu-dark-secondary p-3 rounded-xl border border-bambu-dark-tertiary">
          <div className="flex items-center justify-between text-xs text-white">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setIsPlaying(!isPlaying)}
                className="p-1.5 rounded-lg bg-bambu-green text-black font-semibold hover:bg-bambu-green/80 transition-colors"
                title={isPlaying ? 'Pausieren' : 'Schichtaufbau abspielen'}
              >
                {isPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
              </button>
              <span className="font-medium">Schicht-Inspektion (Layer Scrubber)</span>
            </div>
            <label className="flex items-center gap-1.5 text-xs text-bambu-gray cursor-pointer">
              <input
                type="checkbox"
                checked={showTravelMoves}
                onChange={(e) => setShowTravelMoves(e.target.checked)}
                className="accent-bambu-green rounded"
              />
              <span>Leerfahrten (Travel) anzeigen</span>
            </label>
          </div>

          {/* Slider */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-bambu-gray font-mono">1</span>
            <input
              type="range"
              min={1}
              max={totalLayers}
              value={currentLayer}
              onChange={(e) => {
                setCurrentLayer(Number(e.target.value));
                setIsPlaying(false);
              }}
              className="flex-1 h-2 bg-bambu-dark rounded-lg appearance-none cursor-pointer accent-bambu-green"
            />
            <span className="text-xs text-bambu-gray font-mono">{totalLayers}</span>
          </div>
        </div>

        {/* Model Metrics */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-xs">
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Schichten / Layer</div>
            <div className="text-sm font-semibold text-white mt-0.5">{totalLayers} Layer</div>
          </div>
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Filamentfarbe</div>
            <div className="text-sm font-semibold text-white mt-0.5 flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: filamentColor }} />
              <span>{filamentColor}</span>
            </div>
          </div>
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Druckbett (P2S)</div>
            <div className="text-sm font-semibold text-white mt-0.5">256 × 256 mm PEI</div>
          </div>
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Modellmaße</div>
            <div className="text-sm font-semibold text-white mt-0.5">{widthMm} × {depthMm} × {heightMm} mm</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
