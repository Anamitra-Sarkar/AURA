import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { Bot, Cpu, FileText, MoonStar, Send, Settings, Workflow } from 'lucide-react';
import { useMemo } from 'react';
import { ChatMessage } from './components/ChatMessage';
import { useAuraClient } from './hooks/useAuraClient';

const pages = [
  { to: '/', label: 'Chat', icon: Bot },
  { to: '/workflows', label: 'Workflows', icon: Workflow },
  { to: '/memory', label: 'Memory', icon: FileText },
  { to: '/system', label: 'System', icon: Cpu },
  { to: '/settings', label: 'Settings', icon: Settings },
];

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">AURA</div>
        <nav>
          {pages.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}>
              <Icon size={16} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="main">
        <header className="topbar">
          <div>
            <div className="eyebrow">Fully local · Fully free</div>
            <h1>{title}</h1>
          </div>
          <div className="status-pill">
            <MoonStar size={14} />
            Dark
          </div>
        </header>
        <section className="content">{children}</section>
      </main>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {children}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ChatRoute() {
  const client = useAuraClient();

  const workflowCount = client.snapshot?.active_workflows.length ?? 0;
  const memoryCount = client.snapshot?.recent_memories.length ?? 0;
  const eventCount = client.events.length;

  const voiceModeLabel = useMemo(() => {
    if (!client.snapshot?.lyra_status) {
      return 'Unknown';
    }
    return client.snapshot.lyra_status.voice_mode ? 'On' : 'Off';
  }, [client.snapshot]);

  return (
    <div className="workspace">
      <div className="workspace-main">
        <Card title="Command console">
          <div className="status-row">
            <Metric label="Connection" value={client.connectionState} />
            <Metric label="Workflows" value={`${workflowCount}`} />
            <Metric label="Memories" value={`${memoryCount}`} />
            <Metric label="Lyra" value={voiceModeLabel} />
          </div>

          <div className="chat-log">
            {client.messages.map((message) => (
              <ChatMessage key={message.id} message={message} />
            ))}
          </div>

          <form
            className="chat-form"
            onSubmit={async (event) => {
              event.preventDefault();
              await client.sendMessage();
            }}
          >
            <label className="field">
              <span>Bearer token</span>
              <input
                value={client.token}
                onChange={(event) => client.setToken(event.target.value)}
                placeholder="Optional if auth is disabled"
                autoComplete="off"
              />
            </label>
            <label className="field field-expand">
              <span>Task</span>
              <textarea
                rows={5}
                value={client.draft}
                onChange={(event) => client.setDraft(event.target.value)}
                placeholder="Ask AURA to plan, research, control the PC, or summarize the current state."
              />
            </label>
            <div className="row">
              <label className="field">
                <span>Importance</span>
                <select value={client.importance} onChange={(event) => client.setImportance(Number(event.target.value))}>
                  <option value={1}>Quick</option>
                  <option value={2}>Normal</option>
                  <option value={3}>Deep</option>
                  <option value={4}>Ensemble</option>
                </select>
              </label>
              <button type="submit" disabled={client.isSending || !client.draft.trim()}>
                <Send size={16} />
                {client.isSending ? 'Sending' : 'Send'}
              </button>
            </div>
            {client.error ? <p className="error">{client.error}</p> : null}
          </form>
        </Card>
      </div>

      <aside className="workspace-side">
        <Card title="Live state">
          <div className="summary-list">
            <div>
              <h3>System health</h3>
              <p>
                CPU {client.snapshot?.system_health.cpu_pct ?? '—'}% · RAM {client.snapshot?.system_health.ram_pct ?? '—'}% · Disk{' '}
                {client.snapshot?.system_health.disk_pct ?? '—'}%
              </p>
            </div>
            <div>
              <h3>Lyra</h3>
              <p>
                Listening: {client.snapshot?.lyra_status.listening ? 'yes' : 'no'} · Voice mode: {voiceModeLabel} · Engine:{' '}
                {client.snapshot?.lyra_status.wake_engine ?? '—'}
              </p>
            </div>
            <div>
              <h3>Recent events</h3>
              <p>{eventCount} websocket event{eventCount === 1 ? '' : 's'} captured</p>
            </div>
          </div>

          <div className="panel-list">
            <section>
              <h3>Active workflows</h3>
              {client.snapshot?.active_workflows.length ? (
                client.snapshot.active_workflows.map((workflow) => (
                  <div className="panel-item" key={workflow.id}>
                    <strong>{workflow.name || workflow.id}</strong>
                    <span>
                      {workflow.status} · step {workflow.current_step || 'waiting'}
                    </span>
                  </div>
                ))
              ) : (
                <p className="muted">No active workflows yet.</p>
              )}
            </section>

            <section>
              <h3>Recent memories</h3>
              {client.snapshot?.recent_memories.length ? (
                client.snapshot.recent_memories.map((memory) => (
                  <div className="panel-item" key={memory.id}>
                    <strong>{memory.key || memory.id}</strong>
                    <span>{memory.preview}</span>
                  </div>
                ))
              ) : (
                <p className="muted">No memories yet.</p>
              )}
            </section>
          </div>
        </Card>

        <Card title="Event stream">
          <div className="event-log">
            {client.events.length ? (
              client.events.map((event) => (
                <div className="event-item" key={event.id}>
                  <strong>{event.type}</strong>
                  <span>{event.summary}</span>
                </div>
              ))
            ) : (
              <p className="muted">Waiting for websocket events...</p>
            )}
          </div>
        </Card>
      </aside>
    </div>
  );
}

function PlaceholderRoute({ title, text }: { title: string; text: string }) {
  return (
    <Shell title={title}>
      <Card title={title}>
        <p>{text}</p>
      </Card>
    </Shell>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Shell title="Chat"><ChatRoute /></Shell>} />
      <Route path="/workflows" element={<PlaceholderRoute title="Workflows" text="Workflow timeline and approvals will be layered on top of the live API data next." />} />
      <Route path="/memory" element={<PlaceholderRoute title="Memory" text="Memory search and browsing will use the /api/memories endpoints." />} />
      <Route path="/system" element={<PlaceholderRoute title="System" text="System health and automation controls will be expanded here." />} />
      <Route path="/settings" element={<PlaceholderRoute title="Settings" text="Authentication and provider configuration will live here." />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
