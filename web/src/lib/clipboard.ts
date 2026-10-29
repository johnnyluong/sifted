import { IMAGE_TYPES } from "@/lib/limits";

export type Clip = { text: string; files: File[] };

// The Clipboard API exists only in secure contexts: over plain HTTP (a Tailscale IP) it is undefined.
export function canReadClipboard(): boolean {
  return typeof navigator.clipboard?.read === "function" || typeof navigator.clipboard?.readText === "function";
}

// Must run inside the tap's handler: iOS shows its Paste callout and rejects when it is dismissed.
// One read per tap, so read() covers both a copied screenshot and text.
export async function readClipboard(): Promise<Clip | null> {
  const clipboard = navigator.clipboard;
  try {
    if (typeof clipboard?.read === "function") return await fromItems(await clipboard.read());
    if (typeof clipboard?.readText === "function") return clip(await clipboard.readText(), []);
  } catch {
    return null;
  }
  return null;
}

async function fromItems(items: ClipboardItem[]): Promise<Clip | null> {
  let text = "";
  const files: File[] = [];
  for (const item of items) {
    const image = item.types.find((type) => IMAGE_TYPES.includes(type));
    const blob = image && (await representation(item, image));
    if (image && blob) {
      files.push(new File([blob], `pasted-${files.length + 1}.${image.slice("image/".length)}`, { type: image }));
    }
    const plain = ["text/plain", "text/uri-list"].find((type) => item.types.includes(type));
    if (plain && !text.trim()) text = (await (await representation(item, plain))?.text()) ?? "";
  }
  return clip(text, files);
}

// One representation that cannot be fetched should not lose the others, such as a link beside its preview.
async function representation(item: ClipboardItem, type: string): Promise<Blob | null> {
  try {
    return await item.getType(type);
  } catch {
    return null;
  }
}

function clip(text: string, files: File[]): Clip | null {
  return text.trim() || files.length > 0 ? { text, files } : null;
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
