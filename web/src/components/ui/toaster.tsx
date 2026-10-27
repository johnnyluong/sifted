import type { JSX } from "react";
import { Toaster as Sonner } from "sonner";
import { DOCK_HEIGHT_VAR } from "@/lib/viewport";

export function Toaster(): JSX.Element {
  return (
    <Sonner
      position="bottom-center"
      offset={{ bottom: `calc(var(${DOCK_HEIGHT_VAR}, 0px) + 24px)` }}
      mobileOffset={{ bottom: `calc(var(${DOCK_HEIGHT_VAR}, 0px) + 12px)` }}
      toastOptions={{
        classNames: {
          toast:
            "!rounded-xl !border !border-mesh !bg-sheet !text-graphite !shadow-float !font-sans !text-[13px] !gap-2.5",
          title: "!font-[560]",
          description: "!text-silt",
          actionButton: "!bg-graphite !text-sheet !rounded-md !font-[560] !h-[26px] !px-3",
          cancelButton: "!bg-transparent !text-silt",
          error: "!text-alarm",
        },
      }}
    />
  );
}
