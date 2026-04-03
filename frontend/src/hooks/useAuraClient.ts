import { useEffect, useMemo, useState } from 'react';
import type {
  AuraAgentCard,
  AuraAuthResponse,
  AuraEventRecord,
  AuraMemoryRecord,
  AuraMessage,
  AuraMessageResponse,
  AuraPhantomTask,
  AuraSnapshot,
  AuraWebSocketMessage,
  AuraWorkflowPlan,
} from '../types';

const STORAGE_KEY = 'aura.authToken';

function now(): string {
  return new Date().toISOString();
}

function eventSummary(payload: unknown): string {
  if (payload == null) {
    return '';
  }
  if (typeof payload === 'string') {
    return payload;
  }
  if (typeof payload === 'object') {
    try {
      return JSON.stringify(payload);
    } catch {
      return '[unserializable payload]';
    }
  }
  return String(payload);
}

function createMessage(role: AuraMessage['role'], content: string, details?: Record<string, unknown>): AuraMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    createdAt: now(),
    details,
  };
}

async function readJson<T>(response: Response): Promise<T> {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    throw new Error(await response.text());
  }
  return (await response.json()) as T;
}

export function useAuraClient() {
  const [token, setTokenState] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authError, setAuthError] = useState<string | null>(null);
  const [isSubmittingAuth, setIsSubmittingAuth] = useState(false);
  const [messages, setMessages] = useState<AuraMessage[]>([createMessage('assistant', 'AURA is ready. Authenticate to begin.')]);
  const [draft, setDraft] = useState('');
  const [importance, setImportance] = useState(2);
  const [snapshot, setSnapshot] = useState<AuraSnapshot | null>(null);
  const [events, setEvents] = useState<AuraEventRecord[]>([]);
  const [workflows, setWorkflows] = useState<AuraWorkflowPlan[]>([]);
  const [memories, setMemories] = useState<AuraMemoryRecord[]>([]);
  const [agents, setAgents] = useState<AuraAgentCard[]>([]);
  const [phantomTasks, setPhantomTasks] = useState<AuraPhantomTask[]>([]);
  const [connectionState, setConnectionState] = useState<'connecting' | 'connected' | 'disconnected'>('disconnected');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const authHeaders = useMemo(() => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token.trim()) {
      headers.Authorization = `Bearer ${token.trim()}`;
    }
    return headers;
  }, [token]);

  const isAuthenticated = token.trim().length > 0;
  const needsAuth = !isAuthenticated;

  useEffect(() => {
    if (token.trim()) {
      localStorage.setItem(STORAGE_KEY, token.trim());
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [token]);

  const clearAuth = () => {
    setTokenState('');
    setMessages([createMessage('assistant', 'Session expired. Please log in again.')]);
    setSnapshot(null);
    setWorkflows([]);
    setMemories([]);
    setAgents([]);
    setPhantomTasks([]);
    setEvents([]);
    setConnectionState('disconnected');
  };

  const apiFetch = async <T,>(path: string, init: RequestInit = {}): Promise<T> => {
    const response = await fetch(path, {
      ...init,
      headers: {
        ...authHeaders,
        ...(init.headers as Record<string, string> | undefined),
      },
    });
    if (response.status === 401) {
      clearAuth();
      throw new Error('Unauthorized');
    }
    if (!response.ok) {
      throw new Error(`Request failed (${response.status})`);
    }
    return readJson<T>(response);
  };

  const refreshAll = async () => {
    if (!isAuthenticated) {
      return;
    }
    const [state, workflowData, memoryData, agentData, phantomData] = await Promise.all([
      apiFetch<AuraSnapshot>('/api/state'),
      apiFetch<AuraWorkflowPlan[]>('/api/workflows'),
      apiFetch<AuraMemoryRecord[]>('/api/memories?limit=25'),
      apiFetch<AuraAgentCard[]>('/a2a/agents'),
      apiFetch<AuraPhantomTask[]>('/api/phantom/tasks'),
    ]);
    setSnapshot(state);
    setWorkflows(workflowData);
    setMemories(memoryData);
    setAgents(agentData);
    setPhantomTasks(phantomData);
  };

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        await refreshAll();
        if (!cancelled) {
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to refresh data');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, token]);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/events`);
    setConnectionState('connecting');
    socket.onopen = () => setConnectionState('connected');
    socket.onclose = () => setConnectionState('disconnected');
    socket.onerror = () => setConnectionState('disconnected');
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as AuraWebSocketMessage;
      if (payload.type === 'state_snapshot') {
        setSnapshot(payload.data as AuraSnapshot);
        return;
      }
      setEvents((current) => [
        {
          id: crypto.randomUUID(),
          type: payload.type,
          summary: eventSummary(payload.data),
          timestamp: payload.timestamp,
        },
        ...current,
      ].slice(0, 30));
    };
    return () => {
      socket.close();
    };
  }, [isAuthenticated]);

  const authenticate = async (mode: 'login' | 'register') => {
    setIsSubmittingAuth(true);
    setAuthError(null);
    try {
      const response = await fetch(`/auth/${mode}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        throw new Error(`Authentication failed (${response.status})`);
      }
      const data = (await readJson<AuraAuthResponse>(response)) as AuraAuthResponse;
      setTokenState(data.token || data.jwt_token || '');
      setPassword('');
      setUsername('');
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setIsSubmittingAuth(false);
    }
  };

  const login = async () => authenticate('login');
  const register = async () => authenticate('register');

  const logout = () => {
    clearAuth();
  };

  const sendMessage = async () => {
    const text = draft.trim();
    if (!text || isSending || !isAuthenticated) {
      return;
    }

    setIsSending(true);
    setError(null);
    setMessages((current) => [...current, createMessage('user', text)]);
    setDraft('');
    setMessages((current) => [...current, createMessage('assistant', '…')]);

    try {
      const response = await fetch('/api/message', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ text, importance }),
      });
      if (response.status === 401) {
        clearAuth();
        return;
      }
      if (!response.ok) {
        throw new Error(`Message request failed (${response.status})`);
      }
      const data = (await readJson<AuraMessageResponse>(response)) as AuraMessageResponse;
      setMessages((current) => {
        const withoutPlaceholder = current.slice(0, -1);
        return [...withoutPlaceholder, createMessage('assistant', data.response, {
          used_ensemble: data.used_ensemble,
          reasoning_used: data.reasoning_used,
          tools_called: data.tools_called,
        })];
      });
      await refreshAll();
    } catch (err) {
      setMessages((current) => {
        const withoutPlaceholder = current.slice(0, -1);
        return [...withoutPlaceholder, createMessage('assistant', 'The message request failed.')];
      });
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setIsSending(false);
    }
  };

  const loadMemories = async (query: string) => {
    const url = query.trim() ? `/api/memories?query=${encodeURIComponent(query.trim())}&limit=25` : '/api/memories?limit=25';
    setMemories(await apiFetch<AuraMemoryRecord[]>(url));
  };

  const deleteMemory = async (memoryId: string) => {
    await apiFetch(`/api/memories/${encodeURIComponent(memoryId)}`, { method: 'DELETE' });
    await refreshAll();
  };

  const pauseWorkflow = async (workflowId: string) => {
    await apiFetch(`/api/workflows/${encodeURIComponent(workflowId)}/pause`, { method: 'POST' });
    await refreshAll();
  };

  const resumeWorkflow = async (workflowId: string) => {
    await apiFetch(`/api/workflows/${encodeURIComponent(workflowId)}/resume`, { method: 'POST' });
    await refreshAll();
  };

  const cancelWorkflow = async (workflowId: string) => {
    await apiFetch(`/api/workflows/${encodeURIComponent(workflowId)}`, { method: 'DELETE' });
    await refreshAll();
  };

  const approveWorkflowStep = async (workflowId: string, stepId: string) => {
    await apiFetch(`/api/workflows/${encodeURIComponent(workflowId)}/approve/${encodeURIComponent(stepId)}`, { method: 'POST' });
    await refreshAll();
  };

  const togglePhantomTask = async (taskId: string, enabled: boolean) => {
    await apiFetch(`/api/phantom/tasks/${encodeURIComponent(taskId)}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    });
    await refreshAll();
  };

  const takeScreenshot = async () => {
    return apiFetch<{ path: string }>('/api/aegis/screenshot', {
      method: 'POST',
      body: JSON.stringify({}),
    });
  };

  const refreshAgents = async () => {
    setAgents(await apiFetch<AuraAgentCard[]>('/a2a/agents'));
  };

  const refreshSystem = async () => {
    const data = await apiFetch<AuraSnapshot>('/api/state');
    setSnapshot(data);
    return data;
  };

  return {
    token,
    setToken: setTokenState,
    username,
    setUsername,
    password,
    setPassword,
    authMode,
    setAuthMode,
    authError,
    isSubmittingAuth,
    login,
    register,
    logout,
    isAuthenticated,
    needsAuth,
    messages,
    draft,
    setDraft,
    importance,
    setImportance,
    snapshot,
    events,
    workflows,
    memories,
    agents,
    phantomTasks,
    connectionState,
    isSending,
    error,
    sendMessage,
    refreshAll,
    loadMemories,
    deleteMemory,
    pauseWorkflow,
    resumeWorkflow,
    cancelWorkflow,
    approveWorkflowStep,
    togglePhantomTask,
    takeScreenshot,
    refreshAgents,
    refreshSystem,
  };
}
