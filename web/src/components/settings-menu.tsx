import { Link } from "@tanstack/react-router";
import { Settings } from "lucide-react";
import { type JSX, useState } from "react";
import { sideLinkClass } from "@/components/shelf";
import { ThemePicker } from "@/components/theme-picker";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { ROADMAP } from "@/lib/nav";
import { cn } from "@/lib/utils";

export function SettingsMenu({ className }: { className?: string }): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" aria-label="Settings" className={cn("size-8 px-0 [&_svg]:size-4", className)}>
          <Settings aria-hidden strokeWidth={1.8} />
        </Button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-72 p-0">
        <div className="p-3">
          <Eyebrow as="p" className="mb-2">
            Appearance
          </Eyebrow>
          <ThemePicker />
        </div>
        <div className="border-mesh border-t p-1.5">
          <Link to={ROADMAP.to} onClick={() => setOpen(false)} className={sideLinkClass}>
            <ROADMAP.icon aria-hidden className="size-4 text-silt" strokeWidth={1.8} />
            {ROADMAP.label}
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}
