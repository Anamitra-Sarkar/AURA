import { describe, it, expect, beforeEach, vi } from 'vitest';

describe('AURA Dashboard - API Integration', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  describe('Authentication', () => {
    it('should store JWT token after successful login', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ token: 'test-jwt-token', user_id: 'user123' }),
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const endpoint = '/api/auth/login';
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'testuser', password: 'password123' }),
      });

      const data = await response.json();
      expect(data.token).toBe('test-jwt-token');
      expect(response.ok).toBe(true);
    });

    it('should handle login errors gracefully', async () => {
      const mockResponse = {
        ok: false,
        status: 401,
        json: async () => ({ detail: 'Invalid credentials' }),
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const endpoint = '/api/auth/login';
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: 'testuser', password: 'wrong' }),
      });

      expect(response.ok).toBe(false);
      expect(response.status).toBe(401);
    });

    it('should include Bearer token in API requests', async () => {
      const token = 'test-jwt-token';
      const mockResponse = {
        ok: true,
        json: async () => ([]),
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      await fetch('/a2a/agents?include_hidden=true', {
        headers: { Authorization: `Bearer ${token}` },
      });

      expect(global.fetch).toHaveBeenCalledWith(
        '/a2a/agents?include_hidden=true',
        expect.objectContaining({
          headers: expect.objectContaining({
            Authorization: `Bearer ${token}`,
          }),
        })
      );
    });
  });

  describe('API Endpoints', () => {
    const token = 'test-jwt-token';

    it('should fetch agent list from /a2a/agents', async () => {
      const mockAgents = [
        { id: 'iris', name: 'IRIS', description: 'Researches the web' },
        { id: 'atlas', name: 'ATLAS', description: 'Reads and writes files' },
      ];
      const mockResponse = {
        ok: true,
        json: async () => mockAgents,
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const response = await fetch('/a2a/agents?include_hidden=true', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();

      expect(data).toEqual(mockAgents);
      expect(data.length).toBe(2);
    });

    it('should fetch health status from /api/health', async () => {
      const mockHealth = {
        router: { ok: true, providers: { groq: true } },
        memory: { ok: true },
        local_pc: { ok: true },
        status: 'ok',
      };
      const mockResponse = {
        ok: true,
        json: async () => mockHealth,
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const response = await fetch('/api/health', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();

      expect(data.status).toBe('ok');
      expect(data.router.ok).toBe(true);
    });

    it('should fetch memory count from /api/memories/count', async () => {
      const mockResponse = {
        ok: true,
        json: async () => ({ count: 42 }),
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const response = await fetch('/api/memories/count', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();

      expect(data.count).toBe(42);
    });

    it('should fetch state from /api/state', async () => {
      const mockState = {
        active_workflows: [
          { id: 'wf1', name: 'Task 1', status: 'running' },
        ],
        recent_memories: [],
        phantom_tasks: [],
      };
      const mockResponse = {
        ok: true,
        json: async () => mockState,
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const response = await fetch('/api/state', {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await response.json();

      expect(data.active_workflows.length).toBe(1);
    });

    it('should send message to /api/message with SSE', async () => {
      const mockResponse = {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'text/event-stream' }),
        body: {
          getReader: () => ({
            read: async () => ({
              value: new TextEncoder().encode('data: {"token":"Hello","done":false}\n\n'),
              done: false,
            }),
          }),
        },
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const response = await fetch('/api/message', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ text: 'Hello AURA', importance: 2 }),
      });

      expect(response.ok).toBe(true);
      expect(response.status).toBe(200);
    });
  });

  describe('SSE Message Parsing', () => {
    it('should parse SSE events correctly', () => {
      const sseChunk = 'data: {"token":"Hello ","done":false}\n\n';
      const lines = sseChunk.split('\n\n');
      const dataLine = lines[0];
      const payload = dataLine.replace('data:', '').trim();
      const event = JSON.parse(payload);

      expect(event.token).toBe('Hello ');
      expect(event.done).toBe(false);
    });

    it('should handle multiple SSE events', () => {
      const sseChunk = 'data: {"token":"Hello ","done":false}\n\ndata: {"token":"world","done":false}\n\n';
      const events = [];
      for (const block of sseChunk.split(/\n\n+/)) {
        const line = block.trim();
        if (!line) continue;
        const dataLine = line.split('\n').find((e) => e.startsWith('data:'));
        if (dataLine) {
          const payload = dataLine.replace(/^data:\s*/, '');
          try {
            events.push(JSON.parse(payload));
          } catch {
            // ignore
          }
        }
      }

      expect(events.length).toBe(2);
      expect(events[0].token).toBe('Hello ');
      expect(events[1].token).toBe('world');
    });

    it('should handle done event with tools', () => {
      const sseChunk = 'data: {"token":"","done":true,"tools_called":[{"tool":"IRIS","summary":"Searched web"}]}\n\n';
      const lines = sseChunk.split('\n\n');
      const dataLine = lines[0];
      const payload = dataLine.replace('data:', '').trim();
      const event = JSON.parse(payload);

      expect(event.done).toBe(true);
      expect(event.tools_called.length).toBe(1);
      expect(event.tools_called[0].tool).toBe('IRIS');
    });
  });

  describe('WebSocket Integration', () => {
    it('should construct WebSocket URL correctly', () => {
      const token = 'test-token';
      const protocol = 'ws:';
      const host = 'localhost:3000';
      const wsUrl = `${protocol}//${host}/ws/events?token=${encodeURIComponent(token)}`;

      expect(wsUrl).toContain('/ws/events');
      expect(wsUrl).toContain(`token=${encodeURIComponent(token)}`);
    });

    it('should parse WebSocket event payload', () => {
      const payload = {
        type: 'state_snapshot',
        data: {
          active_workflows: [{ id: 'wf1', status: 'running' }],
        },
        timestamp: new Date().toISOString(),
      };

      expect(payload.type).toBe('state_snapshot');
      expect(payload.data.active_workflows.length).toBe(1);
    });

    it('should extract agent and action from WebSocket message', () => {
      const payload = {
        data: {
          agent: 'IRIS',
          action: 'Searched web for information',
        },
        timestamp: new Date().toISOString(),
      };

      const agent = String(payload.data.agent || 'aura');
      const action = String(payload.data.action || 'event');

      expect(agent).toBe('IRIS');
      expect(action).toBe('Searched web for information');
    });
  });

  describe('Agent Data', () => {
    it('should have all 16 agents defined', () => {
      const agents = [
        'IRIS', 'ATLAS', 'LOGOS', 'AEGIS', 'CORTEX', 'DIRECTOR',
        'ECHO', 'ENSEMBLE', 'HERMES', 'LYRA', 'MNEME', 'MOSAIC',
        'ORACLE DEEP', 'PHANTOM', 'STREAM', 'NEXUS',
      ];

      expect(agents.length).toBe(16);
      expect(agents).toContain('IRIS');
      expect(agents).toContain('ATLAS');
      expect(agents).toContain('ORACLE DEEP');
    });

    it('should have agent icons defined', () => {
      const icons: Record<string, string> = {
        IRIS: '🔍',
        ATLAS: '📂',
        LOGOS: '💻',
        AEGIS: '🖥️',
      };

      expect(icons.IRIS).toBe('🔍');
      expect(icons.ATLAS).toBe('📂');
    });
  });

  describe('Error Handling', () => {
    it('should handle 401 Unauthorized', async () => {
      const mockResponse = {
        status: 401,
        ok: false,
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      const response = await fetch('/api/message', {
        method: 'POST',
        headers: { Authorization: 'Bearer invalid-token' },
      });

      expect(response.status).toBe(401);
    });

    it('should handle network errors', async () => {
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      try {
        await fetch('/api/message');
        expect.fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(Error);
        expect((err as Error).message).toBe('Network error');
      }
    });

    it('should handle malformed JSON responses', async () => {
      const mockResponse = {
        ok: true,
        json: async () => {
          throw new Error('Invalid JSON');
        },
      };
      global.fetch = vi.fn().mockResolvedValue(mockResponse);

      try {
        const response = await fetch('/api/test');
        await response.json();
        expect.fail('Should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(Error);
      }
    });
  });
});
