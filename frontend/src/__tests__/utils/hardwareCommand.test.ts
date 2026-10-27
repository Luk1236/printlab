import { describe, it, expect } from 'vitest';
import { commandToDraft, draftToCommand } from '../../utils/hardwareCommand';

describe('hardware command drafts', () => {
  it('shows text as text and a list as JSON', () => {
    expect(commandToDraft('servo open')).toBe('servo open');
    expect(commandToDraft(['servo', 'open'])).toBe('["servo","open"]');
    expect(commandToDraft(undefined)).toBe('');
  });

  it('turns a JSON list back into a list', () => {
    expect(draftToCommand('["servo","open"]')).toEqual(['servo', 'open']);
    expect(draftToCommand('  ["a b", "c"]  ')).toEqual(['a b', 'c']);
  });

  it('keeps everything else as text, including broken or mixed JSON', () => {
    expect(draftToCommand('servo open')).toBe('servo open');
    expect(draftToCommand('["servo", ')).toBe('["servo", ');
    expect(draftToCommand('["servo", 3]')).toBe('["servo", 3]');
  });
});
