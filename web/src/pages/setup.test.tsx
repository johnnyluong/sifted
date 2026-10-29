import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient, type Goal, type GoalDraft, type SetupApply, type SetupPlan, type SetupView } from "@/api";
import { route } from "@/test/fake-api";
import { status } from "@/test/fixtures";
import { createAppRouter } from "../router";

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock("sonner", () => ({ toast, Toaster: () => null }));

afterEach(() => toast.mockClear());

const SETUP: SetupView = {
  questions: [
    {
      id: "saving",
      kind: "text",
      prompt: "What have you saved lately, and why?",
      hint: null,
      choices: [],
      other: null,
    },
    {
      id: "areas",
      kind: "many",
      prompt: "Which areas do you save about?",
      hint: null,
      choices: [
        { id: "marketing", label: "Marketing and growing a business" },
        { id: "food", label: "Restaurants, bars and food spots" },
      ],
      other: "Something else",
    },
    {
      id: "strictness",
      kind: "one",
      prompt: "How strict should Sift be?",
      hint: null,
      choices: [
        { id: "strict", label: "Strict" },
        { id: "loose", label: "Loose" },
      ],
      other: null,
    },
  ],
  answers: [],
  setup_at: null,
  kept_anyway: [],
  kept_since_setup: 0,
};

function goal(id: number, title: string): Goal {
  return {
    id,
    title,
    description: "",
    category: "personal",
    active: true,
    created_at: "2026-10-20T12:00:00Z",
    updated_at: "2026-10-20T12:00:00Z",
  };
}

const PLAN: SetupPlan = {
  add: [
    { title: "Market my web app", description: "SEO and launch posts.", category: "entrepreneurial", revises: 0 },
    { title: "Date nights in NYC", description: "Places for two.", category: "personal", revises: 0 },
  ],
  deactivate: [2],
  values_text: "Craft over hype.",
};

function renderSetup(goals: Goal[] = [goal(1, "Cook more"), goal(2, "Run a marathon")], view: SetupView = SETUP) {
  window.history.replaceState(null, "", "/setup");
  route("GET /api/status", () => status());
  route("GET /api/setup", () => view);
  route("GET /api/goals", () => goals);
  route("GET /api/values", () => ({ values_text: "" }));
  const queryClient = createQueryClient();
  const router = createAppRouter(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return router;
}

async function answerAndDraft() {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("What have you saved lately, and why?"), "SEO tips");
  await user.click(screen.getByRole("checkbox", { name: "Restaurants, bars and food spots" }));
  await user.click(screen.getByRole("radio", { name: "Strict" }));
  await user.click(screen.getByRole("button", { name: "Draft my goals" }));
  await screen.findByRole("heading", { name: "New goals" });
  return user;
}

