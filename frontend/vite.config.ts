import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const backendUrl = env.VITE_API_BASE || 'http://localhost:7860';

  return {
    plugins: [react()],
    define: {
      // Expose to runtime bundle so useAuraClient can read it
      __VITE_API_BASE__: JSON.stringify(env.VITE_API_BASE || ''),
    },
    server: {
      port: 5173,
      proxy: {
        '/api': { target: backendUrl, changeOrigin: true },
        '/auth': { target: backendUrl, changeOrigin: true },
        '/ws':  { target: backendUrl, changeOrigin: true, ws: true },
        '/a2a': { target: backendUrl, changeOrigin: true },
        '/mcp': { target: backendUrl, changeOrigin: true },
      },
    },
  };
});
