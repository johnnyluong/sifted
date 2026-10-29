import { afterEach } from "vitest";

type Handler = (request: Request) => unknown | Promise<unknown>;

const routes = new Map<string, Handler>();
const calls: string[] = [];

export function route(key: `${"GET" | "POST" | "PATCH" | "PUT" | "DELETE"} /api/${string}`, handler: Handler): void {
  routes.set(key, handler);
}

export function callCount(key: string): number {
  return calls.filter((c) => c === key).length;
}

globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
  const request = new Request(input, init);
  const key = `${request.method} ${new URL(request.url).pathname}`;
  calls.push(key);
  const handler = routes.get(key);
  if (!handler) return Response.json({ detail: `no fake for ${key}` }, { status: 404 });
  try {
    const out = await handler(request);
    return out instanceof Response ? out : Response.json(out);
  } catch (error) {
    const { status = 500, detail = String(error) } = error as { status?: number; detail?: string };
    return Response.json({ detail }, { status });
  }
};

afterEach(() => {
  routes.clear();
  calls.length = 0;
});
