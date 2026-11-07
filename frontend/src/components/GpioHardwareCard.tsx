import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertOctagon, CheckCircle2, Cpu, Play, RotateCcw, Sliders, Wrench } from 'lucide-react';

import { api } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

interface GpioHardwareCardProps {
  canControl: boolean;
}

export function GpioHardwareCard({ canControl }: GpioHardwareCardProps) {
  const { t } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();

  const { data: gpioStatus, isLoading } = useQuery({
    queryKey: ['gpioStatus'],
    queryFn: api.getGpioStatus,
    refetchInterval: 3000,
  });

  const [minAngle, setMinAngle] = useState<number>(10.0);
  const [maxAngle, setMaxAngle] = useState<number>(154.0);
  const [isCalibratedLoaded, setIsCalibratedLoaded] = useState(false);

  // Synchronisiere geladene Servowinkel einmalig
  if (gpioStatus?.servo_calibration && !isCalibratedLoaded) {
    setMinAngle(gpioStatus.servo_calibration.min_angle ?? 10.0);
    setMaxAngle(gpioStatus.servo_calibration.max_angle ?? 154.0);
    setIsCalibratedLoaded(true);
  }

  // Not-Halt auslösen
  const triggerEstopMutation = useMutation({
    mutationFn: api.triggerGpioEstop,
    onSuccess: () => {
      showToast(t('hardware.estopTriggered', 'Not-Halt ausgelöst! Alle Motoren stromlos.'), 'error');
      queryClient.invalidateQueries({ queryKey: ['gpioStatus'] });
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // Not-Halt quittieren
  const resetEstopMutation = useMutation({
    mutationFn: api.resetGpioEstop,
    onSuccess: (data) => {
      showToast(data.message || t('hardware.estopReset', 'Not-Halt erfolgreich quittiert.'), 'success');
      queryClient.invalidateQueries({ queryKey: ['gpioStatus'] });
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // Servowinkel testen
  const testServoMutation = useMutation({
    mutationFn: (angle: number) => api.testServo(angle),
    onSuccess: (data) => {
      showToast(data.message, 'success');
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // Kalibrierung speichern
  const calibrateServoMutation = useMutation({
    mutationFn: () => api.calibrateServo(minAngle, maxAngle),
    onSuccess: (data) => {
      showToast(data.message, 'success');
      queryClient.invalidateQueries({ queryKey: ['gpioStatus'] });
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  // GPIO Konfiguration togglen
  const toggleGpioMutation = useMutation({
    mutationFn: (enabled: boolean) => api.updateGpioConfig({ enabled }),
    onSuccess: () => {
      showToast(t('common.saved', 'Gespeichert'), 'success');
      queryClient.invalidateQueries({ queryKey: ['gpioStatus'] });
    },
    onError: (err: Error) => showToast(err.message, 'error'),
  });

  const isEstop = gpioStatus?.estop_triggered ?? false;

  return (
    <Card className={`border transition-colors ${isEstop ? 'border-red-500/80 bg-red-950/20' : 'border-bambu-dark-tertiary'}`}>
      <CardContent className="space-y-5 p-5">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Cpu className="w-5 h-5 text-bambu-green" />
            <div>
              <h2 className="text-base font-semibold text-white">
                {t('hardware.gpioTitle', 'Hardware-Taster, GPIO & Not-Halt (Raspberry Pi)')}
              </h2>
              <p className="text-xs text-bambu-gray">
                {t('hardware.gpioSubtitle', 'Physische Taster-Entprellung, Not-Aus-Schleife & Servo-Türkalibrierung')}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span
              className={`text-xs px-2 py-0.5 rounded-full border font-mono ${
                gpioStatus?.is_simulated
                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
                  : 'bg-bambu-green/10 text-bambu-green border-bambu-green/30'
              }`}
            >
              {gpioStatus?.is_simulated ? 'GPIO Simulation' : 'Raspberry Pi GPIO Aktiv'}
            </span>

            {canControl && (
              <Button
                size="sm"
                variant={gpioStatus?.enabled ? 'secondary' : 'primary'}
                onClick={() => toggleGpioMutation.mutate(!gpioStatus?.enabled)}
                disabled={toggleGpioMutation.isPending}
                className="text-xs"
              >
                {gpioStatus?.enabled ? t('common.deactivate', 'Deaktivieren') : t('common.activate', 'Aktivieren')}
              </Button>
            )}
          </div>
        </div>

        {/* Not-Halt Banner & Action Controls */}
        <div className={`p-4 rounded-xl border flex flex-col sm:flex-row items-center justify-between gap-4 ${
          isEstop ? 'bg-red-900/40 border-red-500 text-red-100' : 'bg-bambu-dark-secondary/60 border-bambu-dark-tertiary text-white'
        }`}>
          <div className="flex items-center gap-3">
            {isEstop ? (
              <AlertOctagon className="w-8 h-8 text-red-400 animate-pulse shrink-0" />
            ) : (
              <CheckCircle2 className="w-8 h-8 text-bambu-green shrink-0" />
            )}
            <div>
              <div className="font-bold text-sm tracking-wide">
                {isEstop ? 'NOT-HALT VERRIEGELT (STOPP AKTIV)' : 'System betriebsbereit (Normalbetrieb)'}
              </div>
              <div className="text-xs opacity-80">
                {isEstop
                  ? `Ausgelöst durch: ${gpioStatus?.estop_source ?? 'Unbekannt'}. Motoren sind stromlos, Drucke gesperrt.`
                  : 'Kein Not-Aus aktiv. Taster-Eingänge werden überwacht.'}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto">
            {isEstop ? (
              <Button
                variant="primary"
                onClick={() => resetEstopMutation.mutate()}
                disabled={!canControl || resetEstopMutation.isPending}
                className="w-full sm:w-auto bg-bambu-green hover:bg-bambu-green/80 text-black font-semibold flex items-center justify-center gap-1.5"
              >
                <RotateCcw className="w-4 h-4" />
                <span>{t('hardware.resetEstop', 'Not-Halt quittieren & freigeben')}</span>
              </Button>
            ) : (
              <Button
                variant="danger"
                onClick={() => triggerEstopMutation.mutate()}
                disabled={!canControl || triggerEstopMutation.isPending}
                className="w-full sm:w-auto bg-red-600 hover:bg-red-700 text-white font-semibold flex items-center justify-center gap-1.5 shadow-lg shadow-red-950/50"
              >
                <AlertOctagon className="w-4 h-4" />
                <span>{t('hardware.triggerEstop', 'NOT-HALT AUSLÖSEN')}</span>
              </Button>
            )}
          </div>
        </div>

        {/* Live Pin-Status Grid */}
        <div className="space-y-2">
          <div className="text-xs uppercase tracking-wider text-bambu-gray font-medium">
            {t('hardware.pinStates', 'Hardware-Eingänge & Pinbelegung')}
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            <div className="p-3 bg-bambu-dark-secondary rounded-lg border border-bambu-dark-tertiary">
              <div className="text-[10px] text-bambu-gray uppercase">Not-Halt (E-Stop)</div>
              <div className="text-xs font-semibold text-white mt-0.5">GPIO 26 (Pin 37)</div>
              <div className="mt-2 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${gpioStatus?.pins?.estop?.active ? 'bg-red-500 animate-ping' : 'bg-bambu-green'}`} />
                <span className="text-[11px] text-bambu-gray">
                  {gpioStatus?.pins?.estop?.active ? 'Betätigt (Offen)' : 'Geschlossen (OK)'}
                </span>
              </div>
            </div>

            <div className="p-3 bg-bambu-dark-secondary rounded-lg border border-bambu-dark-tertiary">
              <div className="text-[10px] text-bambu-gray uppercase">Quittiertaster (ACK)</div>
              <div className="text-xs font-semibold text-white mt-0.5">GPIO 16 (Pin 36)</div>
              <div className="mt-2 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${gpioStatus?.pins?.button_ack?.active ? 'bg-bambu-green' : 'bg-bambu-gray/40'}`} />
                <span className="text-[11px] text-bambu-gray">
                  {gpioStatus?.pins?.button_ack?.active ? 'Gedrückt' : 'Ruhezustand'}
                </span>
              </div>
            </div>

            <div className="p-3 bg-bambu-dark-secondary rounded-lg border border-bambu-dark-tertiary">
              <div className="text-[10px] text-bambu-gray uppercase">Pause / Resume</div>
              <div className="text-xs font-semibold text-white mt-0.5">GPIO 20 (Pin 38)</div>
              <div className="mt-2 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${gpioStatus?.pins?.button_pause?.active ? 'bg-amber-400' : 'bg-bambu-gray/40'}`} />
                <span className="text-[11px] text-bambu-gray">
                  {gpioStatus?.pins?.button_pause?.active ? 'Gedrückt' : 'Ruhezustand'}
                </span>
              </div>
            </div>

            <div className="p-3 bg-bambu-dark-secondary rounded-lg border border-bambu-dark-tertiary">
              <div className="text-[10px] text-bambu-gray uppercase">Status-LED</div>
              <div className="text-xs font-semibold text-white mt-0.5">GPIO 21 (Pin 40)</div>
              <div className="mt-2 flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${isEstop ? 'bg-red-500 animate-pulse' : 'bg-bambu-green'}`} />
                <span className="text-[11px] text-bambu-gray capitalize">
                  {gpioStatus?.led_state ?? 'Bereit'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Servo-Kalibrierungs-Assistent */}
        <div className="p-4 bg-bambu-dark-secondary rounded-xl border border-bambu-dark-tertiary space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Sliders className="w-4 h-4 text-bambu-green" />
              <span className="text-sm font-semibold text-white">
                {t('hardware.servoCalibration', 'Tür-Servo Feinjustierung & Endlagen')}
              </span>
            </div>
            <span className="text-[11px] text-bambu-gray">GPIO 18 (PWM Pin 12)</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Tür Zu Winkel */}
            <div className="space-y-1.5 bg-bambu-dark/50 p-3 rounded-lg border border-bambu-dark-tertiary/60">
              <div className="flex items-center justify-between text-xs">
                <span className="text-white font-medium">Tür ZU (Standard 10°)</span>
                <span className="font-mono text-bambu-green font-bold">{minAngle.toFixed(1)}°</span>
              </div>
              <input
                type="range"
                min="0"
                max="90"
                step="0.5"
                value={minAngle}
                onChange={(e) => setMinAngle(parseFloat(e.target.value))}
                className="w-full accent-bambu-green h-1.5 bg-bambu-dark rounded-lg cursor-pointer"
              />
              <div className="pt-1 flex justify-end">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => testServoMutation.mutate(minAngle)}
                  disabled={!canControl || testServoMutation.isPending}
                  className="text-xs flex items-center gap-1"
                >
                  <Play className="w-3 h-3" />
                  <span>{t('hardware.testAngle', 'Anfahren')}</span>
                </Button>
              </div>
            </div>

            {/* Tür Offen Winkel */}
            <div className="space-y-1.5 bg-bambu-dark/50 p-3 rounded-lg border border-bambu-dark-tertiary/60">
              <div className="flex items-center justify-between text-xs">
                <span className="text-white font-medium">Tür OFFEN (Standard 154°)</span>
                <span className="font-mono text-bambu-green font-bold">{maxAngle.toFixed(1)}°</span>
              </div>
              <input
                type="range"
                min="90"
                max="180"
                step="0.5"
                value={maxAngle}
                onChange={(e) => setMaxAngle(parseFloat(e.target.value))}
                className="w-full accent-bambu-green h-1.5 bg-bambu-dark rounded-lg cursor-pointer"
              />
              <div className="pt-1 flex justify-end">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => testServoMutation.mutate(maxAngle)}
                  disabled={!canControl || testServoMutation.isPending}
                  className="text-xs flex items-center gap-1"
                >
                  <Play className="w-3 h-3" />
                  <span>{t('hardware.testAngle', 'Anfahren')}</span>
                </Button>
              </div>
            </div>
          </div>

          <div className="flex justify-end pt-1">
            <Button
              size="sm"
              variant="primary"
              onClick={() => calibrateServoMutation.mutate()}
              disabled={!canControl || calibrateServoMutation.isPending}
              className="text-xs flex items-center gap-1.5 bg-bambu-green text-black font-semibold"
            >
              <Wrench className="w-3.5 h-3.5" />
              <span>{t('hardware.saveCalibration', 'Servowinkel dauerhaft speichern')}</span>
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
