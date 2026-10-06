/// <reference types="vite/client" />
import {describe, expect, it} from 'vitest';

describe('frontend module resolution on Windows', () => {
  it('has no source module names that collide when case and extensions are ignored', () => {
    const modules = new Map<string, string[]>();
    for (const file of Object.keys(import.meta.glob('./**/*.{ts,tsx,js,jsx,mts,mjs}'))) {
      const name = String(file).replaceAll('\\', '/');
      if (!/\.[cm]?[jt]sx?$/.test(name)) continue;
      const key = name.replace(/\.[cm]?[jt]sx?$/, '').toLowerCase();
      modules.set(key, [...(modules.get(key) ?? []), name]);
    }
    expect([...modules.values()].filter((names) => names.length > 1)).toEqual([]);
  });
});
