import { MoonStar, Send, LogOut, ChevronDown, ChevronRight } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import ReactMarkdown from 'react-markdown';
import { useAuraClient } from './hooks/useAuraClient';
import type { AuraMessage } from './types';

function formatTime(timestamp: string): string {
  return new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function statusClass(status?: string): string {
  if (status === 'error') {
    return 'status-error';
  }
  if (status === 'ready' || status === 'active') {
    return 'status-ready';
  }
  return 'status-idle';
}

function HealthDot({ ok }: { ok: boolean }) {
  return <span className={`health-dot ${ok ? 'status-ready' : 'status-error'}`} aria-hidden="true" />;
}

function AgentDot({ status }: { status?: string }) {
  return <span className={`agent-dot ${statusClass(status)}`} aria-hidden="true" />;
}

function LoginScreen({ client }: { client: ReturnType<typeof useAuraClient> }) {
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await client.login();
  };

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <div className="brand-lockup">
          <div className="brand-word">AURA</div>
          <p>Your personal AI agent</p>
        </div>
        <label className="field">
          <span>Username</span>
          <input value={client.username} onChange={(event) => client.setUsername(event.target.value)} autoComplete="username" />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={client.password} onChange={(event) => client.setPassword(event.target.value)} autoComplete="current-password" />
        </label>
        {client.authError ? <p className="error-text">{client.authError}</p> : null}
        <button type="submit" className="primary-button" disabled={client.isSubmittingAuth || !client.username || !client.password}>
          Sign in
        </button>
      </form>
    </div>
  );
}

