import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useAuth } from '@/_core/hooks/useAuth';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Moon, Sun, LogOut, Send, ChevronDown, ChevronRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { apiUrl, wsUrl } from '@/config';

interface AuraMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  isThinking?: boolean;
  isStreaming?: boolean;
  tools?: Array<{ tool: string; summary: string }>;
}

interface AgentCard {
  id: string;
  name: string;
  description: string;
  status?: string;
}

interface ToolFeedEntry {
  id: string;
  icon: string;
  agent: string;
  action: string;
  timestamp: string;
}

interface HealthState {
  router: { ok: boolean; providers?: Record<string, boolean> };
  memory: { ok: boolean };
  local_pc: { ok: boolean };
  status: string;
}

const AGENT_DESCRIPTIONS: Record<string, string> = {
  IRIS: 'Researches the web and academic sources',
  ATLAS: 'Reads, writes, moves, and organizes files',
  LOGOS: 'Runs and debugs code locally',
  AEGIS: 'Inspects system, clipboard, processes, and controls PC',
  CORTEX: 'Compresses long context and relays it',
  DIRECTOR: 'Plans multi-step workflows with dependencies',
  ECHO: 'Manages events, reminders, and schedules',
  ENSEMBLE: 'Compares multiple model outputs in parallel',
  HERMES: 'Automates browser and desktop UI tasks',
  LYRA: 'Handles voice input and speech output',
  MNEME: 'Stores and recalls memory locally',
  MOSAIC: 'Synthesizes results from many sources',
  'ORACLE DEEP': 'Reasons about tradeoffs and uncertainty',
  PHANTOM: 'Runs background automation and scheduled tasks',
  STREAM: 'Tracks world-awareness feeds and digests',
  NEXUS: 'Coordinates the whole system',
  MOBILE: 'Controls Android devices over ADB',
};

const AGENT_ICONS: Record<string, string> = {
  IRIS: '🔍',
  ATLAS: '📂',
  LOGOS: '💻',
  AEGIS: '🖥️',
  CORTEX: '🧠',
  DIRECTOR: '📋',
  ECHO: '📅',
  ENSEMBLE: '🎼',
  HERMES: '🌐',
  LYRA: '🎤',
  MNEME: '💾',
  MOSAIC: '🎨',
  'ORACLE DEEP': '🔮',
  PHANTOM: '👻',
  STREAM: '📡',
  NEXUS: '🤖',
  MOBILE: '📱',
};

