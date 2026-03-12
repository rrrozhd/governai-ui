import { FormEvent, useEffect, useRef, useState } from "react";
import {
  AuditEvent,
  CatalogResponse,
  GenerateResponse,
  LiteLLMConfig,
  RunState,
  SessionResponse,
  ValidationResponse,
  answerSession,
  createSession,
  generateWorkflow,
  getCatalog,
  getRunEvents,
  resumeApproval,
  resumeInterrupt,
  runDraft,
  validateDraft
} from "./lib/api";

const pretty = (value: unknown) => JSON.stringify(value, null, 2);

export default function App() {
  const [issue, setIssue] = useState("Build a governed workflow for incident triage and outbound reply");
  const [model, setModel] = useState("openai/gpt-4o-mini");
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [answer, setAnswer] = useState("");

  const [draft, setDraft] = useState<GenerateResponse | null>(null);
  const [dsl, setDsl] = useState("");
  const [validation, setValidation] = useState<ValidationResponse | null>(null);

  const [runState, setRunState] = useState<RunState | null>(null);
  const [inputPayload, setInputPayload] = useState(
    pretty({ issue: "complex security incident affecting billing" })
  );
  const [interruptResponse, setInterruptResponse] = useState(pretty({ approved: true }));

  const [catalog, setCatalog] = useState<CatalogResponse | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const eventCursorRef = useRef(0);

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getCatalog()
      .then(setCatalog)
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    if (!runState?.run_id) {
      return;
    }

    const runId = runState.run_id;
    const timer = window.setInterval(async () => {
      try {
        const page = await getRunEvents(runId, eventCursorRef.current);
        if (page.events.length > 0) {
          setEvents((prev) => [...prev, ...page.events]);
        }
        eventCursorRef.current = page.next_after;
      } catch {
        // Ignore transient polling errors.
      }
    }, 2000);

    return () => window.clearInterval(timer);
  }, [runState?.run_id]);

  async function withBusy<T>(fn: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    } finally {
      setBusy(false);
    }
  }

  const onStartSession = async (event: FormEvent) => {
    event.preventDefault();
    const llmConfig: LiteLLMConfig = {
      provider: "litellm",
      model,
      temperature: 0.2,
      max_tokens: 800
    };
    const next = await withBusy(() => createSession(issue, llmConfig));
    setSession(next);
    setAnswer("");
    setDraft(null);
    setDsl("");
    setValidation(null);
    setRunState(null);
    setEvents([]);
    eventCursorRef.current = 0;
  };

  const onSubmitAnswer = async (event: FormEvent) => {
    event.preventDefault();
    if (!session?.next_question) {
      return;
    }

    const updated = await withBusy(() =>
      answerSession(session.session_id, session.next_question!.id, answer)
    );
    setSession(updated);
    setAnswer("");
  };

  const onGenerate = async (force = false) => {
    if (!session) {
      return;
    }
    const generated = await withBusy(() => generateWorkflow(session.session_id, force));
    setDraft(generated);
    setDsl(generated.dsl);
    setValidation({
      valid: generated.validation.valid,
      errors: generated.validation.errors,
      config_snapshot: generated.config_snapshot,
      graph: generated.validation.graph ?? null
    });
  };

  const onValidate = async () => {
    if (!draft) {
      return;
    }

    const result = await withBusy(() => validateDraft(draft.draft_id, dsl));
    setValidation(result);
  };

  const onRun = async () => {
    if (!draft) {
      return;
    }

    const payload = JSON.parse(inputPayload) as Record<string, unknown>;
    const run = await withBusy(() => runDraft(draft.draft_id, payload));
    setRunState(run.state);
    setEvents([]);
    eventCursorRef.current = 0;
  };

  const onApprove = async (decision: "approve" | "reject") => {
    if (!runState) {
      return;
    }

    const resumed = await withBusy(() => resumeApproval(runState.run_id, decision));
    setRunState(resumed);
  };

  const onResolveInterrupt = async () => {
    if (!runState?.pending_interrupt) {
      return;
    }

    const payload = JSON.parse(interruptResponse) as Record<string, unknown>;
    const resumed = await withBusy(() =>
      resumeInterrupt(
        runState.run_id,
        runState.pending_interrupt!.interrupt_id,
        runState.pending_interrupt!.epoch ?? runState.epoch,
        payload
      )
    );
    setRunState(resumed);
  };

  return (
    <div className="page-shell">
      <div className="orb orb-a" />
      <div className="orb orb-b" />
      <header className="topbar">
        <div>
          <p className="eyebrow">Governed Builder</p>
          <h1>Plan-Mode Workflow Studio</h1>
        </div>
        <p className="subtitle">LiteLLM-default planner over governai deterministic runtime</p>
      </header>

      {error ? <div className="error-box">{error}</div> : null}

      <main className="layout-grid">
        <section className="panel intake">
          <h2>Issue Intake</h2>
          <form onSubmit={onStartSession} className="stack">
            <input
              className="model-input"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="LiteLLM model (e.g. openai/gpt-4o-mini or ollama/llama3.1)"
            />
            <textarea
              value={issue}
              onChange={(e) => setIssue(e.target.value)}
              rows={5}
              placeholder="Describe the issue the workflow should solve"
            />
            <button type="submit" disabled={busy}>Start Question Loop</button>
          </form>

          <h3>Allowlist Catalog</h3>
          <div className="catalog-list">
            {(catalog?.items ?? []).map((item) => (
              <div key={`${item.kind}-${item.name}`} className="catalog-item">
                <span>{item.kind}</span>
                <strong>{item.name}</strong>
                <p>{item.description}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="panel planner">
          <h2>Question Loop</h2>
          {session ? (
            <>
              <div className="metrics">
                <div>
                  <span>State</span>
                  <strong>{session.state}</strong>
                </div>
                <div>
                  <span>Confidence</span>
                  <strong>{session.confidence}</strong>
                </div>
                <div>
                  <span>Questions</span>
                  <strong>{session.asked_questions}</strong>
                </div>
              </div>

              <div className="slot-grid">
                {Object.entries(session.slot_status).map(([slot, filled]) => (
                  <div key={slot} className={`slot ${filled ? "slot-filled" : "slot-empty"}`}>
                    {slot}
                  </div>
                ))}
              </div>

              {session.next_question ? (
                <form onSubmit={onSubmitAnswer} className="stack">
                  <label className="question">{session.next_question.text}</label>
                  <textarea
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                    rows={4}
                    placeholder="Answer this implementation question"
                  />
                  <button type="submit" disabled={busy}>Submit Answer</button>
                </form>
              ) : (
                <p className="muted">Session is ready for workflow generation.</p>
              )}

              <div className="button-row">
                <button onClick={() => onGenerate(false)} disabled={busy || session.state !== "ready"}>
                  Generate Workflow
                </button>
                <button onClick={() => onGenerate(true)} disabled={busy} className="ghost">
                  Force Generate
                </button>
              </div>
            </>
          ) : (
            <p className="muted">Start a session to begin plan-mode questioning.</p>
          )}
        </section>

        <section className="panel dsl">
          <h2>DSL Studio</h2>
          <textarea
            value={dsl}
            onChange={(e) => setDsl(e.target.value)}
            rows={16}
            placeholder="Generated DSL will appear here"
            className="mono"
          />
          <div className="button-row">
            <button onClick={onValidate} disabled={busy || !draft}>Validate DSL</button>
          </div>

          <div className="validation-box">
            <strong>{validation?.valid ? "Valid" : "Not valid"}</strong>
            <pre className="mono">{pretty(validation?.errors ?? [])}</pre>
          </div>

          <h3>Run Payload</h3>
          <textarea
            className="mono"
            value={inputPayload}
            onChange={(e) => setInputPayload(e.target.value)}
            rows={7}
          />
          <button onClick={onRun} disabled={busy || !draft || validation?.valid === false}>
            Run Draft
          </button>
        </section>

        <section className="panel run">
          <h2>Run Lifecycle</h2>
          <pre className="mono run-state">{pretty(runState)}</pre>

          {runState?.pending_approval ? (
            <div className="button-row">
              <button onClick={() => onApprove("approve")} disabled={busy}>Approve</button>
              <button onClick={() => onApprove("reject")} disabled={busy} className="danger">
                Reject
              </button>
            </div>
          ) : null}

          {runState?.pending_interrupt ? (
            <div className="stack">
              <h3>Interrupt Response</h3>
              <textarea
                className="mono"
                rows={5}
                value={interruptResponse}
                onChange={(e) => setInterruptResponse(e.target.value)}
              />
              <button onClick={onResolveInterrupt} disabled={busy}>Resolve Interrupt</button>
            </div>
          ) : null}

          <h3>Audit Timeline</h3>
          <div className="events">
            {events.map((event) => (
              <article key={event.event_id} className="event-row">
                <span>{event.event_type}</span>
                <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
              </article>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
