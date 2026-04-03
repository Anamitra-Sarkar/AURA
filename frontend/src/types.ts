export interface AuraMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  createdAt: string;
  details?: Record<string, unknown>;
}

export interface AuraMessageResponse {
  response: string;
  used_ensemble?: boolean;
  reasoning_used?: boolean;
  tools_called?: string[];
}

export interface AuraWorkflow {
  id: string;
  name: string;
  status: string;
  current_step: string;
  total_steps: number;
  started_at: string | null;
}

export interface AuraMemorySummary {
  id: string;
  key: string;
  category: string;
  preview: string;
  timestamp: string;
}

export interface AuraSystemHealth {
  cpu_pct: number;
  ram_pct: number;
  disk_pct: number;
  uptime: number;
}

export interface AuraLyraStatus {
  enabled: boolean;
  listening: boolean;
  voice_mode: boolean;
  wake_engine: string;
}

export interface AuraSnapshot {
  active_workflows: AuraWorkflow[];
  phantom_tasks: unknown[];
  recent_memories: AuraMemorySummary[];
  lyra_status: AuraLyraStatus;
  system_health: AuraSystemHealth;
}

export interface AuraEventRecord {
  id: string;
  type: string;
  summary: string;
  timestamp: string;
}

export interface AuraWebSocketMessage {
  type: string;
  data: unknown;
  timestamp: string;
}