function MessageBubble({ message }: { message: AuraMessage }) {
  const isAssistant = message.role === 'assistant';
  const [toolsOpen, setToolsOpen] = useState(false);

  return (
    <article className={`chat-message ${isAssistant ? 'assistant' : 'user'}`}>
      <div className="message-shell">
        {isAssistant ? (
          <>
            {message.isThinking && !message.content ? <div className="thinking">AURA is thinking…</div> : null}
            {message.content ? (
              <div className="markdown">
                <ReactMarkdown>{message.content}</ReactMarkdown>
                {message.isStreaming ? <span className="cursor">▋</span> : null}
              </div>
            ) : null}
          </>
        ) : (
          <div className="user-bubble">
            <p>{message.content}</p>
          </div>
        )}
        <div className="message-footer">
          <span>{isAssistant ? 'AURA' : 'You'}</span>
          <span>{formatTime(message.createdAt)}</span>
        </div>
        {isAssistant && message.tools && message.tools.length > 0 ? (
          <div className="tools-block">
            <button type="button" className="tools-toggle" onClick={() => setToolsOpen((current) => !current)}>
              {toolsOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              Tools used ({message.tools.length})
            </button>
            {toolsOpen ? (
              <div className="tools-list">
                {message.tools.map((tool) => (
                  <div key={`${message.id}-${tool.tool}`} className="tool-row">
                    <strong>{tool.tool}</strong>
                    <span>{tool.summary}</span>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </article>
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
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) {
      return;
    }
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 140)}px`;
  }, [value]);

  const handleKeyDown = async (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      await onSend();
    }
  };

  return (
    <div className="composer">
      <textarea
        ref={textareaRef}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          void handleKeyDown(event);
        }}
        placeholder="Ask AURA to research, plan, browse, or control the PC..."
        rows={1}
      />
      <button type="button" className="primary-button send-button" onClick={() => void onSend()} disabled={disabled || !value.trim()}>
        <Send size={16} />
      </button>
    </div>
  );
}

function AppShell({ client }: { client: ReturnType<typeof useAuraClient> }) {
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement | null>(null);
  const feedScrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!selectedAgentId && client.agents.length > 0) {
      setSelectedAgentId(client.agents[0].id);
    }
  }, [client.agents, selectedAgentId]);

  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [client.messages]);

  useEffect(() => {
    if (feedScrollRef.current) {
      feedScrollRef.current.scrollTop = 0;
    }
  }, [client.toolFeed]);

  const selectedAgent = useMemo(
    () => client.agents.find((agent) => agent.id === selectedAgentId) ?? client.agents[0] ?? null,
    [client.agents, selectedAgentId],
  );

  const health = client.health;

  return (
    <div className={`app-shell theme-${client.theme}`}>
      <header className="header">
        <div className="brand-block">
          <div className="brand-word">AURA</div>
          <span>Your personal AI agent</span>
        </div>
        <div className="header-actions">
          <div className="user-pill">{client.currentUser || 'Signed in'}</div>
          <button type="button" className="ghost-button" onClick={client.toggleTheme}>
            <MoonStar size={16} />
            {client.theme === 'dark' ? 'Dark' : 'Light'}
          </button>
          <button type="button" className="ghost-button" onClick={client.logout}>
            <LogOut size={16} />
            Logout
          </button>
        </div>
      </header>

      <main className="layout">
        <aside className="panel left-panel">
          <div className="panel-heading">
            <h2>Agents</h2>
            <span>{client.agents.length} online cards</span>
          </div>
          <div className="agent-list">
            {client.agents.map((agent) => (
              <button
                key={agent.id}
                type="button"
                className={`agent-row ${selectedAgentId === agent.id ? 'selected' : ''}`}
                onClick={() => setSelectedAgentId(agent.id)}
                title={agent.description}
              >
                <AgentDot status={agent.status || (selectedAgentId === agent.id ? 'ready' : 'idle')} />
                <span>{agent.name}</span>
              </button>
            ))}
          </div>
          <div className="agent-info">
            <div className="agent-info-header">
              <strong>{selectedAgent?.name || 'Select an agent'}</strong>
              <span>{selectedAgent?.id || '—'}</span>
            </div>
            <p>{selectedAgent?.description || 'Click an agent to view its description.'}</p>
          </div>
          <div className="connection-card">
            <AgentDot status={client.connectionState === 'connected' ? 'ready' : 'error'} />
            <span>{client.connectionState === 'connected' ? 'Connected' : 'Disconnected'}</span>
          </div>
        </aside>

        <section className="panel center-panel">
          <div className="panel-heading">
            <h2>Chat</h2>
            <button type="button" className="ghost-button" onClick={() => void client.refreshAll()}>
              Refresh
            </button>
          </div>
          <div className="chat-feed" ref={chatScrollRef}>
            {client.messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {client.isSending ? <div className="skeleton-row" /> : null}
          </div>
          <div className="composer-frame">
            {client.error ? <p className="error-text">{client.error}</p> : null}
            <ChatComposer value={client.draft} onChange={client.setDraft} onSend={client.sendMessage} disabled={client.isSending || !client.isAuthenticated} />
          </div>
        </section>

        <aside className="panel right-panel">
          <div className="panel-heading">
            <h2>Live feed</h2>
            <span>{client.toolFeed.length} events</span>
          </div>
          <div className="feed-list" ref={feedScrollRef}>
            {client.toolFeed.length > 0 ? (
              client.toolFeed.map((entry) => (
                <div className="feed-row" key={entry.id}>
                  <span className="feed-icon">{entry.icon}</span>
                  <div>
                    <strong>{entry.agent}</strong>
                    <p>{entry.action}</p>
                  </div>
                  <time>{formatTime(entry.timestamp)}</time>
                </div>
              ))
            ) : (
              <p className="muted">Waiting for live tool calls...</p>
            )}
          </div>

          <div className="stats-card">
            <div className="stat-row">
              <span>Memory count</span>
              <strong>{client.memoryCount}</strong>
            </div>
            <div className="stat-row">
              <span>Active workflows</span>
              <strong>{client.activeWorkflowsCount}</strong>
            </div>
          </div>

          <div className="health-card">
            <div className="health-row">
              <HealthDot ok={health?.router.ok ?? false} />
              <span>LLM Router</span>
              <strong>{health?.router.ok ? 'Online' : 'Offline'}</strong>
            </div>
            <div className="health-row">
              <HealthDot ok={health?.memory.ok ?? false} />
              <span>Memory</span>
              <strong>{health?.memory.ok ? 'Online' : 'Offline'}</strong>
            </div>
            <div className="health-row">
              <HealthDot ok={health?.local_pc.ok ?? false} />
              <span>Local PC</span>
              <strong>{health?.local_pc.ok ? 'Online' : 'Offline'}</strong>
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
}

export default function App() {
  const client = useAuraClient();
  return client.isAuthenticated ? <AppShell client={client} /> : <LoginScreen client={client} />;
}
