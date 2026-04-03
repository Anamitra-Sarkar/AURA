import { useEffect, useMemo, useRef, useState } from 'react';
import type {
  AuraEventRecord,
  AuraMessage,
  AuraMessageResponse,
  AuraSnapshot,
  AuraWebSocketMessage,
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

function createLocalMessage(role: AuraMessage['role'], content: string, details?: Record<string, unknown>): AuraMessage {
  return {
    id: crypto.randomUUID(),
    role,
    content,
    createdAt: now(),
    details,
  };
}

export function useAuraClient() {
  const [messages, setMessages] = useState<AuraMessage[]>([
    createLocalMessage('assistant', 'AURA is ready. Send a task and the live backend will respond here.'),
  ]);
  const [draft, setDraft] = useState('');
  const [importance, setImportance] = useState(2);
  const [snapshot, setSnapshot] = useState<AuraSnapshot | null>(null);
  const [events, setEvents] = useState<AuraEventRecord[]>([]);
  const [connectionState, setConnectionState] = useState<'connecting' | 'connected' | 'disconnected'>('connecting');
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [token, setTokenState] = useState(() => localStorage.getItem(STORAGE_KEY) ?? '');
  const wsRef = useRef<WebSocket | null>(null);

  const authHeaders = useMemo(() => {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (token.trim()) {
      headers.Authorization = `Bearer ${token.trim()}`;
    }
    return headers;
  }, [token]);

  useEffect(() => {
    if (token.trim()) {
      localStorage.setItem(STORAGE_KEY, token.trim());
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, [token]);

  useEffect(() => {
    let cancelled = false;

    async function loadState() {
      try {
        const response = await fetch('/api/state', { headers: authHeaders });
        if (!response.ok) {
          throw new Error(`State request failed (${response.status})`);
        }
        const data = (await response.json()) as AuraSnapshot;
        if (!cancelled) {
          setSnapshot(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load state');
        }
      }
    }

    void loadState();
    return () => {
      cancelled = true;
    };
  }, [authHeaders]);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const socket = new WebSocket(`${protocol}//${window.location.host}/ws/events`);
    wsRef.current = socket;
    setConnectionState('connecting');

    socket.onopen = () => setConnectionState('connected');
    socket.onclose = () => setConnectionState('disconnected');
    socket.onerror = () => setConnectionState('disconnected');
    socket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as AuraWebSocketMessage;
      if (payload.type === 'state_snapshot') {
        setSnapshot(payload.data);
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
      ].slice(0, 20));
    };

    return () => {
      socket.close();
      wsRef.current = null;
    };
  }, []);

  const sendMessage = async () => {
    const text = draft.trim();
    if (!text || isSending) {
      return;
    }

    setIsSending(true);
    setError(null);
    setMessages((current) => [...current, createLocalMessage('user', text)]);
    setDraft('');

    try {
      const response = await fetch('/api/message', {
        method: 'POST',
        headers: authHeaders,
        body: JSON.stringify({ text, importance }),
      });

      if (!response.ok) {
        throw new Error(`Message request failed (${response.status})`);
      }

      const data = (await response.json()) as AuraMessageResponse;
      setMessages((current) => [
        ...current,
        createLocalMessage('assistant', data.response, {
          used_ensemble: data.used_ensemble,
          reasoning_used: data.reasoning_used,
          tools_called: data.tools_called,
        }),
      ]);
    } catch (err) {
      setMessages((current) => [...current, createLocalMessage('assistant', 'The message request failed.')]);
      setError(err instanceof Error ? err.message : 'Failed to send message');
    } finally {
      setIsSending(false);
    }
  };

  return {
    messages,
    draft,
    setDraft,
    importance,
    setImportance,
    snapshot,
    events,
    connectionState,
    isSending,
    error,
    token,
    setToken: setTokenState,
    sendMessage,
  };
}
