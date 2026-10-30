import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ClipboardCheck, Move3d, RotateCcw } from 'lucide-react';

import { api } from '../api/client';
import type { Printer } from '../api/client';
import type { PlateWizardState } from '../api/forkApi';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

const STEPS: { key: string; label: string; hint: string; coords: boolean }[] = [
  { key: 'reference', label: 'Referenzpunkt', hint: 'Achsen auf den Referenzpunkt fahren und die Koordinaten eintragen.', coords: true },
  { key: 'pickup', label: 'Aufnahmeposition', hint: 'Position, an der die Platte aufgenommen wird.', coords: true },
  { key: 'drop', label: 'Ablageposition', hint: 'Position im Magazin, an der die Platte abgelegt wird.', coords: true },
  { key: 'magazine', label: 'Übergabe Magazin (optional)', hint: 'Nur nötig, wenn die Mechanik eine eigene Übergabeposition hat.', coords: true },
  { key: 'door', label: 'Tür und Endschalter', hint: 'Tür von Hand öffnen und schließen; der Endschalter muss den Zustand melden.', coords: false },
  { key: 'dry_run', label: 'Probelauf ohne Platte', hint: 'Ablauf einmal ohne Platte von Hand durchfahren und bestätigen.', coords: false },
];

type Draft = Record<string, { x: string; y: string; z: string; confirmed: boolean; sensor: boolean; note: string }>;

function emptyDraft(): Draft {
  return Object.fromEntries(
    STEPS.map((step) => [step.key, { x: '0', y: '0', z: '0', confirmed: false, sensor: false, note: '' }])
  );
}

/**
 * Einmess-Assistent für den Plattenwechsel: Positionen und Prüfungen festhalten, abschließen, zurücksetzen.
 * Ein begonnener, nicht abgeschlossener Assistent sperrt den Plattenwechsel (auch die Automatik).
 */
