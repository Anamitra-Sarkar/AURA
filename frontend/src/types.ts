export type AuraRole = 'user' | 'assistant';

export interface AuraToolSummary {
  tool: string;
  summary: string;
}

export interface AuraMessage {
  id: string;
  role: AuraRole;
  content: string;
  createdAt: string;
  isStreaming?: boolean;
  isThinking?: boolean;
  tools?: AuraToolSummary[];
}

export interface AuraAuthResponse {
  user_id: string;
  token?: string;
  jwt_token?: string;
}

export interface AuraAgentCard {
  id: string;
  name: string;
  description: string;
  capabilities?: string[];
  status?: 'ready' | 'idle' | 'error' | string;
}

export interface AuraToolFeedEntry {
  id: string;
  icon: string;
  agent: string;
  action: string;
  timestamp: string;
}

export interface AuraHealthState {
  router: { ok: boolean; model?: string };
  memory: { ok: boolean };
  local_pc: { ok: boolean };
  status: string;
}

export interface AuraStateSnapshot {
  active_workflows: Array<{ id: string }>;
  recent_memories: Array<{ id: string }>;
  phantom_tasks: Array<{ id: string }>;
  system_health?: {
    cpu_pct: number;
    ram_pct: number;
    disk_pct: number;
    uptime: number;
  };
}

export interface AuraMessageStreamEvent {
  token?: string;
  done?: boolean;
  tools_called?: string[];
  steps?: Array<{ tool?: string; result?: unknown; error?: string }>;
  reasoning_used?: boolean;
  used_ensemble?: boolean;
}
