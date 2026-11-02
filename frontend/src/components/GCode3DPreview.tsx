import React, { useEffect, useRef, useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Box,
  Play,
  Pause,
  RotateCcw,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { Card, CardContent } from './Card';

interface ToolpathPoint {
  x: number;
  y: number;
  z: number;
  e: number; // Extrusion (0 = travel, >0 = print)
}

interface LayerData {
  layerIndex: number;
  z: number;
  points: ToolpathPoint[];
}

// Erzeugt deterministische Schichtpfade (z. B. Bambu 20mm-Testwürfel mit Infill & Perimeter)
function generateDemoLayers(layerCount = 50, layerHeight = 0.2): LayerData[] {
  const layers: LayerData[] = [];
  const cx = 128; // Bettmitte (256 / 2)
  const cy = 128;
  const size = 30; // 30 mm Würfel
  const half = size / 2;

  for (let l = 0; l < layerCount; l++) {
    const z = (l + 1) * layerHeight;
    const points: ToolpathPoint[] = [];

    // 1. Anfahrt (Travel)
    points.push({ x: cx - half, y: cy - half, z, e: 0 });

    // 2. Äußere Perimeter (Wand 1)
    points.push({ x: cx + half, y: cy - half, z, e: 1 });
    points.push({ x: cx + half, y: cy + half, z, e: 1 });
    points.push({ x: cx - half, y: cy + half, z, e: 1 });
    points.push({ x: cx - half, y: cy - half, z, e: 1 });

    // 3. Innere Wand (Wand 2, 0.4mm Versatz)
    const inset = 0.45;
    points.push({ x: cx - half + inset, y: cy - half + inset, z, e: 0 });
    points.push({ x: cx + half - inset, y: cy - half + inset, z, e: 1 });
    points.push({ x: cx + half - inset, y: cy + half - inset, z, e: 1 });
    points.push({ x: cx - half + inset, y: cy + half - inset, z, e: 1 });
    points.push({ x: cx - half + inset, y: cy - half + inset, z, e: 1 });

    // 4. Infill (Diagonales Gitter / Grid)
    const step = 4.0;
    const angleOffset = l % 2 === 0 ? 1 : -1;
    for (let x = cx - half + 2; x <= cx + half - 2; x += step) {
      if (angleOffset > 0) {
        points.push({ x, y: cy - half + 2, z, e: 0 });
        points.push({ x: Math.min(cx + half - 2, x + (size - 4)), y: cy + half - 2, z, e: 1 });
      } else {
        points.push({ x, y: cy + half - 2, z, e: 0 });
        points.push({ x: Math.min(cx + half - 2, x + (size - 4)), y: cy - half + 2, z, e: 1 });
      }
    }

    layers.push({ layerIndex: l + 1, z, points });
  }

  return layers;
}

export function GCode3DPreview({
  modelName = 'PrintLab_TestCube_P2S.gcode.3mf',
  initialLayerHeight = 0.2,
}: {
  modelName?: string;
  initialLayerHeight?: number;
}) {
  const { t } = useTranslation();
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  const totalLayers = 50;
  const [currentLayer, setCurrentLayer] = useState(25);
  const [isPlaying, setIsPlaying] = useState(false);
  const [rotationX, setRotationX] = useState(55); // Isometrischer Neigungswinkel
  const [rotationZ, setRotationZ] = useState(45); // Drehung um Z-Achse
  const [zoom, setZoom] = useState(1.0);
  const [isDragging, setIsDragging] = useState(false);
  const [lastMouse, setLastMouse] = useState<{ x: number; y: number } | null>(null);
  const [filamentColor, setFilamentColor] = useState('#00AE42'); // Bambu Green
  const [showTravelMoves, setShowTravelMoves] = useState(false);

  const layers = useMemo(() => generateDemoLayers(totalLayers, initialLayerHeight), [totalLayers, initialLayerHeight]);

  // Animation Loop wenn Play aktiv ist
  useEffect(() => {
    if (!isPlaying) return;
    const timer = window.setInterval(() => {
      setCurrentLayer((prev) => {
        if (prev >= totalLayers) {
          setIsPlaying(false);
          return 1;
        }
        return prev + 1;
      });
    }, 120);
    return () => window.clearInterval(timer);
  }, [isPlaying, totalLayers]);

  // 3D Canvas Renderer (Isometrisch projizierte Toolpaths + Bambu P2S 256x256 Bett)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Rescale for Retina / High DPI
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    // Hintergrund
    ctx.fillStyle = '#0f1715'; // Bambu Dark Tint
    ctx.fillRect(0, 0, width, height);

    // Projektions-Transformation
    const radX = (rotationX * Math.PI) / 180;
    const radZ = (rotationZ * Math.PI) / 180;

    const project = (x: number, y: number, z: number) => {
      // Zentrieren um (128, 128)
      const nx = (x - 128) * zoom;
      const ny = (y - 128) * zoom;
      const nz = z * zoom * 1.5;

      // Z-Rotation
      const xRot = nx * Math.cos(radZ) - ny * Math.sin(radZ);
      const yRot = nx * Math.sin(radZ) + ny * Math.cos(radZ);

      // X-Tilt (Isometrie)
      const screenX = width / 2 + xRot;
      const screenY = height / 2 + yRot * Math.sin(radX) - nz * Math.cos(radX);

      return { x: screenX, y: screenY };
    };

    // 1. Druckbett (256x256 mm) zeichnen
    const corners = [
      project(0, 0, 0),
      project(256, 0, 0),
      project(256, 256, 0),
      project(0, 256, 0),
    ];

    // Bett-Oberfläche
    ctx.beginPath();
    ctx.moveTo(corners[0].x, corners[0].y);
    corners.slice(1).forEach((c) => ctx.lineTo(c.x, c.y));
    ctx.closePath();
    ctx.fillStyle = '#182420';
    ctx.fill();
    ctx.strokeStyle = '#2d4239';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Bett-Gitterlinien (alle 32 mm)
    ctx.strokeStyle = '#21332c';
    ctx.lineWidth = 0.5;
    for (let g = 32; g < 256; g += 32) {
      const p1 = project(g, 0, 0);
      const p2 = project(g, 256, 0);
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();

      const p3 = project(0, g, 0);
      const p4 = project(256, g, 0);
      ctx.beginPath();
      ctx.moveTo(p3.x, p3.y);
      ctx.lineTo(p4.x, p4.y);
      ctx.stroke();
    }

    // Bambu P2S Bett-Beschriftung
    const origin = project(10, 246, 0);
    ctx.fillStyle = '#00AE42';
    ctx.font = '10px monospace';
    ctx.fillText('BAMBU P2S (256x256)', origin.x, origin.y);

    // 2. Schichten bis currentLayer zeichnen
    for (let i = 0; i < currentLayer; i++) {
      const layer = layers[i];
      if (!layer) continue;
      const isTop = i === currentLayer - 1;

      // Deckkraft / Alpha für tiefere Schichten
      const alpha = isTop ? 1.0 : Math.max(0.2, 0.8 - (currentLayer - i) * 0.04);

      for (let p = 0; p < layer.points.length - 1; p++) {
        const pt1 = layer.points[p];
        const pt2 = layer.points[p + 1];

        const s1 = project(pt1.x, pt1.y, pt1.z);
        const s2 = project(pt2.x, pt2.y, pt2.z);

        if (pt2.e > 0) {
          // Extrusions-Linie
          ctx.beginPath();
          ctx.moveTo(s1.x, s1.y);
          ctx.lineTo(s2.x, s2.y);
          ctx.strokeStyle = isTop ? filamentColor : `${filamentColor}aa`;
          ctx.lineWidth = isTop ? 2.0 : 1.2;
          ctx.globalAlpha = alpha;
          ctx.stroke();
          ctx.globalAlpha = 1.0;
        } else if (showTravelMoves && isTop) {
          // Leerfahrt (Travel move) gestrichelt
          ctx.beginPath();
          ctx.setLineDash([2, 4]);
          ctx.moveTo(s1.x, s1.y);
          ctx.lineTo(s2.x, s2.y);
          ctx.strokeStyle = '#ef444488'; // Rot gestrichelt
          ctx.lineWidth = 1;
          ctx.stroke();
          ctx.setLineDash([]);
        }
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
  }, [layers, currentLayer, rotationX, rotationZ, zoom, filamentColor, showTravelMoves]);

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

  return (
    <Card className="border border-bambu-dark-tertiary overflow-hidden">
      <CardContent className="p-4 space-y-4">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-bambu-dark-tertiary">
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-bambu-green/10 text-bambu-green rounded-lg">
              <Box className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                {t('slicer.3dPreviewTitle', '3D-Schicht- & Werkzeugbahn-Vorschau')}
                <span className="text-[10px] bg-bambu-green/20 text-bambu-green font-mono px-2 py-0.5 rounded-full">
                  P2S Engine
                </span>
              </h3>
              <p className="text-xs text-bambu-gray font-mono">{modelName}</p>
            </div>
          </div>

          {/* Quick Stats Badges */}
          <div className="flex items-center gap-2 text-xs">
            <span className="px-2.5 py-1 rounded bg-bambu-dark-tertiary text-white font-mono">
              Z: <strong className="text-bambu-green">{currentZ} mm</strong>
            </span>
            <span className="px-2.5 py-1 rounded bg-bambu-dark-tertiary text-white font-mono">
              Layer: <strong className="text-bambu-green">{currentLayer}</strong> / {totalLayers}
            </span>
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
            {['#00AE42', '#ffffff', '#2563eb', '#dc2626', '#f59e0b'].map((c) => (
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
            <div className="text-bambu-gray">Druckzeit (Schätzung)</div>
            <div className="text-sm font-semibold text-white mt-0.5">5m 12s</div>
          </div>
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Filamentbedarf</div>
            <div className="text-sm font-semibold text-white mt-0.5">1.13 g (0.38 m)</div>
          </div>
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Düse / Heizbett</div>
            <div className="text-sm font-semibold text-white mt-0.5">220°C / 55°C</div>
          </div>
          <div className="p-2 rounded bg-bambu-dark border border-bambu-dark-tertiary">
            <div className="text-bambu-gray">Modellmaße</div>
            <div className="text-sm font-semibold text-white mt-0.5">30 × 30 × 10 mm</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
