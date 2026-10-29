import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { type ComponentProps, type JSX, useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { keyboardInset } from "@/lib/viewport";

export const Sheet = Dialog.Root;
export const SheetTrigger = Dialog.Trigger;

function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const update = () => setInset(keyboardInset(window.innerHeight, viewport));
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
    };
  }, []);
  return inset;
}

export function SheetContent({
  title,
  narrow,
  className,
  children,
  ...props
}: ComponentProps<typeof Dialog.Content> & { title: string; narrow?: boolean }): JSX.Element {
  const inset = useKeyboardInset();
  return (
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-50 bg-[rgb(12_13_16/0.32)] data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
      <Dialog.Content
        aria-describedby={undefined}
        style={{ bottom: inset }}
        className={cn(
          "fixed inset-x-0 z-50 max-h-[85dvh] overflow-y-auto rounded-t-[18px] border-mesh border-t bg-sheet px-4 pb-[max(16px,env(safe-area-inset-bottom))] text-graphite shadow-float outline-none",
          "data-[state=closed]:animate-out data-[state=closed]:slide-out-to-bottom data-[state=open]:animate-in data-[state=open]:slide-in-from-bottom data-[state=open]:duration-200",
          narrow && "min-[700px]:mx-auto min-[700px]:max-w-[520px] min-[700px]:px-5",
          className,
        )}
        {...props}
      >
        <div className="flex h-14 items-center justify-between">
          <Dialog.Title className="font-display font-[640] text-[19px]">{title}</Dialog.Title>
          <Dialog.Close
            aria-label="Close"
            className="-mr-2.5 grid size-11 cursor-pointer place-items-center rounded-full text-silt active:bg-pan-hover"
          >
            <X aria-hidden className="size-5" />
          </Dialog.Close>
        </div>
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}