describe("setup", () => {
  it("opens on first run, before any goal is active", async () => {
    window.history.replaceState(null, "", "/");
    route("GET /api/status", () => ({ ...status(), active_goals: 0 }));
    route("GET /api/setup", () => SETUP);
    route("GET /api/goals", () => []);
    route("GET /api/values", () => ({ values_text: "" }));
    const queryClient = createQueryClient();
    const router = createAppRouter(queryClient);
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("heading", { level: 1, name: "What are you working toward?" })).toBeTruthy();
    expect(router.state.location.pathname).toBe("/setup");
  });

  it("asks each question in the form its kind needs", async () => {
    renderSetup();
    expect(await screen.findByRole("textbox", { name: "What have you saved lately, and why?" })).toBeTruthy();
    const areas = screen.getByRole("group", { name: "Which areas do you save about?" });
    expect(within(areas).getAllByRole("checkbox")).toHaveLength(2);
    expect(within(areas).getByRole("textbox", { name: "Something else" })).toBeTruthy();
    const strictness = screen.getByRole("group", { name: "How strict should Sift be?" });
    expect(within(strictness).getAllByRole("radio")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Draft my goals" })).toHaveProperty("disabled", true);
  });

  it("sends only the answered questions and saves nothing before the review", async () => {
    let drafted: unknown;
    route("POST /api/setup/draft", async (request) => {
      drafted = await request.json();
      return PLAN;
    });
    renderSetup();
    await answerAndDraft();
    expect(drafted).toEqual({
      answers: [
        { question_id: "saving", text: "SEO tips", picked: [] },
        { question_id: "areas", text: "", picked: ["food"] },
        { question_id: "strictness", text: "", picked: ["strict"] },
      ],
    });
    expect((screen.getAllByLabelText("Goal")[0] as HTMLInputElement).value).toBe("Market my web app");
  });

  it("turns a typed area into its own chip, and Enter adds it instead of drafting", async () => {
    let drafted: unknown;
    let drafts = 0;
    route("POST /api/setup/draft", async (request) => {
      drafts += 1;
      drafted = await request.json();
      return PLAN;
    });
    renderSetup(undefined, {
      ...SETUP,
      answers: [{ question_id: "areas", text: "home server; Home Server", picked: [] }],
    });
    const user = userEvent.setup();
    const areas = await screen.findByRole("group", { name: "Which areas do you save about?" });
    const box = within(areas).getByRole("textbox", { name: "Something else" });
    const chips = () =>
      within(areas)
        .getAllByRole("checkbox")
        .filter((c) => (c as HTMLInputElement).checked)
        .map((c) => c.closest("label")?.textContent);
    expect(chips()).toEqual(["home server"]);

    await user.type(box, "Woodworking{Enter}");
    await user.type(box, "restaurants, bars and food spots{Enter}");
    await user.type(box, "Home Server");
    await user.click(within(areas).getByRole("button", { name: "Add" }));
    expect(drafts).toBe(0);
    expect(box).toHaveProperty("value", "");
    expect(chips()).toEqual(["Restaurants, bars and food spots", "home server", "Woodworking"]);

    await user.click(within(areas).getByRole("checkbox", { name: "home server" }));
    await user.type(box, "3D printing");
    await user.click(screen.getByRole("button", { name: "Draft my goals" }));
    await screen.findByRole("heading", { name: "New goals" });
    expect(drafted).toEqual({
      answers: [{ question_id: "areas", text: "Woodworking; 3D printing", picked: ["food"] }],
    });
  });

  it("drafts from an area still in the box when it is the only answer", async () => {
    let drafted: unknown;
    route("POST /api/setup/draft", async (request) => {
      drafted = await request.json();
      return PLAN;
    });
    renderSetup();
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Something else" }), "home lab; ;");
    await user.click(screen.getByRole("button", { name: "Draft my goals" }));
    await screen.findByRole("heading", { name: "New goals" });
    expect(drafted).toEqual({ answers: [{ question_id: "areas", text: "home lab", picked: [] }] });
  });

  it("adds each area typed with semicolons and keeps text that does not fit", async () => {
    renderSetup();
    const user = userEvent.setup();
    const areas = await screen.findByRole("group", { name: "Which areas do you save about?" });
    const box = within(areas).getByRole("textbox", { name: "Something else" });
    await user.type(box, "Woodworking; 3D printing{Enter}");
    expect(within(areas).getByRole("checkbox", { name: "Woodworking" })).toHaveProperty("checked", true);
    expect(within(areas).getByRole("checkbox", { name: "3D printing" })).toHaveProperty("checked", true);

    const long = "x".repeat(990);
    await user.click(box);
    await user.paste(long);
    await user.keyboard("{Enter}");
    expect(box).toHaveProperty("value", long);
    expect(within(areas).getByRole("alert").textContent).toBe("No room for more. Remove one first.");
    expect(screen.getByRole("button", { name: "Draft my goals" })).toHaveProperty("disabled", true);
  });

  it("presets the goals the draft retires and saves the edited plan with the answers", async () => {
    let applied: SetupApply | undefined;
    route("POST /api/setup/draft", () => PLAN);
    route("POST /api/setup/apply", async (request) => {
      applied = (await request.json()) as SetupApply;
      return [goal(1, "Cook more")];
    });
    renderSetup();
    const user = await answerAndDraft();

    expect(screen.getByRole("checkbox", { name: /Cook more/ })).toHaveProperty("checked", true);
    const marathon = screen.getByRole("checkbox", { name: /Run a marathon/ });
    expect(marathon).toHaveProperty("checked", false);

    const [title] = screen.getAllByLabelText("Goal");
    if (!title) throw new Error("no draft goal");
    await user.clear(title);
    await user.type(title, "Grow my web app");
    await user.click(screen.getByRole("button", { name: "Remove Date nights in NYC" }));
    await user.click(marathon);
    await user.click(screen.getByRole("button", { name: "Save goals" }));

    await waitFor(() => expect(applied).toBeDefined());
    expect(applied).toEqual({
      answers: [
        { question_id: "saving", text: "SEO tips", picked: [] },
        { question_id: "areas", text: "", picked: ["food"] },
        { question_id: "strictness", text: "", picked: ["strict"] },
      ],
      add: [
        { title: "Grow my web app", description: "SEO and launch posts.", category: "entrepreneurial", revises: 0 },
      ],
      deactivate: [],
      values_text: "Craft over hype.",
    });
  });

  it("caps the review at the eight new goals the API accepts and says why", async () => {
    const seven = Array.from({ length: 7 }, (_, i) => ({
      title: `Goal ${i}`,
      description: "",
      category: "other" as const,
      revises: 0,
    }));
    route("POST /api/setup/draft", () => ({ ...PLAN, add: seven }));
    renderSetup();
    const user = await answerAndDraft();
    const add = screen.getByRole("button", { name: "Add a goal" });
    expect(screen.queryByText("Up to 8 new goals at a time.")).toBeNull();
    await user.click(add);
    expect(screen.getAllByLabelText("Goal")).toHaveLength(8);
    expect(add).toHaveProperty("disabled", true);
    expect(screen.getByText("Up to 8 new goals at a time.")).toBeTruthy();
  });

  it("keeps a drafted goal's title on one line that Enter saves", async () => {
    let applied: SetupApply | undefined;
    route("POST /api/setup/draft", () => ({ ...PLAN, add: PLAN.add.slice(0, 1) }));
    route("POST /api/setup/apply", async (request) => {
      applied = (await request.json()) as SetupApply;
      return [goal(1, "Cook more")];
    });
    renderSetup();
    const user = await answerAndDraft();
    const [title] = screen.getAllByLabelText("Goal");
    if (!title) throw new Error("no draft goal");
    await user.clear(title);
    await user.paste("Grow my\nweb app");
    await user.type(title, "{Enter}");
    await waitFor(() => expect(applied).toBeDefined());
    expect(applied?.add.map((g) => g.title)).toEqual(["Grow my web app"]);
  });

  it("shows a goal the draft revises as an update to it, not a second goal", async () => {
    let applied: SetupApply | undefined;
    const add: GoalDraft[] = [
      { title: "Cook at home", description: "Weeknights and meal prep.", category: "personal", revises: 1 },
    ];
    route("POST /api/setup/draft", (): SetupPlan => ({ add, deactivate: [], values_text: "v" }));
    route("POST /api/setup/apply", async (request) => {
      applied = (await request.json()) as SetupApply;
      return [goal(1, "Cook more")];
    });
    renderSetup();
    const user = await answerAndDraft();
    expect(screen.getByText("Updates: Cook more")).toBeTruthy();
    expect(screen.queryByRole("checkbox", { name: /Cook more/ })).toBeNull();
    await user.click(screen.getByRole("checkbox", { name: /Run a marathon/ }));
    await user.click(screen.getByRole("button", { name: "Save goals" }));
    await waitFor(() => expect(applied).toBeDefined());
    expect(applied).toMatchObject({ add, deactivate: [2] });
  });

  it("offers a topic rebuild after a redo that saves, but not on the first run", async () => {
    route("POST /api/setup/draft", () => PLAN);
    route("POST /api/setup/apply", () => [goal(1, "Cook more")]);
    const router = renderSetup();
    const user = await answerAndDraft();
    await user.click(screen.getByRole("button", { name: "Save goals" }));
    await waitFor(() => expect(toast).toHaveBeenCalled());
    const [message, options] = toast.mock.calls[0] ?? [];
    expect([message, options?.action?.label]).toEqual(["Goals saved", "Rebuild topics"]);
    options.action.onClick();
    await waitFor(() => expect(router.state.location.pathname).toBe("/topics/rebuild"));
  });

  it("saves the first goals without offering a rebuild", async () => {
    route("POST /api/setup/draft", () => PLAN);
    route("POST /api/setup/apply", () => [goal(1, "Cook more")]);
    renderSetup([]);
    const user = await answerAndDraft();
    await user.click(screen.getByRole("button", { name: "Save goals" }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Goals saved", undefined));
  });

  it("shows a refused save next to the button", async () => {
    route("POST /api/setup/draft", () => ({ ...PLAN, add: [], deactivate: [1] }));
    route("POST /api/setup/apply", () => {
      throw { status: 409, detail: "Keep at least one goal active." };
    });
    renderSetup([goal(1, "Cook more")]);
    const user = await answerAndDraft();
    expect(screen.getByText("The draft has no new goals. Add one, or keep your current goals.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save goals" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Keep at least one goal active.");
  });

  it("shows why a save that turns off a goal it also adds was refused", async () => {
    const add: GoalDraft[] = [{ title: "Run a marathon", description: "", category: "personal", revises: 0 }];
    route("POST /api/setup/draft", (): SetupPlan => ({ add, deactivate: [2], values_text: "v" }));
    route("POST /api/setup/apply", () => {
      throw { status: 409, detail: "You turned off Run a marathon and also added it. Keep one." };
    });
    renderSetup();
    const user = await answerAndDraft();
    await user.click(screen.getByRole("button", { name: "Save goals" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "You turned off Run a marathon and also added it. Keep one.",
    );
    expect(screen.getByRole("button", { name: "Save goals" })).toBeTruthy();
  });

  it("explains a draft that could not run", async () => {
    route("POST /api/setup/draft", () => {
      throw { status: 503, detail: "Set ANTHROPIC_API_KEY (or LLM_BACKEND=fake) to draft goals, or add them by hand." };
    });
    renderSetup();
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("What have you saved lately, and why?"), "SEO tips");
    await user.click(screen.getByRole("button", { name: "Draft my goals" }));
    expect((await screen.findByRole("alert")).textContent).toContain("add them by hand");
    expect(screen.getByRole("link", { name: "Add goals by hand" }).getAttribute("href")).toBe("/goals");
  });
});
