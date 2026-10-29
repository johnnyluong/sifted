import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient, type ItemDetail, type Submission } from "@/api";
import { route } from "@/test/fake-api";
import { detail, item, status } from "@/test/fixtures";
import { createAppRouter } from "../router";
import { Thumb } from "./thumb";

const toast = vi.hoisted(() => Object.assign(vi.fn(), { error: vi.fn() }));
vi.mock("sonner", () => ({ toast, Toaster: () => null }));

afterEach(() => {
  toast.mockClear();
  toast.error.mockClear();
});

type Sent = { name: string; type: string | null; channel: string | null; size: number };

const stored: string[] = [];
const sets: { names: string[]; channel: string }[] = [];
let app: ReturnType<typeof createAppRouter>;

function renderInbox(answer: (n: number) => Submission[] = () => [queued(1)], at = "/inbox"): Sent[] {
  const sent: Sent[] = [];
  stored.length = 0;
  sets.length = 0;
  route("POST /api/uploads/files", async (request) => {
    const name = await request.text();
    stored.push(name);
    if (name.startsWith("bad")) throw { status: 415, detail: "Sift reads PNG, JPEG, WebP, GIF and HEIC images." };
    return { name };
  });
  route("POST /api/uploads/sets", async (request) => {
    sets.push((await request.json()) as { names: string[]; channel: string });
    return [queued(9)];
  });
  window.history.replaceState(null, "", at);
  route("GET /api/status", () => status());
  route("GET /api/items", () => []);
  route("GET /api/imports", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  route("POST /api/uploads", async (request) => {
    const body = await request.arrayBuffer();
    sent.push({
      name: new TextDecoder().decode(body),
      type: request.headers.get("content-type"),
      channel: new URL(request.url).searchParams.get("channel"),
      size: body.byteLength,
    });
    return answer(sent.length);
  });
  const queryClient = createQueryClient();
  app = createAppRouter(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={app} />
    </QueryClientProvider>,
  );
  return sent;
}

function queued(id: number): Submission {
  return { kind: "queued", item: item({ id, source: "image", display_title: "Image post" }) };
}

const image = (name: string, type = "image/png") => new File([name], name, { type });

function paste(files: File[]): ClipboardEvent {
  const event = new Event("paste", { bubbles: true, cancelable: true }) as ClipboardEvent;
  Object.defineProperty(event, "clipboardData", { value: { files, getData: () => "" } });
  document.body.dispatchEvent(event);
  return event;
}

async function chooser(): Promise<HTMLElement> {
  return screen.findByRole("dialog");
}

function numbered(dialog: HTMLElement): string[] {
  return within(dialog)
    .getAllByRole("listitem")
    .map((li) => `${li.textContent?.match(/\d+/)?.[0]} ${within(li).getByRole("img").getAttribute("alt")}`);
}

function drag(
  type: "dragstart" | "dragend" | "dragenter" | "dragleave" | "dragover" | "drop",
  files: File[],
  target: Element = document.body,
): DragEvent {
  const event = new Event(type, { bubbles: true, cancelable: true }) as DragEvent;
  const items = files.map((f) => ({ kind: "file", type: f.type }));
  Object.defineProperty(event, "dataTransfer", { value: { types: ["Files"], items, files } });
  act(() => {
    target.dispatchEvent(event);
  });
  return event;
}

describe("adding images", () => {
  it("uploads each chosen file in order as its own post when asked, and toasts what Sift did with it", async () => {
    const sent = renderInbox((n) =>
      n === 1 ? [queued(1)] : [{ kind: "duplicate", item: item({ id: 2, display_title: "Menu at Lucali" }) }],
    );
    const picker = await screen.findByLabelText("Add image");
    await userEvent.upload(picker, [image("a.png"), image("b.jpg", "image/jpeg")]);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add 2 posts" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent.map((s) => [s.name, s.type, s.channel])).toEqual([
      ["a.png", "image/png", "web"],
      ["b.jpg", "image/jpeg", "web"],
    ]);
    await waitFor(() => expect(toast).toHaveBeenCalledTimes(2));
    expect(toast.mock.calls.map((c) => c[0])).toEqual([
      "Added. Processing Image post.",
      "Already saved: Menu at Lucali (kept).",
    ]);
  });

  it("names the file the server refused, and still sends the rest", async () => {
    const sent = renderInbox((n) => {
      if (n === 1) throw { status: 415, detail: "Sift reads PNG, JPEG, WebP, GIF and HEIC images." };
      return [queued(2)];
    });
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("odd.png"), image("ok.png")]);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add 2 posts" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("odd.png: Sift reads PNG, JPEG, WebP, GIF and HEIC images."),
    );
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Added. Processing Image post.", expect.anything()));
  });

  it("uploads an image pasted outside a text field", async () => {
    const sent = renderInbox();
    await screen.findByLabelText("Add image");
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: [image("image.png")], getData: () => "" },
    });
    document.body.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["image.png"]));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Added. Processing Image post.", expect.anything()));
  });

  it("uploads a screenshot pasted into the link field", async () => {
    const sent = renderInbox();
    const field = await screen.findByRole("textbox", { name: "Link to add" });
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: [image("screenshot.png")], getData: () => "" },
    });
    field.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["screenshot.png"]));
    expect((field as HTMLInputElement).value).toBe("");
  });

  it("puts a post link that came as a URI list into the link field, not its preview image", async () => {
    const sent = renderInbox();
    const field = await screen.findByRole("textbox", { name: "Link to add" });
    const event = new Event("paste", { bubbles: true, cancelable: true });
    const getData = (type: string) => (type === "text/uri-list" ? "https://www.instagram.com/reel/ABC/" : "");
    Object.defineProperty(event, "clipboardData", { value: { files: [image("preview.png")], getData } });
    field.dispatchEvent(event);
    expect(sent).toEqual([]);
    await waitFor(() => expect((field as HTMLInputElement).value).toBe("https://www.instagram.com/reel/ABC/"));
  });

  it("adds a copied screenshot from the phone Add sheet's paste button", async () => {
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: {
        read: () =>
          Promise.resolve([
            { types: ["image/png"], getType: () => Promise.resolve(new Blob(["shot"], { type: "image/png" })) },
          ]),
      },
    });
    try {
      const sent = renderInbox(undefined, "/kept");
      await userEvent.click(await screen.findByRole("button", { name: "Add a link" }));
      await userEvent.click(await screen.findByRole("button", { name: "Paste link or screenshot" }));
      await waitFor(() => expect(sent).toEqual([{ name: "shot", type: "image/png", channel: "web", size: 4 }]));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("uploads a copied web image even though its own URL came with it", async () => {
    const sent = renderInbox();
    await screen.findByLabelText("Add image");
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: [image("photo.png")], getData: () => "https://cdn.example/photo.png" },
    });
    document.body.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["photo.png"]));
  });

  it("pastes a copied post as its link, not the preview image that came with it", async () => {
    const sent = renderInbox();
    const links: string[] = [];
    route("POST /api/items", async (request) => {
      links.push(((await request.json()) as { text: string }).text);
      return [{ kind: "queued", item: item({ id: 3 }) }];
    });
    await screen.findByLabelText("Add image");
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: { files: [image("preview.png")], getData: () => "https://www.threads.com/@chef.ana/post/De2" },
    });
    document.body.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    await waitFor(() => expect(links).toEqual(["https://www.threads.com/@chef.ana/post/De2"]));
    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    expect(sent).toEqual([]);
  });

  it("leaves an image pasted into another text field to that field", async () => {
    const sent = renderInbox();
    await screen.findByRole("textbox", { name: "Link to add" });
    const field = document.body.appendChild(document.createElement("textarea"));
    try {
      const event = new Event("paste", { bubbles: true, cancelable: true });
      Object.defineProperty(event, "clipboardData", { value: { files: [image("image.png")], getData: () => "" } });
      field.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
      expect(sent).toEqual([]);
    } finally {
      field.remove();
    }
  });

  it("shows the drop overlay only while files are dragged over the window, and uploads the dropped images", async () => {
    const sent = renderInbox();
    await screen.findByLabelText("Add image");
    const files = [image("one.png"), image("two.webp", "image/webp")];
    expect(screen.queryByText("Drop to add to Sift")).toBeNull();

    drag("dragenter", files);
    expect(screen.getByText("Drop to add to Sift")).toBeTruthy();
    drag("dragenter", files);
    drag("dragleave", files);
    expect(screen.getByText("Drop to add to Sift")).toBeTruthy();
    drag("dragleave", files);
    expect(screen.queryByText("Drop to add to Sift")).toBeNull();

    const text = new Event("dragenter", { bubbles: true, cancelable: true });
    Object.defineProperty(text, "dataTransfer", { value: { types: ["text/plain"], items: [], files: [] } });
    act(() => {
      document.body.dispatchEvent(text);
    });
    expect(screen.queryByText("Drop to add to Sift")).toBeNull();

    drag("dragenter", files);
    expect(drag("dragover", files).defaultPrevented).toBe(true);
    expect(drag("drop", files).defaultPrevented).toBe(true);
    expect(screen.queryByText("Drop to add to Sift")).toBeNull();
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add 2 posts" }));
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["one.png", "two.webp"]));
  });

  it("keeps the overlay away from a dragged zip, and says only images drop here", async () => {
    const sent = renderInbox();
    await screen.findByLabelText("Add image");
    const zip = [new File(["zip"], "meta.zip", { type: "application/zip" })];
    drag("dragenter", zip);
    expect(screen.queryByText("Drop to add to Sift")).toBeNull();
    drag("drop", zip);
    expect(toast.error).toHaveBeenCalledWith("Only images can be dropped here.");
    expect(sent).toEqual([]);
  });

  it("leaves a zip dropped on the Import page's zone to that zone", async () => {
    const sent = renderInbox(undefined, "/import");
    const imported: string[] = [];
    route("POST /api/imports", (request) => {
      imported.push(new URL(request.url).searchParams.get("filename") ?? "");
      throw { status: 422, detail: "Not an export." };
    });
    const zone = (await screen.findByText("Drop the export here, or choose the zip")).closest("label");
    expect(zone).not.toBeNull();
    const zip = [new File(["zip"], "meta.zip", { type: "application/zip" })];
    drag("drop", zip, zone as Element);
    await waitFor(() => expect(imported).toEqual(["meta.zip"]));
    expect(sent).toEqual([]);
    expect(toast.error).not.toHaveBeenCalledWith("Only images can be dropped here.");
  });

  it("offers the picker only the image types Sift reads", async () => {
    renderInbox();
    const picker = await screen.findByLabelText<HTMLInputElement>("Add image");
    expect(picker.accept).toBe("image/png,image/jpeg,image/webp,image/gif,image/heic,image/heif,.heic,.heif");
  });

  it("drops only the image types Sift reads, and lets an untyped file through for the server to judge", async () => {
    const sent = renderInbox();
    await screen.findByLabelText("Add image");
    const files = [
      image("logo.svg", "image/svg+xml"),
      image("scan.tiff", "image/tiff"),
      image("photo.heic", ""),
      image("mystery", ""),
      image("shot.png"),
    ];
    drag("drop", files);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add 3 posts" }));
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["photo.heic", "mystery", "shot.png"]));

    drag("drop", [image("logo.svg", "image/svg+xml")]);
    expect(toast.error).toHaveBeenCalledWith("Only images can be dropped here.");
  });

  it("never uploads an image dragged from the page itself", async () => {
    const sent = renderInbox();
    await screen.findByLabelText("Add image");
    const onPage = [image("thumbnail.jpg", "image/jpeg")];
    const thumb = document.createElement("img");
    document.body.append(thumb);

    drag("dragstart", onPage, thumb);
    drag("dragenter", onPage);
    expect(screen.queryByText("Drop to add to Sift")).toBeNull();
    expect(drag("drop", onPage).defaultPrevented).toBe(false);
    drag("dragend", onPage, thumb);
    thumb.remove();
    expect(toast.error).not.toHaveBeenCalled();

    const fromFinder = [image("from-finder.png")];
    drag("dragenter", fromFinder);
    expect(screen.getByText("Drop to add to Sift")).toBeTruthy();
    drag("drop", fromFinder);
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["from-finder.png"]));
  });

  it.each(["pointermove", "mousemove", "drop"])(
    "forgets a page drag whose dragend was lost once a %s ends it, so a Finder drop still uploads",
    async (ender) => {
      const sent = renderInbox();
      await screen.findByLabelText("Add image");
      const onPage = [image("thumbnail.jpg", "image/jpeg")];
      const thumb = document.createElement("img");
      document.body.append(thumb);
      drag("dragstart", onPage, thumb);
      thumb.remove();
      drag("dragend", onPage, thumb);
      if (ender === "drop") expect(drag("drop", onPage).defaultPrevented).toBe(false);
      else
        act(() => {
          document.body.dispatchEvent(new Event(ender, { bubbles: true }));
        });

      const fromFinder = [image("from-finder.png")];
      drag("dragenter", fromFinder);
      expect(screen.getByText("Drop to add to Sift")).toBeTruthy();
      expect(drag("drop", fromFinder).defaultPrevented).toBe(true);
      await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["from-finder.png"]));
    },
  );

  it("asks before adding two or more chosen images, numbered in reading order", async () => {
    const sent = renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("c.png"), image("a.png"), image("b.png")]);
    const dialog = await chooser();
    expect(within(dialog).getByText("Add 3 images")).toBeTruthy();
    expect(numbered(dialog)).toEqual(["1 c.png", "2 a.png", "3 b.png"]);
    expect(within(dialog).getByRole("button", { name: "Add as one post" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Add 3 posts" })).toBeTruthy();
    expect(sent).toEqual([]);
    expect(stored).toEqual([]);
  });

  it("stores each image and queues one post from their names in order", async () => {
    const sent = renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("c.png"), image("a.png"), image("b.png")]);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(sets).toEqual([{ names: ["c.png", "a.png", "b.png"], channel: "web" }]));
    expect(stored).toEqual(["c.png", "a.png", "b.png"]);
    expect(sent).toEqual([]);
    await waitFor(() => expect(toast).toHaveBeenCalledTimes(1));
    expect(toast).toHaveBeenCalledWith("Added. Processing Image post.", expect.anything());
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("makes no post when the server refuses one of its images, and names that image", async () => {
    renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [
      image("a.png"),
      image("bad.png"),
      image("c.png"),
    ]);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2));
    expect(toast.error.mock.calls).toEqual([
      ["bad.png: Sift reads PNG, JPEG, WebP, GIF and HEIC images."],
      ["Nothing was added: one post needs every image. Remove the refused one and add them again."],
    ]);
    expect(sets).toEqual([]);
  });

  it("refuses a second batch that arrives before the chooser has drawn", async () => {
    renderInbox();
    await screen.findByLabelText("Add image");
    act(() => {
      paste([image("p1.png"), image("p2.png")]);
      paste([image("q1.png"), image("q2.png")]);
    });
    const dialog = await chooser();
    expect(toast.error.mock.calls).toEqual([["Finish the images already open first."]]);
    expect(numbered(dialog)).toEqual(["1 p1.png", "2 p2.png"]);
  });

  it("leaves a removed image out of the post and recounts", async () => {
    renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("a.png"), image("b.png"), image("c.png")]);
    const dialog = await chooser();
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove image 2" }));
    expect(within(dialog).getByText("Add 2 images")).toBeTruthy();
    expect(numbered(dialog)).toEqual(["1 a.png", "2 c.png"]);
    expect(within(dialog).queryByRole("button", { name: /Remove image/ })).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(sets.map((s) => s.names)).toEqual([["a.png", "c.png"]]));
  });

  it("adds nothing when the sheet is closed", async () => {
    const sent = renderInbox();
    const picker = await screen.findByLabelText("Add image");
    await userEvent.upload(picker, [image("a.png"), image("b.png")]);
    await chooser();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await userEvent.upload(picker, [image("a.png"), image("b.png")]);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect([sent, stored, sets]).toEqual([[], [], []]);
    expect(toast).not.toHaveBeenCalled();
  });

  it("offers one post only up to ten images, and still adds them each", async () => {
    const sent = renderInbox();
    const files = Array.from({ length: 12 }, (_, i) => image(`s${i}.png`));
    await userEvent.upload(await screen.findByLabelText("Add image"), files);
    const dialog = await chooser();
    expect(within(dialog).getByText("One post holds at most 10 images. Remove 2 to add them as one.")).toBeTruthy();
    expect(within(dialog).getByRole<HTMLButtonElement>("button", { name: "Add as one post" }).disabled).toBe(true);
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove image 1" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove image 1" }));
    expect(within(dialog).getByRole<HTMLButtonElement>("button", { name: "Add as one post" }).disabled).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Add 10 posts" }));
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(files.slice(2).map((f) => f.name)));
  });

  it("adds a single chosen image straight away", async () => {
    const sent = renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("only.png")]);
    await waitFor(() => expect(sent.map((s) => s.name)).toEqual(["only.png"]));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks about two or more pasted or dropped images too", async () => {
    renderInbox();
    await screen.findByLabelText("Add image");
    expect(paste([image("p1.png"), image("p2.png")]).defaultPrevented).toBe(true);
    let dialog = await chooser();
    expect(numbered(dialog)).toEqual(["1 p1.png", "2 p2.png"]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(sets.map((s) => s.names)).toEqual([["p1.png", "p2.png"]]));

    drag("drop", [image("d1.png"), image("d2.png")]);
    dialog = await chooser();
    expect(numbered(dialog)).toEqual(["1 d1.png", "2 d2.png"]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Add as one post" }));
    await waitFor(() =>
      expect(sets.map((s) => s.names)).toEqual([
        ["p1.png", "p2.png"],
        ["d1.png", "d2.png"],
      ]),
    );
  });

  it("stores a set's images at once and keeps their order when they finish out of order", async () => {
    renderInbox();
    const arrived: string[] = [];
    let allArrived = () => {};
    const gate = new Promise<void>((resolve) => (allArrived = resolve));
    route("POST /api/uploads/files", async (request) => {
      const name = await request.text();
      arrived.push(name);
      if (arrived.length === 3) allArrived();
      await gate;
      if (name === "a.png") await new Promise((resolve) => setTimeout(resolve, 20));
      return { name };
    });
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("a.png"), image("b.png"), image("c.png")]);
    await userEvent.click(within(await chooser()).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(sets.map((s) => s.names)).toEqual([["a.png", "b.png", "c.png"]]));
  });

  it("asks you to finish the open images before more, and adds none of the later ones", async () => {
    const sent = renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("a.png"), image("b.png")]);
    const dialog = await chooser();
    expect(paste([image("p1.png"), image("p2.png")]).defaultPrevented).toBe(true);
    drag("drop", [image("d1.png")]);
    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(2));
    expect(toast.error.mock.calls).toEqual([
      ["Finish the images already open first."],
      ["Finish the images already open first."],
    ]);
    expect(document.querySelectorAll("[role=dialog]")).toHaveLength(1);
    expect(numbered(dialog)).toEqual(["1 a.png", "2 b.png"]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(sets.map((s) => s.names)).toEqual([["a.png", "b.png"]]));
    expect(stored).toEqual(["a.png", "b.png"]);
    expect(sent).toEqual([]);
  });

  it("keeps the chooser after the picker that asked is gone, and toasts what Sift made", async () => {
    renderInbox();
    await userEvent.upload(await screen.findByLabelText("Add image"), [image("a.png"), image("b.png")]);
    const dialog = await chooser();
    await act(() => app.navigate({ to: "/kept" }));
    await waitFor(() => expect(screen.queryByLabelText("Add image")).toBeNull());
    expect(dialog.isConnected).toBe(true);
    await userEvent.click(within(dialog).getByRole("button", { name: "Add as one post" }));
    await waitFor(() => expect(sets.map((s) => s.names)).toEqual([["a.png", "b.png"]]));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Added. Processing Image post.", expect.anything()));
    expect(toast).toHaveBeenCalledTimes(1);
  });

  it("opens the chooser over the phone Add sheet, and finishes the post after that sheet closes without closing it again", async () => {
    renderInbox(undefined, "/kept");
    await userEvent.click(await screen.findByRole("button", { name: "Add a link" }));
    const sheet = await screen.findByRole("dialog", { name: "Add a link" });
    await userEvent.upload(within(sheet).getByLabelText("Add image"), [image("a.png"), image("b.png")]);
    await screen.findByRole("dialog", { name: "Add 2 images" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add 2 images" })).toBeNull());
    expect(sheet.isConnected).toBe(true);

    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    route("POST /api/uploads/files", async (request) => {
      const name = await request.text();
      await gate;
      return { name };
    });
    await userEvent.upload(within(sheet).getByLabelText("Add image"), [image("c.png"), image("d.png")]);
    await userEvent.click(
      within(await screen.findByRole("dialog", { name: "Add 2 images" })).getByRole("button", {
        name: "Add as one post",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Add 2 images" })).toBeNull());
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(document.querySelector("[role=dialog]")).toBeNull());
    await userEvent.click(screen.getByRole("button", { name: "Add a link" }));
    await screen.findByRole("dialog", { name: "Add a link" });
    release();
    await waitFor(() => expect(sets.map((s) => s.names)).toEqual([["c.png", "d.png"]]));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Added. Processing Image post.", expect.anything()));
    expect(toast).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "Add a link" })).toBeTruthy();
  });

  it("keeps thumbnails from being dragged at all", () => {
    render(<Thumb url="/api/items/1/thumbnail" placeholder="IM" />);
    expect(document.querySelector("img")?.getAttribute("draggable")).toBe("false");
  });
});

