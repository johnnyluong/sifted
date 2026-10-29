import { useSuspenseQuery } from "@tanstack/react-query";
import { createRoute, Link } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { type FormEvent, type JSX, useId, useState } from "react";
import { toast } from "sonner";
import {
  api,
  GOAL_CATEGORIES,
  type Goal,
  type GoalCategory,
  type SetupView,
  useCreateGoal,
  useSaveValues,
  useUpdateGoal,
} from "@/api";
import { Page, PageHeader, PageSection } from "@/components/page";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label, Select, Textarea } from "@/components/ui/field";
import { GOAL_DESCRIPTION_MAX, GOAL_TITLE_MAX, VALUES_MAX } from "@/lib/limits";
import { cn } from "@/lib/utils";
import { CATEGORIES } from "@/lib/vocabulary";
import { rootRoute } from "./root";

export const goalsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/goals",
  loader: ({ context }) =>
    Promise.all([
      context.queryClient.ensureQueryData(api.goals),
      context.queryClient.ensureQueryData(api.values),
      context.queryClient.ensureQueryData(api.setup),
    ]),
  component: GoalsPage,
});

function GoalsPage(): JSX.Element {
  const { data: goals } = useSuspenseQuery(api.goals);
  const { data: values } = useSuspenseQuery(api.values);
  const { data: setup } = useSuspenseQuery(api.setup);
  const none = goals.length === 0;
  const [adding, setAdding] = useState(false);
  return (
    <Page>
      <PageHeader title="Goals" subtitle="Every saved post is scored against your active goals and values." />

      <PageSection
        title="Your goals"
        className="mt-8"
        aside={
          !none && (
            <div className="flex gap-2">
              <Button size="sm" asChild>
                <Link to="/setup">Redo setup</Link>
              </Button>
              {!adding && (
                <Button size="sm" onClick={() => setAdding(true)}>
                  <Plus aria-hidden />
                  Add goal
                </Button>
              )}
            </div>
          )
        }
      >
        {adding && (
          <div className="mb-3 surface p-4">
            <GoalForm onDone={() => setAdding(false)} onCancel={() => setAdding(false)} />
          </div>
        )}
        {none ? (
          !adding && (
            <div className="surface px-4 py-5">
              <p className="font-semibold">No goals yet</p>
              <p className="mt-0.5 text-silt">
                Answer a few questions and Sift drafts your goals and values. You review them before anything is saved.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button variant="primary" asChild>
                  <Link to="/setup">Set up from questions</Link>
                </Button>
                <Button variant="ghost" onClick={() => setAdding(true)}>
                  Add a goal by hand
                </Button>
              </div>
            </div>
          )
        ) : (
          <ul className="surface">
            {goals.map((goal) => (
              <GoalRow key={goal.id} goal={goal} />
            ))}
          </ul>
        )}
      </PageSection>

      {!none && <KeptSinceSetup setup={setup} />}

      <PageSection title="Values">
        <ValuesForm text={values.values_text} />
      </PageSection>
    </Page>
  );
}

function KeptSinceSetup({ setup }: { setup: SetupView }): JSX.Element | null {
  const count = setup.kept_since_setup;
  if (count === 0) return null;
  const kept = setup.kept_anyway.slice(0, Math.min(3, count));
  return (
    <section aria-labelledby="kept-since-setup" className="mt-6 surface surface-pad">
      <h2 id="kept-since-setup" className="font-semibold">
        {count === 1 ? "1 post you kept" : `${count} posts you kept`} that Sift would have archived
      </h2>
      <p className="mt-0.5 text-[13px] text-silt leading-[19px]">
        Redo setup and Sift drafts goals that cover them. Nothing changes until you save the draft.
      </p>
      <ul className="mt-3 flex flex-col gap-2">
        {kept.map((k) => (
          <li key={k.item_id} className="min-w-0">
            <Link
              to="/items/$itemId"
              params={{ itemId: k.item_id }}
              className="block truncate font-[560] hover:underline hover:underline-offset-2"
            >
              {k.title}
            </Link>
            <p className="truncate text-[13px] text-silt">
              {k.reason.goal_title ? `For ${k.reason.goal_title}` : "None of your goals"}
              {k.reason.note && `: ${k.reason.note}`}
            </p>
          </li>
        ))}
      </ul>
      <Button variant="primary" size="sm" asChild className="mt-4">
        <Link to="/setup">Redo setup</Link>
      </Button>
    </section>
  );
}

