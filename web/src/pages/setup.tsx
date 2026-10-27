import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link, useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { type FormEvent, type JSX, useId, useState } from "react";
import { toast } from "sonner";
import {
  api,
  GOAL_CATEGORIES,
  type Goal,
  type GoalDraft,
  type SetupAnswer,
  type SetupPlan,
  type SetupQuestion,
  useApplySetup,
  useDraftSetup,
} from "@/api";
import { Page, PageHeader } from "@/components/page";
import { Button } from "@/components/ui/button";
import { Input, Label, LineInput, Select, Textarea } from "@/components/ui/field";
import { ANSWER_MAX, GOAL_DESCRIPTION_MAX, GOAL_TITLE_MAX, SETUP_ADD_MAX, VALUES_MAX } from "@/lib/limits";
import { type Answers, filledAnswers, pick, startingAnswers } from "@/lib/setup";
import { CATEGORIES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/setup",
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.ensureQueryData(api.setup),
      context.queryClient.ensureQueryData(api.goals),
      context.queryClient.ensureQueryData(api.values),
    ]),
  component: SetupPage,
});

function SetupPage(): JSX.Element {
  const { data: setup } = useSuspenseQuery(api.setup);
  const { data: goals } = useSuspenseQuery(api.goals);
  const { data: values } = useSuspenseQuery(api.values);
  const [answers, setAnswers] = useState(() => startingAnswers(setup.questions, setup.answers));
  const [plan, setPlan] = useState<SetupPlan | null>(null);
  const firstRun = !goals.some((g) => g.active);
  return (
    <Page>
      <PageHeader
        title={firstRun ? "What are you working toward?" : "Redo setup"}
        subtitle={
          firstRun
            ? "Answer a few questions about what you save. Sift drafts your goals and values from them, and saves nothing until you confirm."
            : "Answer again to draft new goals. Your current goals stay active unless you turn them off."
        }
      />
      {plan ? (
        <Review
          plan={plan}
          goals={goals}
          currentValues={values.values_text}
          answers={filledAnswers(setup.questions, answers)}
          onBack={() => setPlan(null)}
        />
      ) : (
        <Questions questions={setup.questions} answers={answers} onChange={setAnswers} onDrafted={setPlan} />
      )}
    </Page>
  );
}

function Questions({
  questions,
  answers,
  onChange,
  onDrafted,
}: {
  questions: SetupQuestion[];
  answers: Answers;
  onChange: (answers: Answers) => void;
  onDrafted: (plan: SetupPlan) => void;
}): JSX.Element {
  const draft = useDraftSetup();
  const filled = filledAnswers(questions, answers);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    draft.mutate(filled, { onSuccess: onDrafted });
  };
  return (
    <form onSubmit={submit} className="mt-8 space-y-3">
      {questions.map((q) => {
        const answer = answers[q.id] ?? { question_id: q.id, text: "", picked: [] };
        return (
          <QuestionField
            key={q.id}
            question={q}
            answer={answer}
            onChange={(a) => onChange({ ...answers, [q.id]: a })}
          />
        );
      })}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 pt-3">
        <Button type="submit" variant="primary" disabled={draft.isPending || filled.length === 0}>
          {draft.isPending ? "Drafting..." : "Draft my goals"}
        </Button>
        <Link to="/goals" className="text-[13px] text-silt underline underline-offset-2 hover:text-graphite">
          Add goals by hand
        </Link>
      </div>
      {draft.isPending && (
        <p className="text-[13px] text-silt">Sift is reading your answers. This takes a few seconds.</p>
      )}
      {draft.error && (
        <p role="alert" className="text-[13px] text-alarm">
          {draft.error.message}
        </p>
      )}
    </form>
  );
}

const choiceClass =
  "inline-flex min-h-9 cursor-pointer items-center rounded-full border border-mesh px-3.5 text-[13px] text-ink-soft transition-colors hover:bg-pan-hover has-checked:border-graphite has-checked:bg-sheet has-checked:font-[560] has-checked:text-graphite has-focus-visible:outline-2 has-focus-visible:outline-graphite has-focus-visible:outline-offset-2 max-[700px]:min-h-11 max-[700px]:text-[15px]";

