import { createRoute, useNavigate } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { type JSX, useId, useState } from "react";
import { toast } from "sonner";
import { type PlannedTopic, type RebuildPlan, useApplyRebuild, useDraftRebuild } from "@/api";
import { BackLink, Page, PageHeader, PageSection } from "@/components/page";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label, LineInput } from "@/components/ui/field";
import { TOPIC_DESCRIPTION_MAX, TOPIC_NAME_MAX, TOPICS_MAX } from "@/lib/limits";
import { rootRoute } from "./root";

export const rebuildRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/topics/rebuild",
  component: RebuildPage,
});

const SHOWN_POSTS = 5;

function RebuildPage(): JSX.Element {
  const draft = useDraftRebuild();
  const [plan, setPlan] = useState<RebuildPlan | null>(null);
  return (
    <Page>
      <BackLink to="/topics">Topics</BackLink>
      <PageHeader
        title="Rebuild topics"
        subtitle="Sift reads your goals and every kept post, then drafts a fresh set of topics with each post placed. Nothing changes until you apply."
      />
      {plan ? (
        <Review plan={plan} onBack={() => setPlan(null)} />
      ) : (
        <div className="mt-8 space-y-3">
          <Button
            variant="primary"
            disabled={draft.isPending}
            onClick={() => draft.mutate(undefined, { onSuccess: setPlan })}
          >
            {draft.isPending ? "Drafting..." : "Draft new topics"}
          </Button>
          {draft.isPending && (
            <p className="text-[13px] text-silt">Sift is reading your posts. This takes a few seconds.</p>
          )}
          {draft.error && <FieldError>{draft.error.message}</FieldError>}
        </div>
      )}
    </Page>
  );
}

type Card = PlannedTopic & { key: number };

function Review({ plan, onBack }: { plan: RebuildPlan; onBack: () => void }): JSX.Element {
  const apply = useApplyRebuild();
  const navigate = useNavigate();
  const [cards, setCards] = useState<Card[]>(() => plan.topics.map((t, key) => ({ ...t, key })));
  const [removed, setRemoved] = useState<Card[]>([]);
  const later = [...plan.unsorted, ...removed.flatMap((c) => c.posts)];
  const retiring = [...plan.retiring, ...removed.flatMap((c) => c.continues)];
  const full = cards.length >= TOPICS_MAX;
  const ready = cards.length > 0 && cards.every((c) => c.name.trim());

  const edit = (key: number, change: Partial<Card>) =>
    setCards(cards.map((c) => (c.key === key ? { ...c, ...change } : c)));
  const remove = (card: Card) => {
    setCards(cards.filter((c) => c.key !== card.key));
    setRemoved([...removed, card]);
  };
  const add = () =>
    setCards([
      ...cards,
      { key: Math.max(-1, ...cards.map((c) => c.key)) + 1, name: "", description: "", continues: [], posts: [] },
    ]);
  const save = () =>
    apply.mutate(
      {
        topics: cards.map((c) => ({
          name: c.name.trim(),
          description: c.description.trim(),
          continues: c.continues.map((t) => t.id),
          posts: c.posts.map((p) => p.id),
        })),
        resort: later.map((p) => p.id),
        retire: retiring.map((t) => t.id),
      },
      {
        onSuccess: () => {
          toast("Topics rebuilt");
          void navigate({ to: "/topics" });
        },
      },
    );

  return (
    <div className="mt-8">
      <PageSection
        title="New topics"
        hint="Rename or describe any of them. A topic you remove sends its posts to the list below."
        className="mt-0"
      >
        {cards.length === 0 && (
          <p className="mb-3 surface px-4 py-3 text-[13px] text-silt">Add at least one topic to apply.</p>
        )}
        <ul className="space-y-3">
          {cards.map((card) => (
            <TopicCard
              key={card.key}
              card={card}
              onChange={(change) => edit(card.key, change)}
              onRemove={() => remove(card)}
            />
          ))}
        </ul>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Button type="button" size="sm" disabled={full} onClick={add}>
            <Plus aria-hidden />
            Add a topic
          </Button>
          {full && <p className="text-[13px] text-silt">Sift keeps up to {TOPICS_MAX} topics.</p>}
        </div>
      </PageSection>

      {later.length > 0 && (
        <PageSection title="After you apply, Sift sorts these" hint="Each one lands on whichever new topic fits it.">
          <ul aria-label="Sorted after you apply" className="surface">
            {later.map((post) => (
              <li key={post.id} className="truncate border-mesh border-t px-4 py-2.5 text-[13px] first:border-t-0">
                {post.title}
              </li>
            ))}
          </ul>
        </PageSection>
      )}

      {retiring.length > 0 && (
        <p className="mt-8 text-[13px] text-silt">
          Removed: <span className="text-ink-soft">{retiring.map((t) => t.name).join(", ")}</span>
        </p>
      )}

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <Button variant="primary" disabled={apply.isPending || !ready} onClick={save}>
          {apply.isPending ? "Applying..." : "Apply"}
        </Button>
        <Button variant="ghost" onClick={onBack}>
          Back
        </Button>
        {apply.error && <FieldError>{apply.error.message}</FieldError>}
      </div>
    </div>
  );
}

function TopicCard({
  card,
  onChange,
  onRemove,
}: {
  card: Card;
  onChange: (change: Partial<Card>) => void;
  onRemove: () => void;
}): JSX.Element {
  const id = useId();
  const [all, setAll] = useState(false);
  const shown = all ? card.posts : card.posts.slice(0, SHOWN_POSTS);
  const hidden = card.posts.length - shown.length;
  return (
    <li className="space-y-3.5 surface p-4">
      <div>
        <div className="flex items-center justify-between gap-2">
          <Label htmlFor={`${id}-name`}>Topic</Label>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="-mt-1.5"
            aria-label={`Remove ${card.name || "this topic"}`}
            onClick={onRemove}
          >
            Remove
          </Button>
        </div>
        <Input
          id={`${id}-name`}
          maxLength={TOPIC_NAME_MAX}
          value={card.name}
          aria-invalid={!card.name.trim() || undefined}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="Marketing and growth"
        />
        <p className="mt-1.5 text-caption text-silt">
          {card.continues.length > 0 ? `Continues ${card.continues.map((t) => t.name).join(", ")}` : "New"}
        </p>
      </div>
      <div>
        <Label htmlFor={`${id}-about`}>What belongs here</Label>
        <LineInput
          id={`${id}-about`}
          maxLength={TOPIC_DESCRIPTION_MAX}
          value={card.description}
          onChange={(e) => onChange({ description: e.target.value })}
        />
      </div>
      {card.posts.length === 0 ? (
        <p className="text-[13px] text-silt">No posts yet. Sift files posts here as they fit.</p>
      ) : (
        <div>
          <p className="mb-1 font-[520] text-[13px] text-ink-soft">
            {card.posts.length} {card.posts.length === 1 ? "post" : "posts"}
          </p>
          <ul aria-label={`Posts on ${card.name || "this topic"}`} className="space-y-0.5 text-[13px] text-silt">
            {shown.map((post) => (
              <li key={post.id} className="truncate">
                {post.title}
              </li>
            ))}
          </ul>
          {hidden > 0 && (
            <Button type="button" size="sm" variant="ghost" className="-ml-3 mt-1" onClick={() => setAll(true)}>
              Show {hidden} more
            </Button>
          )}
        </div>
      )}
    </li>
  );
}
