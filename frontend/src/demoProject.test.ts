import {describe, expect, it, vi} from 'vitest';
import {makeDemoProject} from './demoProject';

describe('makeDemoProject', () => {
  it('creates a valid-looking isolated draft without hidden measurements', () => {
    vi.stubGlobal('crypto', {randomUUID: vi.fn()
      .mockReturnValueOnce('11111111-1111-4111-8111-111111111111')
      .mockReturnValueOnce('22222222-2222-4222-8222-222222222222')
      .mockReturnValueOnce('33333333-3333-4333-8333-333333333333')
      .mockReturnValueOnce('44444444-4444-4444-8444-444444444444')
      .mockReturnValueOnce('55555555-5555-4555-8555-555555555555')});
    const project = makeDemoProject('  Проба  ');

    expect(project.name).toBe('Проба');
    expect(project.revision).toBe(1);
    expect(project.status).toBe('draft');
    expect(project.body_measurements.status).toBe('draft');
    expect(project.body_measurements.values).toEqual({});
    expect(project.body_measurements.angles_deg).toEqual({});
    expect((project.privacy as {allow_external_ai: boolean}).allow_external_ai).toBe(false);
    vi.unstubAllGlobals();
  });
});
