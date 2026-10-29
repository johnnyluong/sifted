import createClient from "openapi-fetch";
import type { paths } from "./schema.gen";

export const http = createClient<paths>();

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Result<T> = { data: T; error?: never; response: Response } | { data?: never; error: unknown; response: Response };

export async function unwrap<T>(call: Promise<Result<T>>): Promise<NonNullable<T>> {
  const result = await call;
  if (result.data != null) return result.data;
  throw failure(result);
}

export async function ok(call: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  const result = await call;
  if (!result.response.ok) throw failure(result);
}

function failure({ error, response }: { error?: unknown; response: Response }): ApiError {
  return new ApiError(response.status, detailMessage(error) ?? response.statusText);
}

/** FastAPI sends `{detail: string}` from HTTPException and `{detail: [{msg}]}` from request validation. */
export function detailMessage(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  const first = Array.isArray(detail) ? (detail[0] as { msg?: unknown } | undefined) : undefined;
  return typeof first?.msg === "string" ? first.msg : undefined;
}
