import { describe, it, expect } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { render } from '../utils';
import { ErrorHelpPage } from '../../pages/ErrorHelpPage';
import { server } from '../mocks/server';

const catalog = {
  categories: [
    { id: 'extrusion', title: 'Extrusion', title_en: 'Extrusion', hint: 'A', hint_en: 'A' },
    { id: 'thermal', title: 'Thermisch', title_en: 'Thermal', hint: 'B', hint_en: 'B' },
  ],
  patterns: [
    {
      id: 'heat_creep',
      category: 'extrusion',
      title: 'Heat Creep',
      title_en: 'Heat creep',
      summary: 'Kurz',
      summary_en: 'Short',
      causes: ['Warm'],
      slicer: [],
      automation: [],
      actions: [],
      rules: [],
    },
    {
      id: 'warping',
      category: 'thermal',
      title: 'Warping',
      title_en: 'Warping',
      summary: 'Kurz',
      summary_en: 'Short',
      causes: ['Zugluft'],
      slicer: [],
      automation: [],
      actions: [],
      rules: [],
    },
  ],
  manual_actions: [
    {
      id: 'chamber_fan_full',
      title: 'Kammerlüfter 100 %',
      title_en: 'Chamber fan 100 %',
      command: 'M106 P3 S255',
      effect: 'Kühlt',
      effect_en: 'Cools',
      requires: 'printing',
    },
  ],
  rules: { chamber_hot: { title: 'Warm', title_en: 'Warm', patterns: [] } },
};

const countermeasures = {
  config: {
    enabled: true,
    dry_run: true,
    printers: {},
    thresholds: { hot_c: 38, cold_c: 45 },
    cooldown_seconds: 600,
    max_per_print: 3,
  },
  rules: catalog.rules,
  printers: [],
};

const aiScan = {
  config: { vision_model: 'qwen3.5:4b', error_scan_enabled: false, error_scan_min_confidence: 60, model: 'qwen2.5:3b' },
  server: { reachable: true, models: ['qwen3.5:4b'], model_present: true, error: '' },
  vision_model: 'qwen3.5:4b',
  vision_present: true,
  findings: [],
  counts: {},
};

function mockApi() {
  server.use(
    http.get('*/api/v1/error-help', () => HttpResponse.json(catalog)),
    http.get('*/api/v1/error-help/countermeasures', () => HttpResponse.json(countermeasures)),
    http.get('*/api/v1/error-help/countermeasures/log', () => HttpResponse.json([])),
    http.get('*/api/v1/error-help/ai-scan', () => HttpResponse.json(aiScan)),
    http.get('*/api/v1/error-help/ai-watch', () =>
      HttpResponse.json({
        config: {
          enabled: false,
          interval_seconds: 600,
          min_confidence: 60,
          min_consecutive: 2,
          action: 'notify',
          cooldown_minutes: 30,
          printers: [],
          frames: 2,
          frame_gap_seconds: 2,
          thresholds: {},
        },
        state: { started: null, last_run: null, last_error: null },
        printers: [],
      })
    ),
    http.get('*/api/v1/failure-images/', () => HttpResponse.json([]))
  );
}

describe('ErrorHelpPage', () => {
  it('lists the catalogue and filters by search', async () => {
    mockApi();
    const user = userEvent.setup();
    render(<ErrorHelpPage />);

    expect(await screen.findByText('Troubleshooting')).toBeInTheDocument();
    expect(await screen.findByTestId('pattern-heat_creep')).toBeInTheDocument();
    expect(screen.getByTestId('pattern-warping')).toBeInTheDocument();
    // Jedes Fehlerbild bringt seine schematische Zeichnung mit (Miniatur,
    // beim aufgeklappten Eintrag zusätzlich groß).
    expect(screen.getAllByTestId('error-illustration-heat_creep').length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('error-illustration-warping').length).toBeGreaterThan(0);

    await user.type(screen.getByRole('searchbox'), 'warp');

    await waitFor(() => expect(screen.queryByTestId('pattern-heat_creep')).not.toBeInTheDocument());
    expect(screen.getByTestId('pattern-warping')).toBeInTheDocument();
  });

  it('filters by category chip', async () => {
    mockApi();
    const user = userEvent.setup();
    render(<ErrorHelpPage />);

    await user.click(await screen.findByRole('button', { name: 'Thermal' }));

    await waitFor(() => expect(screen.queryByTestId('pattern-heat_creep')).not.toBeInTheDocument());
    expect(screen.getByTestId('pattern-warping')).toBeInTheDocument();
  });

  it('shows the automation switches and the safety limits', async () => {
    mockApi();
    render(<ErrorHelpPage />);

    expect(await screen.findByText('Automatic countermeasures')).toBeInTheDocument();
    expect(screen.getByText('Dry run (log only)')).toBeInTheDocument();
    expect(
      screen.getByText(/at most 3 actions per rule and print, at least 600 seconds apart/)
    ).toBeInTheDocument();
    expect(screen.getByText('No actions logged yet.')).toBeInTheDocument();
    expect(screen.getByText('AI error detection (local)')).toBeInTheDocument();
    expect(screen.getByText(/vision model “qwen3\.5:4b” is present/)).toBeInTheDocument();
    expect(screen.getByText('No hits yet.')).toBeInTheDocument();
    expect(screen.getByText('Continuous watch (local)')).toBeInTheDocument();
    expect(screen.getByText('Not checked yet.')).toBeInTheDocument();
  });
});
