import { useState } from 'react';
import {
  AlertOctagon,
  CheckCircle2,
  Thermometer,
  Layers,
  Clock,
  Maximize,
  Minimize,
  RefreshCw,
  Video,
  Printer,
  ShieldAlert,
} from 'lucide-react';

interface KioskStatus {
  state: 'IDLE' | 'PRINTING' | 'PAUSED' | 'ESTOP';
  nozzleTemp: number;
  targetNozzleTemp: number;
  bedTemp: number;
  targetBedTemp: number;
  progress: number;
  remainingMinutes: number;
  currentLayer: number;
  totalLayers: number;
  jobName: string;
  plateClean: boolean;
}

export function KioskModePage() {
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [status, setStatus] = useState<KioskStatus>({
    state: 'PRINTING',
    nozzleTemp: 220.5,
    targetNozzleTemp: 220.0,
    bedTemp: 55.2,
    targetBedTemp: 55.0,
    progress: 48,
    remainingMinutes: 24,
    currentLayer: 45,
    totalLayers: 94,
    jobName: 'Gehaeuse_P2S_Front_v3.gcode.3mf',
    plateClean: true,
  });

  const [estopTriggered, setEstopTriggered] = useState(false);

  // Vollbild-Umschaltung
  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const handleEmergencyStop = () => {
    setEstopTriggered(true);
    setStatus((prev) => ({ ...prev, state: 'ESTOP', progress: prev.progress }));
  };

  const handleResetEstop = () => {
    setEstopTriggered(false);
    setStatus((prev) => ({ ...prev, state: 'IDLE' }));
  };

  const handleAcknowledgePlateClean = () => {
    setStatus((prev) => ({ ...prev, plateClean: true }));
  };

  const stateColors = {
    IDLE: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
    PRINTING: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    PAUSED: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
    ESTOP: 'bg-red-500/30 text-red-400 border-red-500/50 animate-pulse',
  };

  return (
    <div className="min-h-screen bg-slate-950 text-white p-4 select-none flex flex-col justify-between font-sans">
      {/* Kiosk Header */}
      <header className="flex items-center justify-between pb-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-emerald-500/20 text-emerald-400 rounded-xl">
            <Printer className="w-8 h-8" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight">PrintLab 2.0 Kiosk</h1>
              <span className="text-xs uppercase font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400">
                Pi 5 Touch Engine
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">Bambu Lab P2S (Werkstatt #1)</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className={`px-4 py-2 rounded-xl border text-sm font-bold tracking-wide uppercase ${stateColors[status.state]}`}>
            {status.state === 'ESTOP' ? 'NOT-HALT AKTIV' : status.state}
          </div>
          <button
            onClick={toggleFullscreen}
            className="p-3 bg-slate-800 hover:bg-slate-700 rounded-xl transition-colors text-slate-300"
            title="Vollbild"
          >
            {isFullscreen ? <Minimize className="w-6 h-6" /> : <Maximize className="w-6 h-6" />}
          </button>
        </div>
      </header>

      {/* Main Kiosk Dashboard Grid */}
      <main className="grid grid-cols-1 md:grid-cols-12 gap-4 my-4 flex-1">
        {/* Left Column: Job & Progress & Camera (7 Cols) */}
        <div className="md:col-span-7 flex flex-col gap-4">
          {/* Active Job Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-col justify-between flex-1">
            <div>
              <span className="text-xs font-semibold uppercase text-slate-400">Aktueller Druckauftrag</span>
              <h2 className="text-lg font-bold text-white mt-1 truncate">{status.jobName}</h2>

              {/* Progress Bar */}
              <div className="mt-4 space-y-1.5">
                <div className="flex justify-between text-sm font-mono">
                  <span className="text-slate-400">Fortschritt</span>
                  <span className="text-emerald-400 font-bold text-base">{status.progress}%</span>
                </div>
                <div className="w-full h-5 bg-slate-800 rounded-full overflow-hidden p-0.5 border border-slate-700">
                  <div
                    className="h-full bg-gradient-to-r from-emerald-500 to-teal-400 rounded-full transition-all duration-500"
                    style={{ width: `${status.progress}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Quick Metrics (3 Big Tiles) */}
            <div className="grid grid-cols-3 gap-3 mt-4">
              <div className="bg-slate-800/60 p-3 rounded-xl border border-slate-700/60">
                <div className="flex items-center gap-1.5 text-xs text-slate-400">
                  <Clock className="w-4 h-4 text-sky-400" />
                  <span>Restzeit</span>
                </div>
                <div className="text-xl font-extrabold font-mono mt-1 text-white">
                  {status.remainingMinutes} <span className="text-xs text-slate-400 font-normal">min</span>
                </div>
              </div>

              <div className="bg-slate-800/60 p-3 rounded-xl border border-slate-700/60">
                <div className="flex items-center gap-1.5 text-xs text-slate-400">
                  <Layers className="w-4 h-4 text-emerald-400" />
                  <span>Schicht</span>
                </div>
                <div className="text-xl font-extrabold font-mono mt-1 text-white">
                  {status.currentLayer} <span className="text-xs text-slate-400 font-normal">/ {status.totalLayers}</span>
                </div>
              </div>

              <div className="bg-slate-800/60 p-3 rounded-xl border border-slate-700/60">
                <div className="flex items-center gap-1.5 text-xs text-slate-400">
                  <Video className="w-4 h-4 text-purple-400" />
                  <span>Kamera</span>
                </div>
                <div className="text-sm font-semibold text-emerald-400 mt-1 flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping inline-block" />
                  Live (1080p)
                </div>
              </div>
            </div>
          </div>

          {/* Temperature Status Card */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 grid grid-cols-2 gap-4">
            <div className="flex items-center gap-3 bg-slate-800/50 p-3 rounded-xl border border-slate-700/50">
              <div className="p-2.5 bg-red-500/20 text-red-400 rounded-lg">
                <Thermometer className="w-6 h-6" />
              </div>
              <div>
                <span className="text-xs text-slate-400">Düse (Nozzle)</span>
                <div className="text-xl font-extrabold font-mono text-white">
                  {status.nozzleTemp.toFixed(1)}°C{' '}
                  <span className="text-xs text-slate-500 font-normal">/ {status.targetNozzleTemp}°C</span>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3 bg-slate-800/50 p-3 rounded-xl border border-slate-700/50">
              <div className="p-2.5 bg-amber-500/20 text-amber-400 rounded-lg">
                <Thermometer className="w-6 h-6" />
              </div>
              <div>
                <span className="text-xs text-slate-400">Heizbett (Bed)</span>
                <div className="text-xl font-extrabold font-mono text-white">
                  {status.bedTemp.toFixed(1)}°C{' '}
                  <span className="text-xs text-slate-500 font-normal">/ {status.targetBedTemp}°C</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: Giant Touch Action Buttons (5 Cols) */}
        <div className="md:col-span-5 flex flex-col gap-4">
          {/* Giant Emergency Stop Button */}
          {!estopTriggered ? (
            <button
              onClick={handleEmergencyStop}
              className="flex-1 min-h-[140px] bg-gradient-to-br from-red-600 to-rose-700 hover:from-red-500 hover:to-rose-600 active:scale-[0.98] rounded-2xl p-4 flex flex-col items-center justify-center gap-2 text-white shadow-lg shadow-red-900/40 border border-red-500 transition-all cursor-pointer"
            >
              <AlertOctagon className="w-14 h-14 animate-pulse" />
              <span className="text-2xl font-black uppercase tracking-wider">NOT-HALT</span>
              <span className="text-xs text-red-200">Sofortige Abschaltung aller Motoren</span>
            </button>
          ) : (
            <button
              onClick={handleResetEstop}
              className="flex-1 min-h-[140px] bg-gradient-to-br from-amber-600 to-orange-700 hover:from-amber-500 hover:to-orange-600 rounded-2xl p-4 flex flex-col items-center justify-center gap-2 text-white shadow-lg border border-amber-400 transition-all cursor-pointer"
            >
              <ShieldAlert className="w-12 h-12" />
              <span className="text-xl font-black uppercase tracking-wider">NOT-HALT QUITTIEREN</span>
              <span className="text-xs text-amber-200">Sicherheitskreis freigeben</span>
            </button>
          )}

          {/* Quick Touch Action: Plate Cleaned */}
          <button
            onClick={handleAcknowledgePlateClean}
            className={`min-h-[85px] rounded-2xl p-4 flex items-center justify-center gap-3 border transition-all text-base font-bold ${
              status.plateClean
                ? 'bg-slate-900 border-slate-800 text-slate-300'
                : 'bg-emerald-600/90 hover:bg-emerald-500 text-white border-emerald-400 animate-bounce'
            }`}
          >
            <CheckCircle2 className="w-7 h-7 text-emerald-400" />
            <span>Bauplatte geleert &amp; frei</span>
          </button>

          {/* AMS Filament Quick Slots */}
          <div className="bg-slate-900 border border-slate-800 rounded-2xl p-3.5 space-y-2">
            <div className="text-xs text-slate-400 font-semibold uppercase flex items-center justify-between">
              <span>AMS Slots</span>
              <span className="text-[10px] text-emerald-400">4 / 4 Bereit</span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {[
                { name: 'PLA', color: '#00AE42', label: 'Grün' },
                { name: 'PLA', color: '#ffffff', label: 'Weiß' },
                { name: 'PETG', color: '#2563eb', label: 'Blau' },
                { name: 'PLA-CF', color: '#1e293b', label: 'Carbon' },
              ].map((s, idx) => (
                <div key={idx} className="bg-slate-800/80 p-2 rounded-xl border border-slate-700 text-center">
                  <div
                    className="w-4 h-4 rounded-full mx-auto mb-1 border border-white/40"
                    style={{ backgroundColor: s.color }}
                  />
                  <div className="text-xs font-bold">{s.name}</div>
                  <div className="text-[10px] text-slate-400">{s.label}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* Kiosk Footer */}
      <footer className="pt-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-500 font-mono">
        <div>PrintLab 2.0 Enterprise · Touchscreen UI</div>
        <div className="flex items-center gap-3">
          <span>Kiosk-Watchdog: OK (30s)</span>
          <button
            onClick={() => window.location.reload()}
            className="flex items-center gap-1 hover:text-white"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Aktualisieren</span>
          </button>
        </div>
      </footer>
    </div>
  );
}
