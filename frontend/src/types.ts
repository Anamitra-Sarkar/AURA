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

export interface AuraWorkflowStep {
  id: string;
  name: string;
  description: string;
  status: string;
  tool_name: string;
  requires_approval?: boolean;
  retry_count?: number;
  max_retries?: number;
  error?: string | null;
}

export interface AuraWorkflowPlan {
  id: string;
  name: string;
  description: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  steps: AuraWorkflowStep[];
  context?: Record<string, unknown>;
}

export interface AuraMemoryRecord {
  id: string;
  key: string;
  category: string;
  preview: string;
  timestamp: string;
  similarity_score?: number;
}

export interface AuraAgentCard {
  id: string;
  name: string;
  description: string;
  capabilities?: string[];
  status?: string;
}

export interface AuraPhantomTask {
  id: string;
  name: string;
  description: string;
  schedule: string;
  enabled: boolean;
  next_run?: string | null;
  last_run?: string | null;
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
  active_workflows: AuraWorkflowPlan[];
  phantom_tasks: AuraPhantomTask[];
  recent_memories: AuraMemoryRecord[];
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

export interface AuraAuthResponse {
  user_id: string;
  token?: string;
  jwt_token?: string;
}
