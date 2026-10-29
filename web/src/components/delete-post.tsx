import type { JSX } from "react";
import { toast } from "sonner";
import { type Item, useDeleteItem } from "@/api";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";

export const DELETE_LABEL = "Delete";

/** `onClose(true)` once the post is deleted; `false` on Cancel or a failure, which the server's toast reports. */
export function ConfirmDelete({
  item,
  open,
  onClose,
}: {
  item: Pick<Item, "id" | "display_title">;
  open: boolean;
  onClose: (deleted: boolean) => void;
}): JSX.Element {
  const del = useDeleteItem();
  const confirm = async () => {
    try {
      await del.mutateAsync(item.id);
    } catch {
      onClose(false);
      return;
    }
    toast(`Deleted: ${item.display_title}`);
    onClose(true);
  };
  return (
    <Sheet open={open} onOpenChange={(next) => !next && !del.isPending && onClose(false)}>
      <SheetContent title="Delete this post?" narrow>
        <p className="text-ink-soft">It is removed from Sift with its saved media. This can't be undone.</p>
        <div className="mt-4 flex justify-end gap-2 max-[700px]:[&>*]:flex-1">
          <Button disabled={del.isPending} onClick={() => onClose(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            className="border-alarm bg-alarm"
            disabled={del.isPending}
            onClick={() => void confirm()}
          >
            {DELETE_LABEL}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