function renderItem(shown: ItemDetail): void {
  window.history.replaceState(null, "", `/items/${shown.id}`);
  route("GET /api/status", () => status());
  route("GET /api/goals", () => []);
  route("GET /api/topics", () => ({ groups: [], suggestions: [], options: [] }));
  route(`GET /api/items/${shown.id}`, () => shown);
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={createAppRouter(queryClient)} />
    </QueryClientProvider>,
  );
}

describe("an image post's page", () => {
  it("shows every image of a set, numbered, each opening the stored image", async () => {
    const images = ["/api/uploads/a.png", "/api/uploads/b.jpg", "/api/uploads/c.png"];
    renderItem(detail({ source: "image", url: "/api/uploads/a.png,b.jpg,c.png", images }));
    expect(await screen.findByRole("button", { name: "3 images" })).toBeTruthy();
    expect(screen.queryByText("Open original")).toBeNull();
    const links = within(screen.getByRole("list", { name: "Images" })).getAllByRole("link");
    expect(links.map((a) => [a.getAttribute("aria-label"), a.getAttribute("href")])).toEqual([
      ["Open image 1", images[0]],
      ["Open image 2", images[1]],
      ["Open image 3", images[2]],
    ]);
  });

  it("keeps Open original for a single image", async () => {
    renderItem(detail({ source: "image", url: "/api/uploads/a.png", images: ["/api/uploads/a.png"] }));
    const original = await screen.findByRole("link", { name: "Open original" });
    expect(original.getAttribute("href")).toBe("/api/uploads/a.png");
    expect(screen.queryByText("Images, in reading order")).toBeNull();
  });
});
