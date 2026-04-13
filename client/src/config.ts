/**
 * API Configuration
 * 
 * In production (deployed to Vercel), this points to the HuggingFace backend at port 7860.
 * In development, it uses relative paths to the local dev server.
 */

export const API_BASE = import.meta.env.VITE_API_BASE || '';

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

export function wsUrl(path: string): string {
  if (!API_BASE) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${path}`;
  }
  return API_BASE.replace(/^http/, 'ws') + path;
}