function QuestionField({
  question: q,
  answer,
  onChange,
}: {
  question: SetupQuestion;
  answer: SetupAnswer;
  onChange: (answer: SetupAnswer) => void;
}): JSX.Element {
  const id = useId();
  const hint = q.hint ? <p className="mb-2.5 text-[13px] text-silt">{q.hint}</p> : null;
  switch (q.kind) {
    case "text":
      return (
        <div className="surface p-4">
          <Label htmlFor={id} className="text-[15px] text-graphite">
            {q.prompt}
          </Label>
          {hint}
          <Textarea
            id={id}
            maxLength={ANSWER_MAX}
            value={answer.text}
            onChange={(e) => onChange({ ...answer, text: e.target.value })}
            className="min-h-20"
          />
        </div>
      );
    case "one":
    case "many":
      return (
        <div className="surface p-4">
          <fieldset>
            <legend className="mb-1.5 font-[520] text-[15px] text-graphite">{q.prompt}</legend>
            {hint}
            <div className="flex flex-wrap gap-2">
              {q.choices.map((c) => (
                <label key={c.id} className={choiceClass}>
                  <input
                    type={q.kind === "one" ? "radio" : "checkbox"}
                    name={id}
                    checked={answer.picked.includes(c.id)}
                    onChange={() => onChange(pick(q, answer, c.id))}
                    className="sr-only"
                  />
                  {c.label}
                </label>
              ))}
            </div>
            {q.other && (
              <Input
                aria-label={q.other}
                placeholder={q.other}
                maxLength={ANSWER_MAX}
                value={answer.text}
                onChange={(e) => onChange({ ...answer, text: e.target.value })}
                className="mt-3 max-w-sm"
              />
            )}
          </fieldset>
        </div>
      );
  }
}

type DraftRow = GoalDraft & { key: number };

