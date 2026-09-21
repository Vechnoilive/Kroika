import {defineConfig, devices} from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI ? [['line'], ['html', {open: 'never'}]] : 'line',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{name: 'chromium', use: {...devices['Desktop Chrome']}}],
  webServer: [
    {
      name: 'Kroika backend',
      command: 'python -m uvicorn kroika_backend.app:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log',
      cwd: '..',
      url: 'http://127.0.0.1:8000/health/ready',
      timeout: 60_000,
      reuseExistingServer: false,
      env: {
        ...process.env,
        KROIKA_DATABASE_PATH: 'data/current-stage-e2e.db',
        KROIKA_IMAGE_STORAGE_PATH: 'data/current-stage-e2e-images',
        KROIKA_AI_PROVIDER: 'mock',
        KROIKA_ENABLED_AI_PROVIDERS: 'mock,qwen',
        KROIKA_LOG_LEVEL: 'WARNING',
      },
    },
    {
      name: 'Kroika frontend',
      command: 'npm run dev -- --host 127.0.0.1',
      url: 'http://127.0.0.1:5173',
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