export function PlateWizardCard({ canControl }: { canControl: boolean }) {
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const [printerId, setPrinterId] = useState(0);
  const [operator, setOperator] = useState('');
  const [draft, setDraft] = useState<Draft>(emptyDraft);

  const { data: printers = [] } = useQuery<Printer[]>({ queryKey: ['printers'], queryFn: api.getPrinters });
  useEffect(() => {
    if (!printers.some((p) => p.id === printerId)) setPrinterId(printers[0]?.id ?? 0);
  }, [printers, printerId]);

  const { data: state } = useQuery<PlateWizardState>({
    queryKey: ['plateWizard', printerId],
    queryFn: () => api.getPlateWizard(printerId),
    enabled: printerId > 0,
  });

  // Gespeicherte Werte in die Eingabefelder übernehmen, sobald der Stand da ist.
  useEffect(() => {
    if (!state) return;
    const next = emptyDraft();
    for (const step of STEPS) {
      const saved = state.steps[step.key];
      next[step.key] = {
        x: String(saved?.position?.x ?? 0),
        y: String(saved?.position?.y ?? 0),
        z: String(saved?.position?.z ?? 0),
        confirmed: Boolean(saved?.confirmed),
        sensor: Boolean(saved?.sensor),
        note: saved?.note ?? '',
      };
    }
    setDraft(next);
    setOperator(state.operator);
  }, [state]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['plateWizard', printerId] });
  const fail = (error: Error) => showToast(error.message, 'error');

  const save = useMutation({
    mutationFn: ({ step }: { step: string }) => {
      const values = draft[step];
      const payload = step === 'door' || step === 'dry_run'
        ? { confirmed: values.confirmed, sensor: values.sensor, note: values.note }
        : { x: Number(values.x), y: Number(values.y), z: Number(values.z), note: values.note };
      return api.savePlateWizardStep(printerId, step, payload);
    },
    onSuccess: () => {
      showToast('Schritt gespeichert.');
      refresh();
    },
    onError: fail,
  });

  const complete = useMutation({
    mutationFn: () => api.completePlateWizard(printerId, operator),
    onSuccess: () => {
      showToast('Einmessung abgeschlossen.');
      refresh();
    },
    onError: fail,
  });

  const reset = useMutation({
    mutationFn: () => api.resetPlateWizard(printerId),
    onSuccess: () => {
      showToast('Einmessung zurückgesetzt.');
      refresh();
    },
    onError: fail,
  });

  const progress = useMemo(() => {
    if (!state) return { done: 0, total: 0 };
    const done = state.steps_required.filter((step) => state.steps[step]).length;
    return { done, total: state.steps_required.length };
  }, [state]);

  if (printers.length === 0) return null;
  const frozen = Boolean(state?.complete);
  const busy = save.isPending || complete.isPending || reset.isPending;

  return (
    <Card>
      <CardContent className="space-y-3">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Move3d className="w-5 h-5 text-bambu-green" />
          Einmess-Assistent Plattenwechsel
        </h2>
        <p className="text-xs text-bambu-gray">
          Positionen der Mechanik aufnehmen und festhalten. Der Assistent fährt nichts von selbst an und erzeugt keine
          Bewegungsfolge — die Werte sind die Grundlage dafür. Solange er begonnen und nicht abgeschlossen ist, bleibt
          der Plattenwechsel gesperrt.
        </p>

        <label className="text-xs text-bambu-gray block">
          Drucker
          <select
            value={printerId}
            onChange={(event) => setPrinterId(Number(event.target.value))}
            className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-sm text-white"
          >
            {printers.map((printer) => (
              <option key={printer.id} value={printer.id}>
                {printer.name}
              </option>
            ))}
          </select>
        </label>

        {state && (
          <div className="rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-3 py-2 text-xs text-bambu-gray">
            Fortschritt: {progress.done}/{progress.total} Pflichtschritte ·{' '}
            {state.complete
              ? `abgeschlossen${state.operator ? ` von ${state.operator}` : ''}${state.completed_at ? ` am ${state.completed_at.slice(0, 10)}` : ''}`
              : state.started
                ? 'begonnen — Plattenwechsel gesperrt'
                : 'noch nicht begonnen'}
            {state.position_problem ? ` · ${state.position_problem}` : ''}
          </div>
        )}

        <div className="space-y-3">
          {STEPS.map((step) => {
            const saved = state?.steps[step.key];
            const values = draft[step.key];
            const optional = step.key === 'magazine';
            return (
              <div key={step.key} className="rounded-md border border-bambu-dark-tertiary p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-white">
                    {step.label}
                    {optional ? ' · optional' : ''}
                  </span>
                  <span className={`text-xs ${saved ? 'text-bambu-green' : 'text-bambu-gray'}`}>
                    {saved ? 'gespeichert' : 'offen'}
                  </span>
                </div>
                <p className="text-xs text-bambu-gray">{step.hint}</p>

                {step.coords ? (
                  <div className="grid grid-cols-3 gap-2">
                    {(['x', 'y', 'z'] as const).map((axis) => (
                      <label key={axis} className="text-xs text-bambu-gray">
                        {axis.toUpperCase()} (mm)
                        <input
                          type="number"
                          step="0.1"
                          value={values[axis]}
                          disabled={!canControl || frozen}
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              [step.key]: { ...prev[step.key], [axis]: event.target.value },
                            }))
                          }
                          className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
                        />
                      </label>
                    ))}
                  </div>
                ) : (
                  <div className="space-y-1">
                    <label className="flex items-center gap-2 text-xs text-bambu-gray">
                      <input
                        type="checkbox"
                        checked={values.confirmed}
                        disabled={!canControl || frozen}
                        onChange={(event) =>
                          setDraft((prev) => ({
                            ...prev,
                            [step.key]: { ...prev[step.key], confirmed: event.target.checked },
                          }))
                        }
                      />
                      {step.key === 'door' ? 'Tür öffnet und schließt, Ablauf geprüft' : 'Probelauf ohne Platte bestätigt'}
                    </label>
                    {step.key === 'door' && (
                      <label className="flex items-center gap-2 text-xs text-bambu-gray">
                        <input
                          type="checkbox"
                          checked={values.sensor}
                          disabled={!canControl || frozen}
                          onChange={(event) =>
                            setDraft((prev) => ({
                              ...prev,
                              [step.key]: { ...prev[step.key], sensor: event.target.checked },
                            }))
                          }
                        />
                        Endschalter meldet den Türzustand
                      </label>
                    )}
                  </div>
                )}

                <input
                  value={values.note}
                  disabled={!canControl || frozen}
                  onChange={(event) =>
                    setDraft((prev) => ({ ...prev, [step.key]: { ...prev[step.key], note: event.target.value } }))
                  }
                  placeholder="Notiz (optional)"
                  maxLength={200}
                  className="w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
                />
                <Button
                  size="sm"
                  disabled={!canControl || frozen || busy}
                  onClick={() => save.mutate({ step: step.key })}
                >
                  <ClipboardCheck className="w-4 h-4" />
                  Schritt speichern
                </Button>
              </div>
            );
          })}
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <label className="text-xs text-bambu-gray flex-1 min-w-40">
            Eingemessen von
            <input
              value={operator}
              disabled={!canControl || frozen}
              onChange={(event) => setOperator(event.target.value)}
              placeholder="Name"
              maxLength={80}
              className="mt-1 w-full rounded-md border border-bambu-dark-tertiary bg-bambu-dark px-2 py-1.5 text-sm text-white"
            />
          </label>
          <Button
            disabled={!canControl || frozen || busy || Boolean(state?.missing.length)}
            onClick={() => complete.mutate()}
          >
            Abschließen
          </Button>
          <Button
            variant="secondary"
            disabled={!canControl || busy}
            onClick={() => {
              if (window.confirm('Einmessung wirklich verwerfen?')) reset.mutate();
            }}
          >
            <RotateCcw className="w-4 h-4" />
            Zurücksetzen
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
