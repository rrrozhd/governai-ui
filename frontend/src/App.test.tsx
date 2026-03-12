import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

const ok = (payload: unknown) =>
  Promise.resolve({
    ok: true,
    json: async () => payload,
    text: async () => JSON.stringify(payload)
  });

describe("App", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.includes("/api/catalog")) {
        return ok({ items: [] });
      }
      if (url.includes("/api/sessions") && !url.includes("answers")) {
        return ok({
          session_id: "s-1",
          state: "questioning",
          confidence: 0.2,
          asked_questions: 0,
          draft_id: null,
          slot_status: {
            objective: true,
            success_criteria: false,
            input_shape: false,
            available_components: false,
            approval_expectations: false,
            branching_logic: false
          },
          next_question: {
            id: "success_criteria",
            slot: "success_criteria",
            text: "How will we measure success?"
          }
        });
      }
      return ok({});
    }));
  });

  it("renders heading", async () => {
    render(<App />);
    expect(screen.getByText("Plan-Mode Workflow Studio")).toBeInTheDocument();
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  });

  it("starts a session and shows first question", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByText("Start Question Loop")[0]);

    await waitFor(() => {
      expect(screen.getByText("How will we measure success?")).toBeInTheDocument();
    });
  });
});
