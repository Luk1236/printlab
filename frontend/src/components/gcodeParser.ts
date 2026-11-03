/**
 * G-Code-Parsing für die 3D-Vorschau (GCode3DPreview).
 *
 * Ausgelagert aus GCode3DPreview.tsx, damit die Komponentendatei nach der
 * react-refresh-Regel nur Komponenten exportiert (Fast-Refresh-Fähigkeit,
 * CI-ESLint-Fehler). Reine Logik, keine React-Abhängigkeit.
 */

export interface ToolpathPoint {
  x: number;
  y: number;
  z: number;
  e: number; // Extrusion (0 = travel, >0 = print)
}

export interface LayerData {
  layerIndex: number;
  z: number;
  points: ToolpathPoint[];
}

export interface BoundingBox {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
}

// Erzeugt deterministische Schichtpfade (z. B. Bambu 20mm-Testwürfel mit Infill & Perimeter)
export function generateDemoLayers(layerCount = 50, layerHeight = 0.2): { layers: LayerData[]; bounds: BoundingBox } {
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

  return {
    layers,
    bounds: {
      minX: cx - half,
      maxX: cx + half,
      minY: cy - half,
      maxY: cy + half,
      minZ: layerHeight,
      maxZ: layerCount * layerHeight,
    },
  };
}

/**
 * Schneller clientseitiger G-Code Parser für reale Bambu Studio / OrcaSlicer G-Code-Dateien.
 */
export function parseGCodeText(
  text: string,
  maxPointsPerLayer = 2500,
): { layers: LayerData[]; bounds: BoundingBox } {
  const lines = text.split('\n');
  const layers: LayerData[] = [];
  let currentLayerPoints: ToolpathPoint[] = [];
  let currentZ = 0.2;
  let curX = 128;
  let curY = 128;
  let curE = 0;
  let lastE = 0;
  let layerIdx = 0;

  let minX = 256;
  let maxX = 0;
  let minY = 256;
  let maxY = 0;
  let minZ = 500;
  let maxZ = 0;

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i].trim();
    if (!raw || raw.startsWith(';')) {
      if (
        raw.startsWith(';LAYER_CHANGE') ||
        raw.startsWith(';Z:') ||
        raw.startsWith('; layer ') ||
        raw.startsWith(';AFTER_LAYER_CHANGE')
      ) {
        if (currentLayerPoints.length > 0) {
          layers.push({ layerIndex: ++layerIdx, z: currentZ, points: currentLayerPoints });
          currentLayerPoints = [];
        }
      }
      continue;
    }

    if (raw.startsWith('G0') || raw.startsWith('G1')) {
      const matchX = raw.match(/X([0-9.-]+)/);
      const matchY = raw.match(/Y([0-9.-]+)/);
      const matchZ = raw.match(/Z([0-9.-]+)/);
      const matchE = raw.match(/E([0-9.-]+)/);

      if (matchZ) {
        const newZ = parseFloat(matchZ[1]);
        if (Math.abs(newZ - currentZ) > 0.05 && currentLayerPoints.length > 0) {
          layers.push({ layerIndex: ++layerIdx, z: currentZ, points: currentLayerPoints });
          currentLayerPoints = [];
          currentZ = newZ;
        }
      }
      if (matchX) {
        curX = parseFloat(matchX[1]);
        minX = Math.min(minX, curX);
        maxX = Math.max(maxX, curX);
      }
      if (matchY) {
        curY = parseFloat(matchY[1]);
        minY = Math.min(minY, curY);
        maxY = Math.max(maxY, curY);
      }
      if (matchZ) {
        minZ = Math.min(minZ, currentZ);
        maxZ = Math.max(maxZ, currentZ);
      }

      if (matchE) {
        curE = parseFloat(matchE[1]);
      } else {
        curE = 0;
      }
      const isExtrusion = matchE !== null && curE > lastE;
      lastE = curE;

      if (currentLayerPoints.length < maxPointsPerLayer) {
        currentLayerPoints.push({ x: curX, y: curY, z: currentZ, e: isExtrusion ? 1 : 0 });
      }
    }
  }

  if (currentLayerPoints.length > 0) {
    layers.push({ layerIndex: ++layerIdx, z: currentZ, points: currentLayerPoints });
  }

  if (layers.length === 0) {
    return generateDemoLayers();
  }

  return {
    layers,
    bounds: {
      minX: minX <= maxX ? minX : 100,
      maxX: minX <= maxX ? maxX : 156,
      minY: minY <= maxY ? minY : 100,
      maxY: minY <= maxY ? maxY : 156,
      minZ: minZ <= maxZ ? minZ : 0.2,
      maxZ: minZ <= maxZ ? maxZ : 10.0,
    },
  };
}