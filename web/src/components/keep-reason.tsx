import { useSuspenseQuery } from "@tanstack/react-query";
import { type FormEvent, type JSX, useId, useState } from "react";
import { toast } from "sonner";
import { api, type ItemDetail, type KeepReason, useSetKeepReason } from "@/api";
import { Button } from "@/components/ui/button";
import { Choice, FieldError, LineInput } from "@/components/ui/field";
import { KEEP_NOTE_MAX } from "@/lib/limits";

type Fit = number | "none";

export function KeepReasonPanel({ item }: { item: ItemDetail }): JSX.Element | null {
  const [editing, setEditing] = useState(false);
  if (!item.asks_keep_reason) return null;
  const reason = item.keep_reason;
  return (
    <div className="mt-5 border-mesh border-t pt-4">
      {reason && !editing ? (
        <SavedReason reason={reason} onEdit={() => setEditing(true)} />
      ) : (
        <ReasonForm
          item={item}
          onSaved={() => setEditing(false)}
          onCancel={reason ? () => setEditing(false) : undefined}
        />
      )}
    </div>
  );
}

function SavedReason({ reason, onEdit }: { reason: KeepReason; onEdit: () => void }): JSX.Element {
  return (
    <>
      <p className="text-[13px] text-silt">Why you kept it</p>
      <p className="mt-1 font-[560]">{reason.goal_title ? `For ${reason.goal_title}` : "None of your goals"}</p>
      {reason.note && <p className="mt-0.5 text-[13px] text-ink-soft leading-[19px]">{reason.note}</p>}
      <button
        type="button"
        onClick={onEdit}
        className="mt-2 text-[13px] text-silt underline underline-offset-2 hover:text-graphite max-[700px]:-my-3 max-[700px]:py-3"
      >
        Change
      </button>
    </>
  );
}

function ReasonForm({
  item,
  onSaved,
  onCancel,
}: {
  item: ItemDetail;
  onSaved: () => void;
  onCancel?: () => void;
}): JSX.Element {
  const { data: goals } = useSuspenseQuery(api.goals);
  const save = useSetKeepReason();
  const group = useId();
  const prior = item.keep_reason;
  const [fit, setFit] = useState<Fit | null>(prior ? (prior.goal_id ?? "none") : null);
  const [note, setNote] = useState(prior?.note ?? "");
  const choices: { fit: Fit; label: string }[] = [
    ...goals.filter((g) => g.active).map((g) => ({ fit: g.id, label: g.title })),
    { fit: "none", label: "None of my goals" },
  ];
  const picked = choices.find((c) => c.fit === fit)?.fit ?? null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (picked === null) return;
    save.mutate(
      { id: item.id, goal_id: picked === "none" ? null : picked, note },
      {
        onSuccess: () => {
          toast("Reason saved");
          onSaved();
        },
      },
    );
  };
  return (
    <form onSubmit={submit}>
      <fieldset>
        <legend className="font-[560]">Why keep it?</legend>
        <p className="mt-0.5 text-[13px] text-silt leading-[19px]">
          Sift uses your reason to score new posts and to suggest goals when you redo setup.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {choices.map((c) => (
            <Choice
              key={c.fit}
              name={group}
              checked={picked === c.fit}
              onChange={() => setFit(c.fit)}
              className="max-w-full py-1.5 text-left"
            >
              {c.label}
            </Choice>
          ))}
        </div>
      </fieldset>
      <LineInput
        aria-label="In your words"
        placeholder={picked === "none" ? "What is it for? (optional)" : "In your words (optional)"}
        maxLength={KEEP_NOTE_MAX}
        value={note}
        onChange={(e) => setNote(e.target.value)}
        className="mt-3"
      />
      <div className="mt-3 flex gap-2">
        <Button type="submit" size="sm" variant="primary" disabled={picked === null || save.isPending}>
          Save reason
        </Button>
        {onCancel && (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
      {save.error && <FieldError className="mt-2">{save.error.message}</FieldError>}
    </form>
  );
}
