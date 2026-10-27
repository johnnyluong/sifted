import { describe, expect, it } from "vitest";
import { ApiError, detailMessage, http, unwrap } from "@/api/client";
import { route } from "@/test/fake-api";

describe("unwrap", () => {
  it("returns the body of a 2xx", async () => {
    route("GET /api/values", () => ({ values_text: "Craft over hype." }));
    await expect(unwrap(http.GET("/api/values"))).resolves.toEqual({ values_text: "Craft over hype." });
  });

  it("throws ApiError with the status for a 4xx", async () => {
    route("POST /api/digests", () => {
      throw { status: 409, detail: "Nothing new to surface." };
    });
    const error = await unwrap(http.POST("/api/digests")).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 409, message: "Nothing new to surface." });
  });
});

describe("detailMessage", () => {
  it("reads both FastAPI error shapes", () => {
    expect(detailMessage({ detail: "Item not found" })).toBe("Item not found");
    expect(
      detailMessage({ detail: [{ msg: "String should have at least 1 character", loc: ["body", "title"] }] }),
    ).toBe("String should have at least 1 character");
    expect(detailMessage("Internal Server Error")).toBeUndefined();
    expect(detailMessage(null)).toBeUndefined();
  });
});