function GoalRow({ goal }: { goal: Goal }): JSX.Element {
  const [editing, setEditing] = useState(false);
  return (
    <li className="border-mesh border-t px-4 py-3.5 first:border-t-0">
      {editing ? (
        <GoalForm goal={goal} onDone={() => setEditing(false)} onCancel={() => setEditing(false)} />
      ) : (
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className={cn(
              "mt-[7px] size-[7px] shrink-0 rounded-full",
              goal.active ? "bg-graphite" : "shadow-[inset_0_0_0_1.5px_var(--silt)]",
            )}
          />
          <div className={cn("min-w-0 flex-1", !goal.active && "text-silt")}>
            <p className="font-semibold">{goal.title}</p>
            {goal.description && <p className="mt-0.5 text-[13px] text-silt">{goal.description}</p>}
          </div>
          <span className="shrink-0 pt-px text-caption text-silt max-[700px]:hidden">
            {CATEGORIES[goal.category]}
            {!goal.active && " · inactive"}
          </span>
          <Button size="sm" variant="ghost" onClick={() => setEditing(true)} aria-label={`Edit ${goal.title}`}>
            Edit
          </Button>
        </div>
      )}
    </li>
  );
}

function GoalForm({ goal, onDone, onCancel }: { goal?: Goal; onDone: () => void; onCancel?: () => void }): JSX.Element {
  const create = useCreateGoal();
  const update = useUpdateGoal();
  const [title, setTitle] = useState(goal?.title ?? "");
  const [description, setDescription] = useState(goal?.description ?? "");
  const [category, setCategory] = useState<GoalCategory>(goal?.category ?? "personal");
  const id = useId();
  const pending = create.isPending || update.isPending;
  const error = create.error ?? update.error;

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    const body = { title, description, category };
    const done = (message: string) => () => {
      toast(message);
      onDone();
    };
    if (goal) update.mutate({ id: goal.id, patch: body }, { onSuccess: done("Goal saved") });
    else create.mutate(body, { onSuccess: done("Goal added") });
  };
  const toggle = () => goal && update.mutate({ id: goal.id, patch: { active: !goal.active } }, { onSuccess: onDone });

  return (
    <form onSubmit={onSubmit} className="space-y-3.5">
      <div>
        <Label htmlFor={`${id}-title`}>Title</Label>
        <Input
          id={`${id}-title`}
          required
          maxLength={GOAL_TITLE_MAX}
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Market my web app"
          aria-invalid={Boolean(error)}
        />
        {error && <FieldError className="mt-1.5">{error.message}</FieldError>}
      </div>
      <div>
        <Label htmlFor={`${id}-why`}>Why it matters</Label>
        <Textarea
          id={`${id}-why`}
          maxLength={GOAL_DESCRIPTION_MAX}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="SEO, GEO, Search Console and organic ad formats."
          className="min-h-16"
        />
      </div>
      <div>
        <Label htmlFor={`${id}-category`}>Category</Label>
        <Select
          id={`${id}-category`}
          value={category}
          onChange={(e) => setCategory(GOAL_CATEGORIES.find((c) => c === e.target.value) ?? "other")}
        >
          {GOAL_CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {CATEGORIES[c]}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-wrap items-center gap-2 pt-1">
        <Button type="submit" variant="primary" disabled={pending}>
          {goal ? "Save goal" : "Add goal"}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
        {goal && (
          <Button type="button" variant="ghost" className="ml-auto" disabled={pending} onClick={toggle}>
            {goal.active ? "Deactivate" : "Reactivate"}
          </Button>
        )}
      </div>
    </form>
  );
}

function ValuesForm({ text }: { text: string }): JSX.Element {
  const save = useSaveValues();
  const [draft, setDraft] = useState(text);
  const [saved, setSaved] = useState(false);
  const id = useId();
  return (
    <form
      className="surface p-4"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(draft, { onSuccess: () => setSaved(true) });
      }}
    >
      <Label htmlFor={id}>What you care about, and what counts as noise</Label>
      <Textarea
        id={id}
        maxLength={VALUES_MAX}
        value={draft}
        onChange={(e) => {
          setDraft(e.target.value);
          setSaved(false);
        }}
        placeholder="I value craft, local spots and things I can try within a week. Hustle content and gadget hype are noise."
      />
      <div className="mt-3 flex items-center justify-end gap-3">
        {save.error && <FieldError className="mr-auto">{save.error.message}</FieldError>}
        {saved && <span className="text-[13px] text-silt">Saved</span>}
        <Button type="submit" variant="primary" disabled={save.isPending}>
          Save values
        </Button>
      </div>
    </form>
  );
}