function formatTime(timestamp: string): string {
  try {
    return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function HealthDot({ ok }: { ok: boolean }) {
  return (
    <div
      className={`w-2 h-2 rounded-full ${ok ? 'bg-green-500' : 'bg-red-500'}`}
      aria-hidden="true"
    />
  );
}

function AgentDot({ status }: { status?: string }) {
  const statusClass = {
    ready: 'bg-green-500',
    active: 'bg-blue-500',
    error: 'bg-red-500',
    idle: 'bg-gray-400',
  }[status || 'idle'];

  return <div className={`w-2 h-2 rounded-full ${statusClass}`} aria-hidden="true" />;
}

function LoginScreen() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLogin, setIsLogin] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const endpoint = isLogin ? apiUrl('/api/auth/login') : apiUrl('/api/auth/register');
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `${response.status} Error`);
      }

      const data = await response.json();
      if (data.token || data.jwt_token) {
        localStorage.setItem('aura_token', data.token || data.jwt_token);
        window.location.reload();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Authentication failed');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="w-full max-w-sm bg-card border border-border rounded-lg p-8 shadow-sm">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-primary mb-2">AURA</h1>
          <p className="text-sm text-muted-foreground">Your personal AI agent</p>
        </div>

        <div className="flex gap-2 mb-6 border border-border rounded-md p-1 bg-secondary">
          <button
            type="button"
            onClick={() => { setIsLogin(true); setError(null); }}
            className={`flex-1 py-2 px-3 rounded text-sm font-medium transition-colors ${
              isLogin
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => { setIsLogin(false); setError(null); }}
            className={`flex-1 py-2 px-3 rounded text-sm font-medium transition-colors ${
              !isLogin
                ? 'bg-primary text-primary-foreground'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            Create account
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-foreground mb-2">Username</label>
            <Input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="e.g. anamitra"
              autoComplete="username"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-foreground mb-2">Password</label>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={isLogin ? 'Your password' : 'Choose a strong password'}
              autoComplete={isLogin ? 'current-password' : 'new-password'}
            />
          </div>

          {error && (
            <div className="p-3 bg-destructive/10 border border-destructive/30 rounded text-sm text-destructive">
              {error}
            </div>
          )}

          <Button
            type="submit"
            disabled={isLoading || !username || !password}
            className="w-full"
          >
            {isLoading ? (isLogin ? 'Signing in…' : 'Creating account…') : (isLogin ? 'Sign in' : 'Create account')}
          </Button>
        </form>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: AuraMessage }) {
  const [toolsOpen, setToolsOpen] = useState(false);
  const isAssistant = message.role === 'assistant';

  return (
    <div className={`flex ${isAssistant ? 'justify-start' : 'justify-end'} mb-4`}>
      <div className={`max-w-[70%] ${isAssistant ? '' : 'items-end'}`}>
        {isAssistant ? (
          <div className="bg-card border border-border rounded-lg p-4 text-sm">
            {message.isThinking && !message.content && (
              <p className="text-muted-foreground italic">AURA is thinking…</p>
            )}
            {message.content && (
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <ReactMarkdown>{message.content}</ReactMarkdown>
                {message.isStreaming && <span className="inline-block ml-1 animate-pulse">▋</span>}
              </div>
            )}
          </div>
        ) : (
          <div className="bg-primary text-primary-foreground rounded-lg p-4 text-sm">
            <p>{message.content}</p>
          </div>
        )}

        <div className="flex gap-2 mt-2 text-xs text-muted-foreground">
          <span>{isAssistant ? 'AURA' : 'You'}</span>
          <span>{formatTime(message.createdAt)}</span>
        </div>

        {isAssistant && message.tools && message.tools.length > 0 && (
          <div className="mt-2">
            <button
              type="button"
              onClick={() => setToolsOpen(!toolsOpen)}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              {toolsOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              Tools used ({message.tools.length})
            </button>
            {toolsOpen && (
              <div className="mt-2 space-y-1 bg-secondary p-2 rounded text-xs">
                {message.tools.map((tool, idx) => (
                  <div key={idx} className="border-l-2 border-primary pl-2">
                    <p className="font-medium text-foreground">{tool.tool}</p>
                    <p className="text-muted-foreground">{tool.summary}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ChatComposer({
  value,
  onChange,
  onSend,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
  disabled: boolean;
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
  }, [value]);

  const handleKeyDown = async (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      await onSend();
    }
  };

  return (
    <div className="flex gap-2 p-4 border-t border-border bg-card">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask AURA to research, plan, browse, or control the PC..."
        rows={1}
        className="flex-1 p-3 bg-secondary border border-border rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary"
      />
      <Button
        onClick={() => onSend()}
        disabled={disabled || !value.trim()}
        size="icon"
        className="self-end"
      >
        <Send size={16} />
      </Button>
    </div>
  );
}

export default function AuraDashboard() {
  const { user, logout } = useAuth();
  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [messages, setMessages] = useState<AuraMessage[]>([
    { id: '1', role: 'assistant', content: 'AURA is ready. What can I help you with?', createdAt: new Date().toISOString() },
  ]);
  const [draft, setDraft] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [toolFeed, setToolFeed] = useState<ToolFeedEntry[]>([]);
  const [health, setHealth] = useState<HealthState | null>(null);
  const [memoryCount, setMemoryCount] = useState(0);
  const [activeWorkflows, setActiveWorkflows] = useState(0);
  const [connectionState, setConnectionState] = useState<'connected' | 'disconnected'>('disconnected');
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const feedScrollRef = useRef<HTMLDivElement>(null);

  const token = localStorage.getItem('aura_token');

  // Fetch agents
  useEffect(() => {
    if (!token) return;
    const fetchAgents = async () => {
      try {
        const res = await fetch(apiUrl('/a2a/agents?include_hidden=true'), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setAgents(data);
          if (data.length > 0 && !selectedAgentId) {
            setSelectedAgentId(data[0].id);
          }
        }
      } catch (err) {
        console.error('Failed to fetch agents:', err);
      }
    };
    fetchAgents();
  }, [token, selectedAgentId]);

  // Fetch health
  useEffect(() => {
    if (!token) return;
    const fetchHealth = async () => {
      try {
        const res = await fetch(apiUrl('/api/health'), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          setHealth(await res.json());
        }
      } catch (err) {
        console.error('Failed to fetch health:', err);
      }
    };
    fetchHealth();
    const interval = setInterval(fetchHealth, 5000);
    return () => clearInterval(interval);
  }, [token]);

  // Fetch state
  useEffect(() => {
    if (!token) return;
    const fetchState = async () => {
      try {
        const res = await fetch(apiUrl('/api/state'), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setActiveWorkflows(data.active_workflows?.length || 0);
        }
      } catch (err) {
        console.error('Failed to fetch state:', err);
      }
    };
    fetchState();
    const interval = setInterval(fetchState, 5000);
    return () => clearInterval(interval);
  }, [token]);

  // Fetch memory count
  useEffect(() => {
    if (!token) return;
    const fetchMemoryCount = async () => {
      try {
        const res = await fetch(apiUrl('/api/memories/count'), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const data = await res.json();
          setMemoryCount(data.count || 0);
        }
      } catch (err) {
        console.error('Failed to fetch memory count:', err);
      }
    };
    fetchMemoryCount();
  }, [token]);

  // WebSocket for events
  useEffect(() => {
    if (!token) return;
    const wsUrlString = wsUrl(`/ws/events?token=${encodeURIComponent(token)}`);
    const ws = new WebSocket(wsUrlString);

    ws.onopen = () => setConnectionState('connected');
    ws.onclose = () => setConnectionState('disconnected');
    ws.onerror = () => setConnectionState('disconnected');

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === 'state_snapshot') {
          const state = payload.data;
          setActiveWorkflows(state.active_workflows?.length || 0);
          return;
        }
        const agent = String(payload.data?.agent || payload.data?.agent_id || 'aura');
        const action = String(payload.data?.action || payload.data?.event || 'event');
        const icon = AGENT_ICONS[agent.toUpperCase()] || '🤖';
        setToolFeed((cur) => [
          {
            id: Math.random().toString(),
            icon,
            agent,
            action,
            timestamp: payload.timestamp || new Date().toISOString(),
          },
          ...cur,
        ].slice(0, 50));
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    return () => ws.close();
  }, [token]);

  // Auto-scroll chat
  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Auto-scroll feed
  useEffect(() => {
    if (feedScrollRef.current) {
      feedScrollRef.current.scrollTop = 0;
    }
  }, [toolFeed]);

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === selectedAgentId) ?? agents[0] ?? null,
    [agents, selectedAgentId],
  );

  const handleSendMessage = useCallback(async () => {
    const text = draft.trim();
    if (!text || isSending || !token) return;

    setIsSending(true);
    const userMessage: AuraMessage = {
      id: Math.random().toString(),
      role: 'user',
      content: text,
      createdAt: new Date().toISOString(),
    };

    const assistantId = Math.random().toString();
    setMessages((cur) => [
      ...cur,
      userMessage,
      { id: assistantId, role: 'assistant', content: '', createdAt: new Date().toISOString(), isThinking: true, isStreaming: true },
    ]);
    setDraft('');

    try {
      const response = await fetch(apiUrl('/api/message'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ text, importance: 2 }),
      });

      if (response.status === 401) {
        localStorage.removeItem('aura_token');
        window.location.reload();
        return;
      }

      if (!response.ok || !response.body) {
        throw new Error(`Request failed: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const event = JSON.parse(line.replace('data:', '').trim());
              if (event.token) {
                setMessages((cur) =>
                  cur.map((m) =>
                    m.id === assistantId
                      ? { ...m, content: `${m.content}${event.token}`, isThinking: false, isStreaming: true }
                      : m,
                  ),
                );
              }
              if (event.done) {
                const tools = (event.tools_called || []).map((t: any) => ({
                  tool: t.tool || 'tool',
                  summary: t.summary || 'Completed',
                }));
                setMessages((cur) =>
                  cur.map((m) =>
                    m.id === assistantId
                      ? { ...m, isThinking: false, isStreaming: false, tools: tools.length > 0 ? tools : undefined }
                      : m,
                  ),
                );
              }
            } catch (err) {
              console.error('Failed to parse SSE event:', err);
            }
          }
        }
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      setMessages((cur) =>
        cur.map((m) =>
          m.id === assistantId
            ? { ...m, content: 'Message failed. Please try again.', isThinking: false, isStreaming: false }
            : m,
        ),
      );
    } finally {
      setIsSending(false);
    }
  }, [draft, isSending, token]);

  const toggleTheme = () => {
    const newTheme = theme === 'light' ? 'dark' : 'light';
    setTheme(newTheme);
    document.documentElement.classList.toggle('dark', newTheme === 'dark');
  };

  if (!token) {
    return <LoginScreen />;
  }

  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      {/* Header */}
      <header className="flex items-center justify-between px-4 sm:px-6 py-4 border-b border-border bg-card shadow-sm">
        <div className="flex items-center gap-2 sm:gap-3">
          <h1 className="text-xl sm:text-2xl font-bold text-primary">AURA</h1>
          <span className="hidden sm:inline text-sm text-muted-foreground">Your personal AI agent</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="px-3 py-1 bg-secondary rounded-full text-sm font-medium text-muted-foreground">
            {user?.name || 'Signed in'}
          </div>
          <Button variant="ghost" size="sm" onClick={toggleTheme}>
            {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => { localStorage.removeItem('aura_token'); logout(); }}>
            <LogOut size={16} />
          </Button>
        </div>
      </header>

      {/* Main layout */}
      <div className="flex flex-1 overflow-hidden gap-0">
        {/* Left panel - Agents */}
        <aside className="hidden lg:flex lg:w-64 border-r border-border bg-card flex-col overflow-hidden">
          <div className="p-4 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">Agents</h2>
            <p className="text-xs text-muted-foreground mt-1">{agents.length} online</p>
          </div>

          <div className="flex-1 overflow-y-auto p-2">
            {agents.map((agent) => (
              <button
                key={agent.id}
                onClick={() => setSelectedAgentId(agent.id)}
                className={`w-full text-left px-3 py-2 rounded-lg mb-1 transition-colors flex items-center gap-2 text-sm ${
                  selectedAgentId === agent.id
                    ? 'bg-primary/10 text-primary font-medium'
                    : 'text-foreground hover:bg-secondary'
                }`}
              >
                <AgentDot status={selectedAgentId === agent.id ? 'ready' : 'idle'} />
                <span>{agent.name}</span>
              </button>
            ))}
          </div>

          <div className="p-4 border-t border-border space-y-3">
            <div>
              <p className="text-xs font-semibold text-foreground uppercase tracking-wide mb-1">
                {selectedAgent?.name || 'Select an agent'}
              </p>
              <p className="text-xs text-muted-foreground">
                {selectedAgent?.description || AGENT_DESCRIPTIONS[selectedAgent?.name || ''] || 'Click an agent to view its description.'}
              </p>
            </div>
            <div className="flex items-center gap-2 p-2 bg-secondary rounded-lg">
              <AgentDot status={connectionState === 'connected' ? 'ready' : 'error'} />
              <span className="text-xs font-medium text-foreground">
                {connectionState === 'connected' ? 'Connected' : 'Disconnected'}
              </span>
            </div>
          </div>
        </aside>

        {/* Center panel - Chat */}
        <section className="flex-1 flex flex-col overflow-hidden bg-background">
          <div className="p-4 border-b border-border bg-card">
            <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">Chat</h2>
          </div>

          <div ref={chatScrollRef} className="flex-1 overflow-y-auto p-4">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} />
            ))}
          </div>

          <ChatComposer
            value={draft}
            onChange={setDraft}
            onSend={handleSendMessage}
            disabled={isSending}
          />
        </section>

        {/* Right panel - Feed & Stats */}
        <aside className="hidden xl:flex xl:w-80 border-l border-border bg-card flex-col overflow-hidden">
          <div className="p-4 border-b border-border">
            <h2 className="text-sm font-semibold text-foreground uppercase tracking-wide">Live feed</h2>
            <p className="text-xs text-muted-foreground mt-1">{toolFeed.length} events</p>
          </div>

          <div ref={feedScrollRef} className="flex-1 overflow-y-auto p-3 space-y-2">
            {toolFeed.length > 0 ? (
              toolFeed.map((entry) => (
                <div key={entry.id} className="p-2 bg-secondary rounded-lg text-xs">
                  <div className="flex items-start gap-2">
                    <span className="text-base">{entry.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-foreground">{entry.agent}</p>
                      <p className="text-muted-foreground truncate">{entry.action}</p>
                    </div>
                    <time className="text-muted-foreground whitespace-nowrap">{formatTime(entry.timestamp)}</time>
                  </div>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground text-center py-8">Waiting for live tool calls...</p>
            )}
          </div>

          <div className="p-4 border-t border-border space-y-3">
            <div className="p-3 bg-secondary rounded-lg space-y-2">
              <div className="flex justify-between items-center text-xs">
                <span className="text-muted-foreground">Memory count</span>
                <span className="font-semibold text-foreground">{memoryCount}</span>
              </div>
              <div className="flex justify-between items-center text-xs">
                <span className="text-muted-foreground">Active workflows</span>
                <span className="font-semibold text-foreground">{activeWorkflows}</span>
              </div>
            </div>

            {health && (
              <div className="p-3 bg-secondary rounded-lg space-y-2">
                <div className="pb-2 border-b border-border">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">System Status</span>
                    <span className={`font-semibold ${health.status === 'ok' ? 'text-green-600' : 'text-yellow-600'}`}>
                      {health.status === 'ok' ? 'OK' : 'Degraded'}
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <HealthDot ok={health.router.ok} />
                  <span className="text-muted-foreground">LLM Router</span>
                  <span className="font-semibold text-foreground ml-auto">{health.router.ok ? 'Online' : 'Offline'}</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <HealthDot ok={health.memory.ok} />
                  <span className="text-muted-foreground">Memory</span>
                  <span className="font-semibold text-foreground ml-auto">{health.memory.ok ? 'Online' : 'Offline'}</span>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <HealthDot ok={health.local_pc.ok} />
                  <span className="text-muted-foreground">Local PC</span>
                  <span className="font-semibold text-foreground ml-auto">{health.local_pc.ok ? 'Online' : 'Offline'}</span>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