function Review({
  plan,
  goals,
  currentValues,
  answers,
  onBack,
}: {
  plan: SetupPlan;
  goals: Goal[];
  currentValues: string;
  answers: SetupAnswer[];
  onBack: () => void;
}): JSX.Element {
  const apply = useApplySetup();
  const navigate = useNavigate();
  const [rows, setRows] = useState<DraftRow[]>(() => plan.add.map((g, key) => ({ ...g, key })));
  const [deactivate, setDeactivate] = useState(() => new Set(plan.deactivate));
  const [values, setValues] = useState(plan.values_text);
  const valuesId = useId();
  const active = goals.filter((g) => g.active);
  const revised = new Set(rows.map((r) => r.revises));
  const kept = active.filter((g) => !revised.has(g.id));
  const full = rows.length >= SETUP_ADD_MAX;

  const edit = (key: number, change: Partial<GoalDraft>) =>
    setRows(rows.map((r) => (r.key === key ? { ...r, ...change } : r)));
  const addRow = () =>
    setRows([
      ...rows,
      {
        key: Math.max(-1, ...rows.map((r) => r.key)) + 1,
        title: "",
        description: "",
        category: "personal",
        revises: 0,
      },
    ]);
  const toggle = (id: number) => {
    const next = new Set(deactivate);
    if (!next.delete(id)) next.add(id);
    setDeactivate(next);
  };
  const save = (event: FormEvent) => {
    event.preventDefault();
    const add = rows.map(({ key: _, ...goal }) => goal);
    apply.mutate(
      { answers, add, deactivate: kept.filter((g) => deactivate.has(g.id)).map((g) => g.id), values_text: values },
      {
        onSuccess: () => {
          toast("Goals saved");
          void navigate({ to: "/goals" });
        },
      },
    );
  };

  return (
    <form onSubmit={save} className="mt-8">
      <section>
        <h2 className="font-semibold">New goals</h2>
        <p className="mt-0.5 mb-3 text-[13px] text-silt">
          Edit or remove any of them. Sift scores every post you save against the goals you keep.
        </p>
        {rows.length === 0 && (
          <p className="mb-3 surface px-4 py-3 text-[13px] text-silt">
            The draft has no new goals. Add one, or keep your current goals.
          </p>
        )}
        <ul className="space-y-3">
          {rows.map((row) => (
            <DraftGoal
              key={row.key}
              row={row}
              updates={active.find((g) => g.id === row.revises)}
              onChange={(change) => edit(row.key, change)}
              onRemove={() => setRows(rows.filter((r) => r.key !== row.key))}
            />
          ))}
        </ul>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Button type="button" size="sm" disabled={full} onClick={addRow}>
            <Plus aria-hidden />
            Add a goal
          </Button>
          {full && <p className="text-[13px] text-silt">Up to {SETUP_ADD_MAX} new goals at a time.</p>}
        </div>
      </section>

      {kept.length > 0 && (
        <section className="mt-10">
          <h2 className="font-semibold">Your current goals</h2>
          <p className="mt-0.5 mb-3 text-[13px] text-silt">
            Uncheck a goal to turn it off. It stays on your Goals page, and you can turn it back on.
          </p>
          <ul className="surface">
            {kept.map((g) => (
              <li key={g.id} className="border-mesh border-t first:border-t-0">
                <label className="flex cursor-pointer items-start gap-3 px-4 py-3.5">
                  <input
                    type="checkbox"
                    checked={!deactivate.has(g.id)}
                    onChange={() => toggle(g.id)}
                    className="mt-1 size-4 shrink-0 accent-graphite"
                  />
                  <span className="min-w-0">
                    <span className="block font-semibold">{g.title}</span>
                    {g.description && <span className="mt-0.5 block text-[13px] text-silt">{g.description}</span>}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-10">
        <h2 className="mb-3 font-semibold">Values</h2>
        <div className="surface p-4">
          <Label htmlFor={valuesId}>What you care about, and what counts as noise</Label>
          <Textarea id={valuesId} maxLength={VALUES_MAX} value={values} onChange={(e) => setValues(e.target.value)} />
          {currentValues && values !== currentValues && (
            <Button type="button" size="sm" variant="ghost" className="mt-2" onClick={() => setValues(currentValues)}>
              Keep my current values
            </Button>
          )}
        </div>
      </section>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <Button type="submit" variant="primary" disabled={apply.isPending}>
          {apply.isPending ? "Saving..." : "Save goals"}
        </Button>
        <Button type="button" variant="ghost" onClick={onBack}>
          Back to questions
        </Button>
        {apply.error && (
          <p role="alert" className="text-[13px] text-alarm">
            {apply.error.message}
          </p>
        )}
      </div>
    </form>
  );
}

function DraftGoal({
  row,
  updates,
  onChange,
  onRemove,
}: {
  row: DraftRow;
  updates: Goal | undefined;
  onChange: (change: Partial<GoalDraft>) => void;
  onRemove: () => void;
}): JSX.Element {
  const id = useId();
  return (
    <li className="space-y-3.5 surface p-4">
      <div>
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`${id}-title`}>Goal</Label>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="-mt-1.5"
            aria-label={`Remove ${row.title || "this goal"}`}
            onClick={onRemove}
          >
            Remove
          </Button>
        </div>
        <LineInput
          id={`${id}-title`}
          required
          maxLength={GOAL_TITLE_MAX}
          value={row.title}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="Market my web app"
        />
        {updates && <p className="mt-1.5 text-caption text-silt">Updates: {updates.title}</p>}
      </div>
      <div>
        <Label htmlFor={`${id}-why`}>Why it matters</Label>
        <Textarea
          id={`${id}-why`}
          maxLength={GOAL_DESCRIPTION_MAX}
          value={row.description}
          onChange={(e) => onChange({ description: e.target.value })}
          className="min-h-16"
        />
      </div>
      <div>
        <Label htmlFor={`${id}-category`}>Category</Label>
        <Select
          id={`${id}-category`}
          value={row.category}
          onChange={(e) => onChange({ category: GOAL_CATEGORIES.find((c) => c === e.target.value) ?? "other" })}
        >
          {GOAL_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORIES[c]}
            </option>
          ))}
        </Select>
      </div>
    </li>
  );
}
