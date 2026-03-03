import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup-vitest.ts'],
    include: ['tests/unit/**/*.test.ts'],
    coverage: {
      reporter: ['text', 'lcov'],
    },
  },
});
