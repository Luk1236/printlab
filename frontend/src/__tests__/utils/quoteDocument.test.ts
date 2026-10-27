import { describe, it, expect } from 'vitest';
import { buildQuoteDocument } from '../../utils/quoteDocument';

const labels = {
  title: 'Quote',
  material: 'Material',
  energy: 'Energy',
  labor: 'Labor',
  subtotal: 'Subtotal',
  markup: 'Markup',
  total: 'Total',
};
const quote = { currency: 'EUR', inputs: {}, material: 2.2, energy: 0.5, labor: 5, subtotal: 7.7, markup: 1.54, total: 9.24 };

describe('buildQuoteDocument', () => {
  it('contains every line and the total', () => {
    const html = buildQuoteDocument(quote, labels, new Date('2026-10-27T10:00:00Z'));
    for (const label of Object.values(labels)) expect(html).toContain(label);
    expect(html).toMatch(/9[.,]24/);
    expect(html).toContain('<!doctype html>');
  });

  it('escapes labels so no markup can be injected', () => {
    const html = buildQuoteDocument(quote, { ...labels, title: '<script>alert(1)</script>' }, new Date());
    expect(html).not.toContain('<script>');
    expect(html).toContain('&lt;script&gt;');
  });
});
