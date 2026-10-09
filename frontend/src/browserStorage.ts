// Browser recovery storage is optional; server persistence must still work without it.
export const browserStorage = {
  getItem(key: string): string | null {
    try {return window.localStorage.getItem(key);} catch {return null;}
  },
  setItem(key: string, value: string): void {
    try {window.localStorage.setItem(key, value);} catch { /* Keep server saving available. */ }
  },
  removeItem(key: string): void {
    try {window.localStorage.removeItem(key);} catch { /* Storage may be disabled. */ }
  },
};
