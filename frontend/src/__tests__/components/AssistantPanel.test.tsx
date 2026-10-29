import { describe, it, expect, beforeEach } from 'vitest';
import { http, HttpResponse, delay } from 'msw';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { server } from '../mocks/server';
import { render } from '../utils';
import { AssistantPanel } from '../../components/AssistantPanel';

const config = { enabled: true, base_url: 'http://127.0.0.1:11434', model: 'qwen2.5:3b', timeout_seconds: 180, max_tokens: 500 };
const ready = { reachable: true, models: ['qwen2.5:3b'], model_present: true, error: '' };

let chats: Array<{ messages: Array<{ role: string; content: string }>; lang: string }> = [];
let patches: Array<{ id: string; body: Record<string, unknown> }> = [];
let saved: Array<Record<string, unknown>> = [];

/** Baut einen SSE-Antwortkörper wie /assistant/chat-stream ihn liefert. */
function sse(events: object[]): string {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('');
}

const SSE_HEADERS = { 'content-type': 'text/event-stream' };

function use(over: { config?: Partial<typeof config>; server?: Partial<typeof ready>; answer?: object; chatError?: string; slow?: boolean } = {}) {
  chats = [];
  patches = [];
  saved = [];
  server.use(
    http.get('/api/v1/assistant/status', () => HttpResponse.json({ config: { ...config, ...over.config }, server: { ...ready, ...over.server } })),
    http.put('/api/v1/assistant/config', async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      saved.push(body);
      return HttpResponse.json({ config: { ...config, ...over.config, ...body }, server: { ...ready, ...over.server } });
    }),
    http.post('/api/v1/assistant/chat-stream', async ({ request }) => {
      chats.push((await request.json()) as (typeof chats)[number]);
      if (over.slow) {
        // Erst schweigen („denkt nach“ sichtbar), dann live weitergeben.
        const done = { type: 'done', reply: 'Alles ruhig.', actions: [], rejected: 0, seconds: 4.2, ...(over.answer ?? {}) };
        const stream = new ReadableStream({
          async start(controller) {
            await delay(1200);
            controller.enqueue(new TextEncoder().encode(sse([{ type: 'delta', text: done.reply }])));
            controller.enqueue(new TextEncoder().encode(sse([done])));
            controller.close();
          },
        });
        return new HttpResponse(stream, { headers: SSE_HEADERS });
      }
      if (over.chatError) {
        return new HttpResponse(sse([{ type: 'error', detail: over.chatError }]), { headers: SSE_HEADERS });
      }
      const done = { type: 'done', reply: 'Alles ruhig.', actions: [], rejected: 0, seconds: 4.2, ...(over.answer ?? {}) };
      return new HttpResponse(sse([{ type: 'delta', text: done.reply }, done]), { headers: SSE_HEADERS });
    }),
    http.patch('/api/v1/queue/:id', async ({ params, request }) => {
      patches.push({ id: String(params.id), body: (await request.json()) as Record<string, unknown> });
      return HttpResponse.json({ id: Number(params.id) });
    }),
  );
}

const ask = async (text: string) => {
  await userEvent.type(await screen.findByLabelText(/Ask about operations/), text);
  await userEvent.click(screen.getByRole('button', { name: 'Send' }));
};

describe('AssistantPanel', () => {
  beforeEach(() => {
    chats = [];
    patches = [];
    saved = [];
  });

  it('explains that it is turned off and offers no chat', async () => {
    use({ config: { enabled: false } });
    render(<AssistantPanel canConfigure />);
    expect(await screen.findByTestId('assistant-disabled')).toBeInTheDocument();
    expect(screen.queryByLabelText(/Ask about operations/)).not.toBeInTheDocument();
  });

  it('turns the assistant on with the checkbox', async () => {
    use({ config: { enabled: false } });
    render(<AssistantPanel canConfigure />);
    await userEvent.click(await screen.findByLabelText('Turn on the assistant'));
    await waitFor(() => expect(saved).toEqual([{ enabled: true }]));
  });

  it('saves address, model and time limit', async () => {
    use();
    render(<AssistantPanel canConfigure />);
    const url = await screen.findByLabelText('Model server address');
    await userEvent.clear(url);
    await userEvent.type(url, 'http://192.168.178.34:11434');
    const model = screen.getByLabelText('Model');
    await userEvent.clear(model);
    await userEvent.type(model, 'llama3.2:3b');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(saved.length).toBe(1));
    expect(saved[0]).toEqual({ base_url: 'http://192.168.178.34:11434', model: 'llama3.2:3b', timeout_seconds: 180 });
  });

  it('hides the settings without permission', async () => {
    use();
    render(<AssistantPanel canConfigure={false} />);
    await screen.findByTestId('assistant-suggestions');
    expect(screen.queryByTestId('assistant-config')).not.toBeInTheDocument();
  });

  it.each([
    [{ reachable: false, models: [], model_present: false }, 'Model server not reachable'],
    [{ reachable: true, models: ['other:1b'], model_present: false }, 'but the model "qwen2.5:3b" is missing'],
    [{}, 'Model server reachable, model present'],
  ])('shows the server state %#', async (serverState, text) => {
    use({ server: serverState });
    render(<AssistantPanel canConfigure />);
    expect(await screen.findByTestId('assistant-server')).toHaveTextContent(text);
  });

  it('sends a suggestion, shows the answer and the time it took, and keeps the conversation', async () => {
    use();
    render(<AssistantPanel canConfigure={false} />);
    await userEvent.click(await screen.findByRole('button', { name: 'What is running now and when will everything be done?' }));
    expect(await screen.findByText('Alles ruhig.')).toBeInTheDocument();
    expect(screen.getByText('Answered in 4.2 s')).toBeInTheDocument();
    expect(chats[0]).toEqual({ messages: [{ role: 'user', content: 'What is running now and when will everything be done?' }], lang: 'en' });
    await ask('Und morgen?');
    await waitFor(() => expect(chats.length).toBe(2));
    expect(chats[1].messages.map((m) => m.role)).toEqual(['user', 'assistant', 'user']);
  });

  it('shows that the model is thinking and blocks a second question meanwhile', async () => {
    use({ slow: true });
    render(<AssistantPanel canConfigure={false} />);
    await ask('Hallo');
    expect(await screen.findByRole('status')).toHaveTextContent('The model is thinking');
    expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled();
    expect(await screen.findByText('Alles ruhig.', undefined, { timeout: 3000 })).toBeInTheDocument();
  });

  it('shows a clear error when the model server fails', async () => {
    use({ chatError: 'No model server reachable at http://127.0.0.1:11434. Is Ollama running?' });
    render(<AssistantPanel canConfigure={false} />);
    await ask('Hallo');
    expect(await screen.findByText(/Is Ollama running\?/)).toBeInTheDocument();
  });

  it('can start a new conversation', async () => {
    use();
    render(<AssistantPanel canConfigure={false} />);
    await ask('Hallo');
    await screen.findByText('Alles ruhig.');
    await userEvent.click(screen.getByRole('button', { name: 'New conversation' }));
    expect(screen.queryByText('Alles ruhig.')).not.toBeInTheDocument();
    expect(screen.getByTestId('assistant-suggestions')).toBeInTheDocument();
  });
});

