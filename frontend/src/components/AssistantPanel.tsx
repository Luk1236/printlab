import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, Send } from 'lucide-react';

import { api } from '../api/client';
import type { AssistantAction, AssistantStatus } from '../api/client';
import { Button } from './Button';
import { Card, CardContent } from './Card';
import { useToast } from '../contexts/ToastContext';

interface Turn {
  role: 'user' | 'assistant';
  content: string;
  actions?: AssistantAction[];
  rejected?: number;
  seconds?: number;
}

type ActionState = 'pending' | 'done' | 'failed' | 'dismissed';

const SUGGESTIONS = ['suggestRunning', 'suggestWaiting', 'suggestError', 'suggestText'] as const;

/**
 * Lokaler KI-Assistent: Fragen zum Betrieb, Fehler erklären, Texte entwerfen. Das Modell läuft auf einem lokalen
 * Modell-Server (Standard: Ollama auf dem Pi). Änderungen schlägt der Assistent nur vor; ausgeführt wird erst nach
 * Bestätigung hier über die normalen Warteschlangen-Funktionen (mit deren Rechteprüfung).
 */
export function AssistantPanel({ canConfigure }: { canConfigure: boolean }) {
  const { t, i18n } = useTranslation();
  const { showToast } = useToast();
  const queryClient = useQueryClient();
  const lang = i18n.language.startsWith('de') ? 'de' : 'en';
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [actionStates, setActionStates] = useState<Record<string, ActionState>>({});
  const [form, setForm] = useState<{ base_url: string; model: string; timeout_seconds: string } | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const streamControl = useRef<AbortController | null>(null);

  const { data: status } = useQuery<AssistantStatus>({ queryKey: ['assistantStatus'], queryFn: api.getAssistantStatus });
  const config = status?.config;
  const draft = form ?? (config ? { base_url: config.base_url, model: config.model, timeout_seconds: String(config.timeout_seconds) } : null);

  const saveConfig = useMutation({
    mutationFn: (update: Record<string, unknown>) => api.saveAssistantConfig(update),
    onSuccess: (saved) => {
      queryClient.setQueryData(['assistantStatus'], saved);
      setForm(null);
      showToast(t('assistant.saved'));
    },
    onError: (error: Error) => showToast(error.message, 'error'),
  });

  useEffect(() => {
    if (!pending) return;
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [pending]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' });
  }, [turns, pending]);

  // Wort-für-Wort: das letzte Drehbuch ist der Live-Turn am Ende der Liste; geprüfte Aktionen kommen erst im
  // Abschluss-Ereignis (nichts ändert sich ohne Bestätigung).
  const send = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || pending) return;
    const userTurns: { role: 'user' | 'assistant'; content: string }[] = [
      ...turns.map(({ role, content }) => ({ role, content } as { role: 'user' | 'assistant'; content: string })),
      { role: 'user', content: trimmed },
    ];
    setTurns([...turns, { role: 'user', content: trimmed }, { role: 'assistant', content: '' }]);
    setInput('');
    streamControl.current?.abort();
    const controller = new AbortController();
    streamControl.current = controller;
    let live = '';
    setPending(true);
    api
      .streamAssistantChat(userTurns, lang, (delta) => {
        live += delta;
        setTurns((prev) => {
          // Der Live-Turn ist der letzte Eintrag — es sei denn, jemand hat das Gespräch inzwischen geleert.
          if (!prev.length || prev[prev.length - 1].role !== 'assistant') return prev;
          const copy = [...prev];
          copy[copy.length - 1] = { ...copy[copy.length - 1], content: live };
          return copy;
        });
      }, controller.signal)
      .then((answer) =>
        setTurns((prev) => {
          if (!prev.length || prev[prev.length - 1].role !== 'assistant') return prev;
          const copy = [...prev];
          copy[copy.length - 1] = {
            role: 'assistant',
            content: answer.reply,
            actions: answer.actions,
            rejected: answer.rejected,
            seconds: answer.seconds,
          };
          return copy;
        }),
      )
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setTurns((prev) => (prev.length && prev[prev.length - 1].role === 'assistant' && !prev[prev.length - 1].content
          ? prev.slice(0, -1)
          : prev));
        showToast(error instanceof Error ? error.message : t('assistant.streamAborted'), 'error');
      })
      .finally(() => {
        if (streamControl.current === controller) streamControl.current = null;
        setPending(false);
      });
  };

  const runAction = async (key: string, action: AssistantAction) => {
    try {
      await api.updateQueueItem(
        action.item_id,
        action.type === 'set_priority' ? { priority: action.priority } : { due_at: action.due_at ?? null },
      );
      setActionStates((prev) => ({ ...prev, [key]: 'done' }));
      queryClient.invalidateQueries({ queryKey: ['queue'] });
    } catch (error) {
      setActionStates((prev) => ({ ...prev, [key]: 'failed' }));
      showToast(error instanceof Error ? error.message : t('common.error'), 'error');
    }
  };

  const server = status?.server;
  const setField = (patch: Partial<NonNullable<typeof draft>>) => draft && setForm({ ...draft, ...patch });

  return (
    <Card>
      <CardContent className="space-y-4" data-testid="assistant-panel">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Bot className="w-5 h-5 text-bambu-green" />
            {t('assistant.title')}
          </h2>
          <div className="flex items-center gap-2">
            {pending && (
              <Button size="sm" variant="ghost" onClick={() => streamControl.current?.abort()}>
                {t('assistant.stop')}
              </Button>
            )}
            {turns.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  streamControl.current?.abort();
                  setTurns([]);
                  setActionStates({});
                }}
              >
                {t('assistant.newChat')}
              </Button>
            )}
          </div>
        </div>
        <p className="text-xs text-bambu-gray">{t('assistant.intro')}</p>

        {canConfigure && draft && (
          <div className="rounded-lg border border-bambu-dark-tertiary p-3 space-y-3" data-testid="assistant-config">
            <label className="flex items-center gap-2 text-sm text-white">
              <input
                type="checkbox"
                checked={config?.enabled ?? false}
                disabled={saveConfig.isPending}
                onChange={(event) => saveConfig.mutate({ enabled: event.target.checked })}
              />
              {t('assistant.enable')}
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <label className="text-xs text-bambu-gray sm:col-span-2">
                {t('assistant.baseUrl')}
                <input
                  value={draft.base_url}
                  onChange={(event) => setField({ base_url: event.target.value })}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm font-mono"
                />
              </label>
              <label className="text-xs text-bambu-gray">
                {t('assistant.model')}
                <input
                  value={draft.model}
                  onChange={(event) => setField({ model: event.target.value })}
                  list="assistant-model-list"
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm font-mono"
                />
                <datalist id="assistant-model-list">
                  {(server?.models ?? []).map((model) => (
                    <option key={model} value={model} />
                  ))}
                </datalist>
              </label>
              <label className="text-xs text-bambu-gray">
                {t('assistant.timeout')}
                <input
                  type="number"
                  min={10}
                  max={900}
                  value={draft.timeout_seconds}
                  onChange={(event) => setField({ timeout_seconds: event.target.value })}
                  className="mt-1 w-full bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                disabled={saveConfig.isPending}
                onClick={() => saveConfig.mutate({ base_url: draft.base_url, model: draft.model, timeout_seconds: Number(draft.timeout_seconds) })}
              >
                {t('assistant.save')}
              </Button>
              {server && (
                <span
                  className={`text-xs ${server.reachable && server.model_present ? 'text-bambu-green' : 'text-amber-700 dark:text-amber-400'}`}
                  data-testid="assistant-server"
                >
                  {!server.reachable
                    ? t('assistant.serverDown')
                    : server.model_present
                      ? t('assistant.serverOk')
                      : t('assistant.serverNoModel', { model: config?.model })}
                </span>
              )}
            </div>
            {server?.reachable && server.models.length > 0 && (
              <p className="text-[11px] text-bambu-gray">{t('assistant.serverModels', { list: server.models.join(', ') })}</p>
            )}
            {(!server?.reachable || !server?.model_present) && <p className="text-[11px] text-bambu-gray">{t('assistant.setupHint')}</p>}
            {server?.reachable && <p className="text-[11px] text-bambu-gray">{t('assistant.keepAliveHint')}</p>}
          </div>
        )}

        {config && !config.enabled ? (
          <p className="text-sm text-bambu-gray" data-testid="assistant-disabled">
            {t('assistant.disabled')}
          </p>
        ) : (
          <>
            {turns.length === 0 && (
              <div className="flex flex-wrap gap-2" data-testid="assistant-suggestions">
                {SUGGESTIONS.map((key) => (
                  <Button key={key} size="sm" variant="secondary" disabled={pending} onClick={() => send(t(`assistant.${key}`))}>
                    {t(`assistant.${key}`)}
                  </Button>
                ))}
              </div>
            )}
            <div className="space-y-3 max-h-[28rem] overflow-y-auto" aria-live="polite">
              {turns.map((turn, index) => (
                <div key={index} className={turn.role === 'user' ? 'text-right' : ''} data-testid={`turn-${turn.role}`}>
                  <div className="text-[11px] text-bambu-gray mb-0.5">{t(turn.role === 'user' ? 'assistant.roleUser' : 'assistant.roleAssistant')}</div>
                  <div
                    className={`inline-block max-w-full whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-sm text-left ${
                      turn.role === 'user' ? 'bg-bambu-green/15 text-white' : 'bg-bambu-dark-tertiary text-bambu-gray-light'
                    }`}
                  >
                    {turn.content}
                  </div>
                  {turn.seconds != null && <div className="text-[10px] text-bambu-gray mt-0.5">{t('assistant.took', { seconds: turn.seconds })}</div>}
                  {turn.actions && turn.actions.length > 0 && (
                    <div className="mt-2 rounded-lg border border-bambu-green/40 p-2 space-y-2 text-left" data-testid="assistant-actions">
                      <p className="text-xs font-medium text-white">{t('assistant.actionsTitle')}</p>
                      {turn.actions.map((action, n) => {
                        const key = `${index}-${n}`;
                        const state = actionStates[key] ?? 'pending';
                        if (state === 'dismissed') return null;
                        return (
                          <div key={key} className="flex flex-wrap items-center gap-2 text-xs">
                            <span className="text-white flex-1 min-w-40">{action.label}</span>
                            {state === 'pending' ? (
                              <>
                                <Button size="sm" onClick={() => runAction(key, action)}>
                                  {t('assistant.apply')}
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setActionStates((prev) => ({ ...prev, [key]: 'dismissed' }))}>
                                  {t('assistant.dismiss')}
                                </Button>
                              </>
                            ) : (
                              <span className={state === 'done' ? 'text-bambu-green' : 'text-red-700 dark:text-red-400'}>
                                {t(state === 'done' ? 'assistant.applied' : 'assistant.failed')}
                              </span>
                            )}
                          </div>
                        );
                      })}
                      <p className="text-[11px] text-bambu-gray">{t('assistant.actionsHint')}</p>
                    </div>
                  )}
                  {turn.rejected != null && turn.rejected > 0 && (
                    <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">{t('assistant.rejected', { count: turn.rejected })}</p>
                  )}
                </div>
              ))}
              {pending && turns[turns.length - 1]?.role === 'assistant' && !turns[turns.length - 1]?.content && (
                <p className="text-xs text-bambu-gray" role="status">
                  {t('assistant.thinking', { seconds: elapsed })}
                </p>
              )}
              <div ref={bottom} />
            </div>
            <form
              className="flex items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                send(input);
              }}
            >
              <textarea
                value={input}
                rows={2}
                maxLength={4000}
                placeholder={t('assistant.placeholder')}
                aria-label={t('assistant.placeholder')}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    send(input);
                  }
                }}
                className="flex-1 bg-bambu-dark-tertiary border border-bambu-dark-tertiary rounded-lg px-2 py-1.5 text-white text-sm"
              />
              <Button type="submit" size="sm" disabled={!input.trim() || pending} aria-label={t('assistant.send')}>
                <Send className="w-4 h-4" />
              </Button>
            </form>
          </>
        )}
        <p className="text-[11px] text-bambu-gray">{t('assistant.footer')}</p>
      </CardContent>
    </Card>
  );
}
