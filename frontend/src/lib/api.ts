export type Question = {
  id: string;
  slot: string;
  text: string;
};

export type SessionResponse = {
  session_id: string;
  state: "questioning" | "drafting" | "ready";
  confidence: number;
  slot_status: Record<string, boolean>;
  next_question: Question | null;
  asked_questions: number;
  draft_id: string | null;
};

export type LiteLLMConfig = {
  provider: "litellm";
  model: string;
  temperature?: number;
  max_tokens?: number;
  api_base?: string;
  api_key_env?: string;
  extra_headers?: Record<string, string>;
  extra_body?: Record<string, unknown>;
};

export type GenerateResponse = {
  draft_id: string;
  version_id: string;
  dsl: string;
  config_snapshot: Record<string, unknown> | null;
  validation: {
    valid: boolean;
    errors: Array<Record<string, unknown>>;
    graph?: Record<string, unknown>;
  };
};

export type ValidationResponse = {
  valid: boolean;
  errors: Array<Record<string, unknown>>;
  config_snapshot: Record<string, unknown> | null;
  graph: Record<string, unknown> | null;
};

export type RunState = {
  run_id: string;
  workflow_name: string;
  status: string;
  epoch: number;
  current_step: string | null;
  completed_steps: string[];
  artifacts: Record<string, unknown>;
  channels: Record<string, unknown>;
  pending_approval: Record<string, unknown> | null;
  pending_interrupt: {
    interrupt_id: string;
    message?: string;
    context?: Record<string, unknown>;
    epoch?: number;
    expires_at?: number;
  } | null;
  checkpoint_id: string | null;
  thread_id: string | null;
  error: string | null;
  updated_at: string;
};

export type RunResponse = {
  draft_id: string;
  version_id: string;
  state: RunState;
};

export type AuditEvent = {
  event_id: string;
  timestamp: string;
  event_type: string;
  step_name: string | null;
  payload: Record<string, unknown>;
};

export type AuditEventsResponse = {
  events: AuditEvent[];
  next_after: number;
};

export type CatalogResponse = {
  items: Array<{
    name: string;
    kind: string;
    description: string;
  }>;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }

  return (await response.json()) as T;
}

export async function getCatalog(): Promise<CatalogResponse> {
  return request<CatalogResponse>("/api/catalog");
}

export async function createSession(
  issue: string,
  llmConfig?: LiteLLMConfig
): Promise<SessionResponse> {
  return request<SessionResponse>("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ issue, llm_config: llmConfig })
  });
}

export async function answerSession(
  sessionId: string,
  questionId: string,
  answer: string
): Promise<SessionResponse> {
  return request<SessionResponse>(`/api/sessions/${sessionId}/answers`, {
    method: "POST",
    body: JSON.stringify({ question_id: questionId, answer })
  });
}

export async function generateWorkflow(sessionId: string, force = false): Promise<GenerateResponse> {
  const suffix = force ? "?force=true" : "";
  return request<GenerateResponse>(`/api/sessions/${sessionId}/generate${suffix}`, {
    method: "POST"
  });
}

export async function validateDraft(draftId: string, dsl: string): Promise<ValidationResponse> {
  return request<ValidationResponse>(`/api/drafts/${draftId}/validate`, {
    method: "POST",
    body: JSON.stringify({ dsl })
  });
}

export async function runDraft(draftId: string, inputPayload: Record<string, unknown>): Promise<RunResponse> {
  return request<RunResponse>(`/api/drafts/${draftId}/run`, {
    method: "POST",
    body: JSON.stringify({ input_payload: inputPayload })
  });
}

export async function resumeApproval(runId: string, decision: "approve" | "reject") {
  return request<RunState>(`/api/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify({ type: "approval", decision, decided_by: "ui-user" })
  });
}

export async function resumeInterrupt(
  runId: string,
  interruptId: string,
  epoch: number,
  responsePayload: Record<string, unknown>
) {
  return request<RunState>(`/api/runs/${runId}/resume`, {
    method: "POST",
    body: JSON.stringify({
      type: "interrupt",
      interrupt_id: interruptId,
      epoch,
      response: responsePayload
    })
  });
}

export async function getRunState(runId: string): Promise<RunState> {
  return request<RunState>(`/api/runs/${runId}`);
}

export async function getRunEvents(runId: string, after: number): Promise<AuditEventsResponse> {
  return request<AuditEventsResponse>(`/api/runs/${runId}/events?after=${after}`);
}
