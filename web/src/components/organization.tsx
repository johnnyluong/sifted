import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { type JSX, useState } from "react";
import { toast } from "sonner";
import { api, type ItemDetail, type ItemOrganization, type TopicRef, useSetItemTopic } from "@/api";
import { Bullets, Facts, Section } from "@/components/card-body";
import { SIFTS_PICK } from "@/components/shelf";
import { Button, chipClass } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { TOPIC_CHOOSERS } from "@/lib/vocabulary";

const linkClass = "underline decoration-dust underline-offset-[3px] hover:decoration-graphite";

export function Organization({ item }: { item: ItemDetail }): JSX.Element | null {
  const org = item.organization;
  if (!org) return null;
  const cardShowsKeyPoints = item.card?.item_type === "other" && item.card.details.key_points.length > 0;
  return (
    <>
      {org.key_points.length > 0 && !cardShowsKeyPoints && (
        <Section title="Key points" className="mt-7">
          <Bullets items={org.key_points} />
        </Section>
      )}
      <Section title="Organization" className="mt-7">
        <Facts
          rows={[
            ["Topic", <TopicPicker key="topic" itemId={item.id} org={org} />],
            [
              "Labels",
              org.labels.length > 0 && (
                <span key="labels" className="flex flex-wrap gap-2">
                  {org.labels.map((label) => (
                    <Link key={label} to="/kept" search={{ label }} className={chipClass()}>
                      {label}
                    </Link>
                  ))}
                </span>
              ),
            ],
            [
              "Covered by",
              org.covered_by && (
                <span key="covered">
                  <Link to="/items/$itemId" params={{ itemId: org.covered_by.id }} className={linkClass}>
                    {org.covered_by.title}
                  </Link>
                  <span className="block text-caption text-silt">That post says everything this one does.</span>
                </span>
              ),
            ],
            [
              "Covers",
              org.covers.length > 0 && (
                <ul key="covers" className="space-y-1">
                  {org.covers.map((ref) => (
                    <li key={ref.id}>
                      <Link to="/items/$itemId" params={{ itemId: ref.id }} className={linkClass}>
                        {ref.title}
                      </Link>
                    </li>
                  ))}
                </ul>
              ),
            ],
            [
              "Brief",
              org.cited_in > 0 && org.topic && (
                <Link key="brief" to="/topics/$topicId" params={{ topicId: org.topic.id }} className={linkClass}>
                  Cited in {org.cited_in} {org.cited_in === 1 ? "point" : "points"} of the {org.topic.name} brief
                </Link>
              ),
            ],
          ]}
        />
      </Section>
    </>
  );
}

function movedMessage(chosen: number | typeof SIFTS_PICK, landed: TopicRef | null): string {
  if (chosen !== SIFTS_PICK && landed) return `Moved to ${landed.name}`;
  return landed ? `Back to Sift's pick: ${landed.name}` : "Back to Sift's pick";
}

function TopicPicker({ itemId, org }: { itemId: number; org: ItemOrganization }): JSX.Element {
  const move = useSetItemTopic();
  const options = useQuery(api.topics).data?.options ?? [];
  const yours = org.topic_chosen_by === "you" ? org.topic : null;
  const choices = options.filter((t) => t.id !== org.sift_topic?.id || yours?.id === t.id);
  const pick = (topic: number | null, onDone?: () => void) =>
    move.mutate(
      { id: itemId, topic },
      {
        onSuccess: (after) => {
          toast(movedMessage(topic, after.topic));
          onDone?.();
        },
      },
    );
  return (
    <span className="block max-w-[320px]">
      <Select
        aria-label="Topic"
        value={yours?.id ?? ""}
        disabled={move.isPending}
        onChange={(e) => pick(e.target.value ? Number(e.target.value) : SIFTS_PICK)}
        className="w-full max-[700px]:hidden [&>select]:w-full"
      >
        <option value="">{`${TOPIC_CHOOSERS.sift}: ${org.sift_topic?.name ?? "not sorted yet"}`}</option>
        {choices.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </Select>
      <MoveToSheet org={org} choices={choices} current={yours?.id ?? null} pending={move.isPending} onPick={pick} />
      <span className="mt-1 flex gap-2 text-caption text-silt">
        {org.topic_chosen_by && TOPIC_CHOOSERS[org.topic_chosen_by]}
        {org.topic && (
          <Link
            to="/topics/$topicId"
            params={{ topicId: org.topic.id }}
            className="text-graphite underline underline-offset-2 max-[700px]:-my-3 max-[700px]:py-3"
          >
            Open topic
          </Link>
        )}
      </span>
    </span>
  );
}

function MoveToSheet({
  org,
  choices,
  current,
  pending,
  onPick,
}: {
  org: ItemOrganization;
  choices: TopicRef[];
  current: number | null;
  pending: boolean;
  onPick: (topic: number | null, onDone: () => void) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const choose = (topic: number | null) => {
    if (topic === current) setOpen(false);
    else onPick(topic, () => setOpen(false));
  };
  return (
    <span className="hidden items-center justify-between gap-3 max-[700px]:flex">
      <span className="min-w-0 truncate">{org.topic?.name ?? "Not sorted yet"}</span>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button size="sm">Move to...</Button>
        </SheetTrigger>
        <SheetContent title="Move to">
          <ul className="overflow-hidden rounded-xl border border-mesh">
            <MoveChoice
              label="Sift's pick"
              hint={org.sift_topic?.name ?? "Not sorted yet"}
              current={current === SIFTS_PICK}
              disabled={pending}
              onClick={() => choose(SIFTS_PICK)}
            />
            {choices.map((t) => (
              <MoveChoice
                key={t.id}
                label={t.name}
                current={current === t.id}
                disabled={pending}
                onClick={() => choose(t.id)}
              />
            ))}
          </ul>
        </SheetContent>
      </Sheet>
    </span>
  );
}

function MoveChoice({
  label,
  hint,
  current,
  disabled,
  onClick,
}: {
  label: string;
  hint?: string;
  current: boolean;
  disabled: boolean;
  onClick: () => void;
}): JSX.Element {
  return (
    <li className="border-mesh border-t first:border-t-0">
      <button
        type="button"
        aria-current={current || undefined}
        disabled={disabled}
        onClick={onClick}
        className="flex min-h-14 w-full cursor-pointer items-center gap-3.5 px-4 py-2.5 text-left active:bg-hover disabled:opacity-50"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate font-semibold text-[15px]">{label}</span>
          {hint && <span className="block truncate text-caption text-silt">{hint}</span>}
        </span>
        {current && <Check aria-hidden className="size-[18px] shrink-0 text-graphite" />}
      </button>
    </li>
  );
}
