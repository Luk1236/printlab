import { describe, it, expect } from 'vitest';
import { buildStatsDocument } from '../../utils/statsDocument';

const labels = {
  title: 'Print statistics', period: 'Period', prints: 'Prints', successful: 'Successful', failed: 'Failed',
  time: 'Time', filament: 'Filament', filamentCost: 'Filament cost', energy: 'Energy', energyCost: 'Energy cost',
};
const stats = {
  total_prints: 12, successful_prints: 10, failed_prints: 2, cancelled_prints: 0, total_print_time_hours: 34.56,
  total_filament_grams: 812.4, total_cost: 17.9, prints_by_filament_type: {}, prints_by_printer: {},
  average_time_accuracy: null, time_accuracy_by_printer: null, total_energy_kwh: 4.1234, total_energy_cost: 1.44,
};

describe('buildStatsDocument', () => {
  it('lists the key figures of the period', () => {
    const html = buildStatsDocument(stats, labels, '2026-10-01 – 2026-10-31', 'EUR', new Date('2026-11-01T10:00:00Z'));
    expect(html).toContain('2026-10-01 – 2026-10-31');
    expect(html).toContain('34.6 h');
    expect(html).toContain('812 g');
    expect(html).toContain('EUR 17.90');
    expect(html).toContain('4.123 kWh');
  });

  it('escapes the period text and labels', () => {
    const html = buildStatsDocument(stats, { ...labels, title: '<img src=x onerror=1>' }, '<b>x</b>', 'EUR', new Date());
    expect(html).not.toContain('<img');
    expect(html).not.toContain('<b>x');
  });
});
