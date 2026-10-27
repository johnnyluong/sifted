// The Clipboard API exists only in secure contexts: over plain HTTP (a Tailscale IP) it is undefined.
export function canReadClipboard(): boolean {
  return typeof navigator.clipboard?.readText === "function";
}

// Must run inside the tap's handler: iOS shows its Paste callout and rejects when it is dismissed.
export async function readClipboard(): Promise<string | null> {
  if (!canReadClipboard()) return null;
  try {
    const text = await navigator.clipboard.readText();
    return text.trim() ? text : null;
  } catch {
    return null;
  }
}

export async function writeClipboard(text: string): Promise<boolean> {
  if (typeof navigator.clipboard?.writeText !== "function") return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
