import { useCallback, useEffect, useMemo, useState } from 'react';
import type {
  AuraAgentCard,
  AuraAuthResponse,
  AuraHealthState,
  AuraMessage,
  AuraMessageStreamEvent,
  AuraStateSnapshot,
  AuraToolFeedEntry,
  AuraToolSummary,
} from '../types';

// ---------------------------------------------------------------------------
// API base URL
// When deployed to Vercel (static), __VITE_API_BASE__ is injected at build
// time via vite.config.ts define. It points to the HuggingFace FastAPI backend.
// When served directly by FastAPI (HF Space), it is empty string → relative paths.
// ---------------------------------------------------------------------------
declare const __VITE_API_BASE__: string;
const API_BASE: string = (typeof __VITE_API_BASE__ !== 'undefined' ? __VITE_API_BASE__ : '').replace(/\/$/, '');

function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

function wsUrl(path: string): string {
  if (!API_BASE) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}${path}`;
  }
  // Convert https://host → wss://host
  return API_BASE.replace(/^http/, 'ws') + path;
}

function now(): string {
  return new Date().toISOString();
}

function createMessage(role: AuraMessage['role'], content: string, overrides: Partial<AuraMessage> = {}): AuraMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    createdAt: now(),
    ...overrides,
  };
}

function safeJson(value: unknown): string {
  if (value == null) {
    return '';
  }
  if (typeof value === 'string') {
    return value;
  }
  try {
    return JSON.stringify(value);
  } catch {
    return '[unserializable]';
  }
}

function summarizeStep(step: { tool?: string; result?: unknown; error?: string } | string): AuraToolSummary {
  if (typeof step === 'string') {
    return { tool: step, summary: 'Completed' };
  }
  const tool = step.tool || 'tool';
  if (step.error) {
    return { tool, summary: `Error: ${step.error}` };
  }
  const result = step.result;
  if (result && typeof result === 'object' && 'message' in result) {
    return { tool, summary: safeJson((result as { message?: unknown }).message) };
  }
  return { tool, summary: safeJson(result).slice(0, 160) || 'Completed' };
}

function summarizeFeedPayload(payload: unknown): { agent: string; action: string } {
  if (payload == null) {
    return { agent: 'aura', action: 'event' };
  }
  if (typeof payload === 'string') {
    return { agent: 'aura', action: payload };
  }
  if (typeof payload !== 'object') {
    return { agent: 'aura', action: String(payload) };
  }
  const data = payload as Record<string, unknown>;
  const agent = String(data.agent || data.agent_id || data.source || data.tool || 'aura');
  const action = String(data.action || data.tool || data.event || data.type || safeJson(payload));
  return { agent, action };
}

function iconForAgent(agent: string): string {
  const mapping: Record<string, string> = {
    atlas: '📂',
    hermes: '🌐',
    logos: '💻',
    aegis: '🖥️',
    echo: '📅',
    mneme: '🧠',
    iris: '🔍',
  };
  return mapping[agent.toLowerCase()] || '🤖';
}

async function readJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(await response.text());
  }
  return (await response.json()) as T;
}

function parseSseChunk(chunk: string): AuraMessageStreamEvent[] {
  const events: AuraMessageStreamEvent[] = [];
  for (const block of chunk.split(/\n\n+/)) {
    const line = block.trim();
    if (!line) {
      continue;
    }
    const dataLine = line.split('\n').find((entry) => entry.startsWith('data:'));
    if (!dataLine) {
      continue;
    }
    const payload = dataLine.replace(/^data:\s*/, '');
    try {
      events.push(JSON.parse(payload) as AuraMessageStreamEvent);
    } catch {
      continue;
    }
  }
  return events;
}

export function useAuraClient() {
  const [token, setToken] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const [currentUser, setCurrentUser] = useState('');
  const [messages, setMessages] = useState<AuraMessage[]>([createMessage('assistant', 'AURA is ready. Please sign in to continue.')]);
  const [draft, setDraft] = useState('');
  const [importance, setImportance] = useState(2);
  const [agents, setAgents] = useState<AuraAgentCard[]>([]);
  const [toolFeed, setToolFeed] = useState<AuraToolFeedEntry[]>([]);
  const [health, setHealth] = useState<AuraHealthState | null>(null);
  const [snapshot, setSnapshot] = useState<AuraStateSnapshot | null>(null);
  const [memoryCount, setMemoryCount] = useState(0);
  const [activeWorkflowsCount, setActiveWorkflowsCount] = useState(0);
  const [connectionState, setConnectionState] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');

  const isAuthenticated = token.trim().length > 0;

  const authHeaders = useMemo(() => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token.trim()) {
      headers.Authorization = `Bearer ${token.trim()}`;
    }
    return headers;
  }, [token]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const clearAuth = useCallback(() => {
    setToken('');
    setCurrentUser('');
    setMessages([createMessage('assistant', 'Session expired. Please sign in again.')]);
    setAgents([]);
    setToolFeed([]);
    setHealth(null);
    setSnapshot(null);
    setMemoryCount(0);
    setActiveWorkflowsCount(0);
    setConnectionState('disconnected');
    setError(null);
  }, []);

  const buildHeaders = useCallback(
    (overrideToken?: string, initHeaders?: HeadersInit) => {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const activeToken = overrideToken?.trim() || token.trim();
      if (activeToken) {
        headers.Authorization = `Bearer ${activeToken}`;
      }
      return {
        ...headers,
        ...(initHeaders as Record<string, string> | undefined),
      };
    },
    [token],
  );

  const apiFetch = useCallback(
    async <T,>(path: string, init: RequestInit = {}, overrideToken?: string): Promise<T> => {
      const response = await fetch(apiUrl(path), {
        ...init,
        headers: buildHeaders(overrideToken, init.headers),
      });
      if (response.status === 401) {
        clearAuth();
        throw new Error('Unauthorized');
      }
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      return readJson<T>(response);
    },
    [buildHeaders, clearAuth],
  );

  const refreshAll = useCallback(
    async (overrideToken?: string) => {
      const activeToken = overrideToken?.trim() || token.trim();
      if (!activeToken) {
        return;
      }
      const [state, healthData, agentData, countData] = await Promise.all([
        apiFetch<AuraStateSnapshot>('/api/state', {}, activeToken),
        apiFetch<AuraHealthState>('/api/health', {}, activeToken),
        apiFetch<AuraAgentCard[]>('/a2a/agents?include_hidden=true', {}, activeToken),
        apiFetch<{ count: number }>('/api/memories/count', {}, activeToken),
      ]);
      setSnapshot(state);
      setHealth(healthData);
      setAgents(agentData);
      setMemoryCount(countData.count);
      setActiveWorkflowsCount(state.active_workflows.length);
      setToolFeed((current) => current.slice(0, 50));
    },
    [apiFetch, token],
  );

  const refreshSystem = useCallback(
    async (overrideToken?: string) => {
      const activeToken = overrideToken?.trim() || token.trim();
      if (!activeToken) {
        return;
      }
      const [healthData, countData, state] = await Promise.all([
        apiFetch<AuraHealthState>('/api/health', {}, activeToken),
        apiFetch<{ count: number }>('/api/memories/count', {}, activeToken),
        apiFetch<AuraStateSnapshot>('/api/state', {}, activeToken),
      ]);
      setHealth(healthData);
      setMemoryCount(countData.count);
      setSnapshot(state);
      setActiveWorkflowsCount(state.active_workflows.length);
    },
    [apiFetch, token],
  );

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const [state, healthData, agentsData, countData] = await Promise.all([
          apiFetch<AuraStateSnapshot>('/api/state'),
          apiFetch<AuraHealthState>('/api/health'),
          apiFetch<AuraAgentCard[]>('/a2a/agents?include_hidden=true'),
          apiFetch<{ count: number }>('/api/memories/count'),
        ]);
        if (cancelled) {
          return;
        }
        setSnapshot(state);
        setHealth(healthData);
        setAgents(agentsData);
        setMemoryCount(countData.count);
        setActiveWorkflowsCount(state.active_workflows.length);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load AURA');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [apiFetch, isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    const socket = new WebSocket(`${wsUrl('/ws/events')}?token=${encodeURIComponent(token)}`);
    setConnectionState('connecting');
    socket.onopen = () => setConnectionState('connected');
    socket.onclose = () => setConnectionState('disconnected');
    socket.onerror = () => setConnectionState('disconnected');
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as { type: string; data: unknown; timestamp: string };
      if (payload.type === 'state_snapshot') {
        const state = payload.data as AuraStateSnapshot;
        setSnapshot(state);
        setActiveWorkflowsCount(state.active_workflows.length);
        return;
      }
      const { agent, action } = summarizeFeedPayload(payload.data);
      setToolFeed((current) => [
        {
          id: crypto.randomUUID(),
          icon: iconForAgent(agent),
          agent,
          action,
          timestamp: payload.timestamp,
        },
        ...current,
      ].slice(0, 50));
    };
    return () => {
      socket.close();
    };
  }, [isAuthenticated, token]);

  const login = useCallback(async () => {
    setIsSubmittingAuth(true);
    setAuthError(null);
    try {
      const response = await fetch(apiUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        throw new Error(`Authentication failed (${response.status})`);
      }
      const data = await readJson<AuraAuthResponse>(response);
      const tokenValue = data.token || data.jwt_token || '';
      setToken(tokenValue);
      setCurrentUser(data.user_id || username);
      setPassword('');
      await refreshAll(tokenValue);
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setIsSubmittingAuth(false);
    }
  }, [password, refreshAll, username]);

  const logout = useCallback(() => {
    clearAuth();
  }, [clearAuth]);

  const sendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || isSending || !isAuthenticated) {
      return;
    }

    setIsSending(true);
    setError(null);
    const userMessage = createMessage('user', text);
    const assistantId = crypto.randomUUID();
    setMessages((current) => [
      ...current,
      userMessage,
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        createdAt: now(),
        isThinking: true,
        isStreaming: true,
      },
    ]);
    setDraft('');

    try {
      const response = await fetch(apiUrl('/api/message'), {
        method: 'POST',
        headers: {
          ...authHeaders,
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ text, importance }),
      });
      if (response.status === 401) {
        clearAuth();
        return;
      }
      if (!response.ok || response.body == null) {
        throw new Error(`Message request failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let sawToken = false;

      const updateAssistant = (updater: (message: AuraMessage) => AuraMessage) => {
        setMessages((current) =>
          current.map((message) => (message.id === assistantId ? updater(message) : message)),
        );
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const segments = buffer.split('\n\n');
        buffer = segments.pop() || '';
        const events = segments.flatMap((segment) => parseSseChunk(`${segment}\n\n`));
        for (const event of events) {
          if (event.token) {
            sawToken = true;
            updateAssistant((message) => ({
              ...message,
              content: `${message.content}${event.token || ''}`,
              isThinking: false,
              isStreaming: true,
            }));
          }
          if (event.done) {
            const steps = event.steps || [];
            const tools = steps.length > 0 ? steps.map((step) => summarizeStep(step)) : (event.tools_called || []).map((tool) => summarizeStep(tool));
            updateAssistant((message) => ({
              ...message,
              isThinking: false,
              isStreaming: false,
              tools,
            }));
          }
        }
      }

      if (!sawToken) {
        updateAssistant((message) => ({
          ...message,
          content: message.content || 'No response returned.',
          isThinking: false,
          isStreaming: false,
        }));
      }
      await refreshSystem();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Message failed');
      updateAssistant((message) => ({
        ...message,
        content: message.content || 'Message failed.',
        isThinking: false,
        isStreaming: false,
      }));
    } finally {
      setIsSending(false);
    }
  }, [authHeaders, clearAuth, draft, importance, isAuthenticated, isSending, refreshSystem]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === 'dark' ? 'light' : 'dark'));
  }, []);

  return {
    token,
    setToken,
    username,
    setUsername,
    password,
    setPassword,
    authError,
    isSubmittingAuth,
    currentUser,
    isAuthenticated,
    messages,
    setMessages,
    draft,
    setDraft,
    importance,
    setImportance,
    agents,
    toolFeed,
    health,
    snapshot,
    memoryCount,
    activeWorkflowsCount,
    connectionState,
    isSending,
    error,
    theme,
    setTheme,
    login,
    logout,
    sendMessage,
    refreshAll,
    refreshSystem,
    toggleTheme,
  };
}
