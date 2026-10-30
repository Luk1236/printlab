import { describe, expect, it } from 'vitest';

import {
  flattenFolderTree,
  pickNumber,
  pickObject,
  pickString,
  proxyCdn,
  proxyCdnUrlsInHtml,
} from '../../utils/makerworld';

describe('makerworld pickers', () => {
  it('reads only the expected types and falls back to empty values', () => {
    const payload: Record<string, unknown> = { title: 'Vase', likes: 12, design: { id: 1 }, tags: ['a'] };
    expect(pickString(payload, 'title')).toBe('Vase');
    expect(pickString(payload, 'likes')).toBe('');
    expect(pickString(undefined, 'title')).toBe('');
    expect(pickNumber(payload, 'likes')).toBe(12);
    expect(pickNumber(payload, 'title')).toBeNull();
    expect(pickObject(payload, 'design')).toEqual({ id: 1 });
    expect(pickObject(payload, 'tags')).toBeUndefined();
  });
});

describe('proxyCdn', () => {
  it('routes MakerWorld CDN hosts through the own thumbnail proxy', () => {
    expect(proxyCdn('https://makerworld.bblmw.com/a/b.png')).toBe(
      '/api/v1/makerworld/thumbnail?url=https%3A%2F%2Fmakerworld.bblmw.com%2Fa%2Fb.png',
    );
    expect(proxyCdn('https://public-cdn.bblmw.com/x.png')).toContain('/api/v1/makerworld/thumbnail');
  });

  it('leaves other hosts and empty values alone', () => {
    expect(proxyCdn('https://example.com/x.png')).toBe('https://example.com/x.png');
    expect(proxyCdn('')).toBe('');
  });

  it('rewrites CDN urls inside description html', () => {
    const html = '<p><img src="https://makerworld.bblmw.com/a.png"> und <b>Text</b></p>';
    const rewritten = proxyCdnUrlsInHtml(html);
    expect(rewritten).toContain('/api/v1/makerworld/thumbnail?url=');
    expect(rewritten).not.toContain('makerworld.bblmw.com/a.png"');
    expect(rewritten).toContain('<b>Text</b>');
  });
});

describe('flattenFolderTree', () => {
  it('walks depth-first and keeps the depth for indentation', () => {
    const tree = {
      id: 1,
      name: 'Wurzel',
      children: [
        { id: 2, name: 'Kind', children: [{ id: 3, name: 'Enkel', children: [] }] },
        { id: 4, name: 'Geschwister', children: [] },
      ],
    };
    const flat = flattenFolderTree(tree);
    expect(flat.map((entry) => [entry.folder.name, entry.depth])).toEqual([
      ['Wurzel', 0],
      ['Kind', 1],
      ['Enkel', 2],
      ['Geschwister', 1],
    ]);
  });
});
