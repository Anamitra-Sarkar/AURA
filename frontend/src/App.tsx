import { Bot, Cpu, FileText, LogOut, MoonStar, RefreshCw, Send, Shield, Users, Workflow } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { ChatMessage } from './components/ChatMessage';
import { useAuraClient } from './hooks/useAuraClient';

const pages = [
  { to: '/', label: 'Chat', icon: Bot },
  { to: '/workflows', label: 'Workflows', icon: Workflow },
  { to: '/memory', label: 'Memory', icon: FileText },
  { to: '/agents', label: 'Agents', icon: Users },
  { to: '/system', label: 'System', icon: Cpu },
];

function Shell({ title, children, onLogout }: { title: string; children: ReactNode; onLogout?: () => void }) {
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
          <div className="topbar-actions">
            <div className="status-pill">
              <MoonStar size={14} />
              Dark
            </div>
            {onLogout ? (
              <button type="button" className="ghost-button" onClick={onLogout}>
                <LogOut size={14} />
                Logout
              </button>
            ) : null}
          </div>
        </header>
        <section className="content">{children}</section>
      </main>
    </div>
  );
}

function Card({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <div className="card">
      <div className="card-header">
        <h2>{title}</h2>
        {action}
      </div>
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

function AuthScreen({ client }: { client: ReturnType<typeof useAuraClient> }) {
  return (
    <div className="auth-shell">
      <div className="auth-card">
        <div className="brand">AURA</div>
        <p className="muted">Log in to access the live chat, workflow controls, memory browser, agent list, and system dashboard.</p>
        <label className="field">
          <span>Username</span>
          <input value={client.username} onChange={(event) => client.setUsername(event.target.value)} autoComplete="username" />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={client.password} onChange={(event) => client.setPassword(event.target.value)} autoComplete="current-password" />
        </label>
        <div className="row">
          <button type="button" onClick={() => void client.login()} disabled={client.isSubmittingAuth || !client.username || !client.password}>
            Log in
          </button>
          <button type="button" className="secondary-button" onClick={() => void client.register()} disabled={client.isSubmittingAuth || !client.username || !client.password}>
            Register
          </button>
        </div>
        {client.authError ? <p className="error">{client.authError}</p> : null}
      </div>
    </div>
  );
}

function ChatPage({ client }: { client: ReturnType<typeof useAuraClient> }) {
  const workflowCount = client.snapshot?.active_workflows.length ?? client.workflows.length;
  const memoryCount = client.snapshot?.recent_memories.length ?? client.memories.length;
  const eventCount = client.events.length;
  const voiceModeLabel = useMemo(() => (client.snapshot?.lyra_status?.voice_mode ? 'On' : 'Off'), [client.snapshot]);

  return (
    <div className="workspace">
      <div className="workspace-main">
        <Card
          title="Command console"
          action={
            <button type="button" className="ghost-button" onClick={() => void client.refreshAll()}>
              <RefreshCw size={14} />
              Refresh
            </button>
          }
        >
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
        <Card title="Live state" action={<button type="button" className="ghost-button" onClick={() => void client.refreshSystem()}><RefreshCw size={14} />Refresh</button>}>
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
              {client.workflows.slice(0, 3).map((workflow) => (
                <div className="panel-item" key={workflow.id}>
                  <strong>{workflow.name || workflow.id}</strong>
                  <span>{workflow.status} · {workflow.steps.length} step(s)</span>
                </div>
              ))}
              {!client.workflows.length ? <p className="muted">No active workflows yet.</p> : null}
            </section>

            <section>
              <h3>Recent memories</h3>
              {client.memories.slice(0, 3).map((memory) => (
                <div className="panel-item" key={memory.id}>
                  <strong>{memory.key || memory.id}</strong>
                  <span>{memory.preview}</span>
                </div>
              ))}
              {!client.memories.length ? <p className="muted">No memories yet.</p> : null}
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

function WorkflowsPage({ client }: { client: ReturnType<typeof useAuraClient> }) {
  return (
    <Card title="Workflows" action={<button type="button" className="ghost-button" onClick={() => void client.refreshAll()}><RefreshCw size={14} />Refresh</button>}>
      <div className="stack">
        {client.workflows.map((workflow) => (
          <section className="panel-item" key={workflow.id}>
            <div className="panel-item-header">
              <div>
                <strong>{workflow.name || workflow.id}</strong>
                <p className="muted">{workflow.description}</p>
              </div>
              <div className="row">
                <button type="button" className="secondary-button" onClick={() => void client.pauseWorkflow(workflow.id)}>Pause</button>
                <button type="button" className="secondary-button" onClick={() => void client.resumeWorkflow(workflow.id)}>Resume</button>
                <button type="button" className="secondary-button" onClick={() => void client.cancelWorkflow(workflow.id)}>Cancel</button>
              </div>
            </div>

            <div className="step-list">
              {workflow.steps.map((step) => (
                <div className="step-item" key={step.id}>
                  <div>
                    <strong>{step.name}</strong>
                    <p className="muted">{step.description}</p>
                    <p className="muted">Tool: {step.tool_name} · Status: {step.status}</p>
                  </div>
                  {step.status === 'waiting_approval' || step.requires_approval ? (
                    <button type="button" onClick={() => void client.approveWorkflowStep(workflow.id, step.id)}>Approve</button>
                  ) : null}
                </div>
              ))}
            </div>
          </section>
        ))}
        {!client.workflows.length ? <p className="muted">No workflows available.</p> : null}
      </div>
    </Card>
  );
}

function MemoryPage({ client }: { client: ReturnType<typeof useAuraClient> }) {
  const [query, setQuery] = useState('');

  return (
    <Card
      title="Memory"
      action={
        <div className="row">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search memories" />
          <button type="button" className="secondary-button" onClick={() => void client.loadMemories(query)}>Search</button>
        </div>
      }
    >
      <div className="stack">
        {client.memories.map((memory) => (
          <div className="panel-item" key={memory.id}>
            <div className="panel-item-header">
              <div>
                <strong>{memory.key}</strong>
                <p className="muted">{memory.category}</p>
              </div>
              <button type="button" className="secondary-button" onClick={() => void client.deleteMemory(memory.id)}>
                Delete
              </button>
            </div>
            <p>{memory.preview}</p>
          </div>
        ))}
        {!client.memories.length ? <p className="muted">No memory results.</p> : null}
      </div>
    </Card>
  );
}

function AgentsPage({ client }: { client: ReturnType<typeof useAuraClient> }) {
  return (
    <Card title="Agents" action={<button type="button" className="ghost-button" onClick={() => void client.refreshAgents()}><RefreshCw size={14} />Refresh</button>}>
      <div className="stack">
        {client.agents.map((agent) => (
          <div className="panel-item" key={agent.id}>
            <strong>{agent.name}</strong>
            <p className="muted">{agent.description}</p>
            <div className="chip-row">
              {(agent.capabilities ?? []).map((capability) => (
                <span className="chip" key={capability}>{capability}</span>
              ))}
            </div>
          </div>
        ))}
        {!client.agents.length ? <p className="muted">No agents available.</p> : null}
      </div>
    </Card>
  );
}

function SystemPage({ client }: { client: ReturnType<typeof useAuraClient> }) {
  return (
    <div className="stack">
      <Card
        title="System"
        action={
          <div className="row">
            <button type="button" className="ghost-button" onClick={() => void client.refreshSystem()}>
              <RefreshCw size={14} />
              Refresh
            </button>
            <button type="button" className="ghost-button" onClick={async () => { await client.takeScreenshot(); }}>
              <Shield size={14} />
              Screenshot
            </button>
          </div>
        }
      >
        <div className="status-row">
          <Metric label="CPU" value={`${client.snapshot?.system_health.cpu_pct ?? '—'}%`} />
          <Metric label="RAM" value={`${client.snapshot?.system_health.ram_pct ?? '—'}%`} />
          <Metric label="Disk" value={`${client.snapshot?.system_health.disk_pct ?? '—'}%`} />
          <Metric label="Uptime" value={`${client.snapshot?.system_health.uptime ?? '—'}s`} />
        </div>
      </Card>

      <Card title="Phantom tasks">
        <div className="stack">
          {client.phantomTasks.map((task) => (
            <div className="panel-item" key={task.id}>
              <div className="panel-item-header">
                <div>
                  <strong>{task.name}</strong>
                  <p className="muted">{task.description}</p>
                </div>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => void client.togglePhantomTask(task.id, !task.enabled)}
                >
                  {task.enabled ? 'Disable' : 'Enable'}
                </button>
              </div>
              <p className="muted">Schedule: {task.schedule} · Next run: {task.next_run ?? '—'}</p>
            </div>
          ))}
          {!client.phantomTasks.length ? <p className="muted">No phantom tasks available.</p> : null}
        </div>
      </Card>
    </div>
  );
}

export default function App() {
  const client = useAuraClient();

  if (client.needsAuth) {
    return <AuthScreen client={client} />;
  }

  return (
    <Routes>
      <Route path="/" element={<Shell title="Chat" onLogout={client.logout}><ChatPage client={client} /></Shell>} />
      <Route path="/workflows" element={<Shell title="Workflows" onLogout={client.logout}><WorkflowsPage client={client} /></Shell>} />
      <Route path="/memory" element={<Shell title="Memory" onLogout={client.logout}><MemoryPage client={client} /></Shell>} />
      <Route path="/agents" element={<Shell title="Agents" onLogout={client.logout}><AgentsPage client={client} /></Shell>} />
      <Route path="/system" element={<Shell title="System" onLogout={client.logout}><SystemPage client={client} /></Shell>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
