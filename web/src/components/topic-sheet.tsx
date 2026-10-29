import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Ellipsis, Plus } from "lucide-react";
import { type FormEvent, type JSX, useId, useState } from "react";
import { toast } from "sonner";
import {
  api,
  type TopicCreated,
  type TopicDetail,
  useCreateTopic,
  useDissolveTopic,
  useMergeTopic,
  useRenameTopic,
} from "@/api";
import { Button } from "@/components/ui/button";
import { FieldError, Input, Label, LineInput, Select } from "@/components/ui/field";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { TOPIC_DESCRIPTION_MAX, TOPIC_NAME_MAX } from "@/lib/limits";

export function NewTopicSheet(): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button>
          <Plus aria-hidden />
          New topic
        </Button>
      </SheetTrigger>
      <SheetContent title="New topic" narrow>
        <NewTopicForm close={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}

function addedMessage({ topic, not_moved }: TopicCreated, sorted: boolean): string {
  if (not_moved) return `Added ${topic.name}. ${not_moved}`;
  if (!sorted) return `Added ${topic.name}`;
  if (topic.kept === 0) return `Added ${topic.name}. No kept posts fit it better.`;
  return `Added ${topic.name} and moved ${topic.kept} ${topic.kept === 1 ? "post" : "posts"} to it`;
}

function NewTopicForm({ close }: { close: () => void }): JSX.Element {
  const create = useCreateTopic();
  const navigate = useNavigate();
  const id = useId();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [sort, setSort] = useState(true);
  const next = name.trim();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!next) return;
    create.mutate(
      { name: next, description: description.trim(), sort_posts: sort },
      {
        onSuccess: (created) => {
          close();
          toast(addedMessage(created, sort));
          void navigate({ to: "/topics/$topicId", params: { topicId: created.topic.id } });
        },
      },
    );
  };
  return (
    <form onSubmit={submit} className="space-y-3.5 border-mesh border-t py-4">
      <div>
        <Label htmlFor={`${id}-name`}>Name</Label>
        <Input
          id={`${id}-name`}
          required
          value={name}
          maxLength={TOPIC_NAME_MAX}
          placeholder="Marketing and growth"
          aria-invalid={create.isError || undefined}
          onChange={(e) => {
            setName(e.target.value);
            create.reset();
          }}
        />
      </div>
      <div>
        <Label htmlFor={`${id}-about`}>What belongs here</Label>
        <LineInput
          id={`${id}-about`}
          value={description}
          maxLength={TOPIC_DESCRIPTION_MAX}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <label className="flex cursor-pointer items-center gap-2.5 text-[13px] text-ink-soft">
        <input
          type="checkbox"
          checked={sort}
          onChange={(e) => setSort(e.target.checked)}
          className="size-4 shrink-0 accent-graphite"
        />
        Move kept posts that fit
      </label>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Button type="submit" variant="primary" disabled={create.isPending || !next}>
          {create.isPending ? "Adding..." : "Add topic"}
        </Button>
        {create.isPending && sort && <p className="text-[13px] text-silt">Sift is reading your kept posts.</p>}
      </div>
      {create.error && <FieldError>{create.error.message}</FieldError>}
    </form>
  );
}

export function TopicSheet({ topic }: { topic: TopicDetail }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button>
          <Ellipsis aria-hidden />
          Edit topic
        </Button>
      </SheetTrigger>
      <SheetContent title={topic.name} narrow>
        <Rename topic={topic} />
        <Merge topic={topic} close={() => setOpen(false)} />
        <Remove topic={topic} close={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}

function Rename({ topic }: { topic: TopicDetail }): JSX.Element {
  const rename = useRenameTopic();
  const [name, setName] = useState(topic.name);
  const next = name.trim();
  return (
    <form
      className="border-mesh border-t py-4"
      onSubmit={(event) => {
        event.preventDefault();
        rename.mutate({ id: topic.id, name: next }, { onSuccess: (t) => toast(`Renamed to ${t.name}`) });
      }}
    >
      <Label htmlFor="topic-name">Name</Label>
      <div className="flex gap-2">
        <Input
          id="topic-name"
          value={name}
          maxLength={TOPIC_NAME_MAX}
          aria-invalid={rename.isError || undefined}
          onChange={(e) => {
            setName(e.target.value);
            rename.reset();
          }}
        />
        <Button type="submit" disabled={rename.isPending || !next || next === topic.name}>
          Rename
        </Button>
      </div>
      {rename.error && <FieldError className="mt-2">{rename.error.message}</FieldError>}
    </form>
  );
}

function Merge({ topic, close }: { topic: TopicDetail; close: () => void }): JSX.Element {
  const merge = useMergeTopic();
  const navigate = useNavigate();
  const { data } = useQuery(api.topics);
  const others = (data?.options ?? []).filter((t) => t.id !== topic.id);
  const [into, setInto] = useState<number | null>(null);
  return (
    <form
      className="border-mesh border-t py-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (into === null) return;
        merge.mutate(
          { id: topic.id, into },
          {
            onSuccess: (survivor) => {
              close();
              toast(`Merged ${topic.name} into ${survivor.name}`);
              void navigate({ to: "/topics/$topicId", params: { topicId: survivor.id }, replace: true });
            },
          },
        );
      }}
    >
      <Label htmlFor="topic-merge">Merge into another topic</Label>
      <div className="flex gap-2">
        <Select
          id="topic-merge"
          value={into ?? ""}
          onChange={(e) => setInto(e.target.value ? Number(e.target.value) : null)}
          className="min-w-0 flex-1 [&>select]:w-full"
        >
          <option value="">Choose a topic</option>
          {others.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </Select>
        <Button type="submit" disabled={merge.isPending || into === null}>
          Merge
        </Button>
      </div>
      <p className="mt-2 text-caption text-silt">
        Its posts move over, and its name keeps pointing at the other topic.
      </p>
    </form>
  );
}

function Remove({ topic, close }: { topic: TopicDetail; close: () => void }): JSX.Element {
  const dissolve = useDissolveTopic();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const posts = `${topic.kept} kept ${topic.kept === 1 ? "post" : "posts"}`;
  if (!confirming) {
    return (
      <div className="border-mesh border-t pt-4">
        <Button variant="ghost" className="-ml-3.5 text-alarm hover:text-alarm" onClick={() => setConfirming(true)}>
          Remove topic
        </Button>
      </div>
    );
  }
  return (
    <div role="alertdialog" aria-labelledby="topic-remove" className="border-mesh border-t pt-4">
      <p id="topic-remove">
        Remove <span className="font-semibold">{topic.name}</span>? Its {posts} stay in Kept, and Sift places them on
        other topics.
      </p>
      <div className="mt-3 flex gap-2 max-[700px]:[&>*]:flex-1">
        <Button onClick={() => setConfirming(false)}>Cancel</Button>
        <Button
          variant="primary"
          className="border-alarm bg-alarm"
          disabled={dissolve.isPending}
          onClick={() =>
            dissolve.mutate(topic.id, {
              onSuccess: ({ rehoming }) => {
                close();
                toast(`Removed ${topic.name}. Sift is placing ${rehoming} ${rehoming === 1 ? "post" : "posts"} again.`);
                void navigate({ to: "/topics", replace: true });
              },
            })
          }
        >
          Remove
        </Button>
      </div>
    </div>
  );
}