describe('AssistantPanel — suggested changes', () => {
  const answer = {
    reply: 'Das mache ich.',
    actions: [
      { type: 'set_priority', item_id: 12, priority: 2, label: 'Set the priority of item 12 (Gehäuse) to “Urgent”' },
      { type: 'set_due_date', item_id: 13, due_at: null, label: 'Remove the due date of item 13 (Deckel)' },
      { type: 'set_due_date', item_id: 14, due_at: '2026-11-05T09:30:00+00:00', label: 'Set the due date of item 14 (Rahmen) to 2026-11-05 09:30' },
    ],
    rejected: 2,
    seconds: 3,
  };

  it('does nothing until confirmed, then changes exactly the shown item through the queue API', async () => {
    use({ answer });
    render(<AssistantPanel canConfigure={false} />);
    await ask('Mach 12 eilig');
    const box = await screen.findByTestId('assistant-actions');
    expect(patches).toEqual([]);
    expect(within(box).getByText('Nothing happens until you confirm.')).toBeInTheDocument();
    const first = within(box).getByText(/item 12/).parentElement as HTMLElement;
    await userEvent.click(within(first).getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(patches).toEqual([{ id: '12', body: { priority: 2 } }]));
    expect(within(first).getByText('Done')).toBeInTheDocument();
    expect(within(first).queryByRole('button', { name: 'Apply' })).not.toBeInTheDocument();
  });

  it('removes and sets due dates and can dismiss an action', async () => {
    use({ answer });
    render(<AssistantPanel canConfigure={false} />);
    await ask('Termine');
    const box = await screen.findByTestId('assistant-actions');
    const clear = within(box).getByText(/item 13/).parentElement as HTMLElement;
    await userEvent.click(within(clear).getByRole('button', { name: 'Apply' }));
    const set = within(box).getByText(/item 14/).parentElement as HTMLElement;
    await userEvent.click(within(set).getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(patches.length).toBe(2));
    expect(patches).toEqual([
      { id: '13', body: { due_at: null } },
      { id: '14', body: { due_at: '2026-11-05T09:30:00+00:00' } },
    ]);
    const other = within(box).getByText(/item 12/).parentElement as HTMLElement;
    await userEvent.click(within(other).getByRole('button', { name: 'Dismiss' }));
    expect(within(box).queryByText(/item 12/)).not.toBeInTheDocument();
    expect(patches.length).toBe(2);
  });

  it('tells how many suggestions were dropped', async () => {
    use({ answer });
    render(<AssistantPanel canConfigure={false} />);
    await ask('x');
    expect(await screen.findByText('2 suggestion(s) could not be carried out and were dropped.')).toBeInTheDocument();
  });

  it('shows a failed state when the queue update is refused', async () => {
    use({ answer });
    server.use(http.patch('/api/v1/queue/:id', () => HttpResponse.json({ detail: 'Forbidden' }, { status: 403 })));
    render(<AssistantPanel canConfigure={false} />);
    await ask('x');
    const box = await screen.findByTestId('assistant-actions');
    const first = within(box).getByText(/item 12/).parentElement as HTMLElement;
    await userEvent.click(within(first).getByRole('button', { name: 'Apply' }));
    expect(await within(first).findByText('Failed')).toBeInTheDocument();
  });

  it('shows no box when there is nothing to confirm', async () => {
    use();
    render(<AssistantPanel canConfigure={false} />);
    await ask('x');
    await screen.findByText('Alles ruhig.');
    expect(screen.queryByTestId('assistant-actions')).not.toBeInTheDocument();
  });
});
