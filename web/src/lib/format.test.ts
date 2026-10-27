import { describe, expect, it } from "vitest";
import { formatAgo, formatDay, formatMoment } from "@/lib/format";

const NY = "America/New_York";

describe("dates in the server's time zone", () => {
  it("shows the wall-clock time where the server is, not where the browser is", () => {
    expect(formatMoment("2026-10-21T19:04:00Z", NY)).toBe("Oct 21, 3:04 PM");
    expect(formatMoment("2026-10-21T19:04:00Z", "Asia/Tokyo")).toBe("Oct 22, 4:04 AM");
  });

  it("drops the year only for this year", () => {
    const now = new Date("2026-10-23T12:00:00Z");
    expect(formatDay("2026-10-21T19:04:00Z", NY, now)).toBe("Oct 21");
    expect(formatDay("2025-10-21T19:04:00Z", NY, now)).toBe("Oct 21, 2025");
  });

  it("counts minutes and hours for recent rows", () => {
    const now = new Date("2026-10-21T19:10:00Z");
    expect(formatAgo("2026-10-21T19:09:40Z", NY, now)).toBe("just now");
    expect(formatAgo("2026-10-21T19:06:00Z", NY, now)).toBe("4 min ago");
    expect(formatAgo("2026-10-21T16:10:00Z", NY, now)).toBe("3 h ago");
    expect(formatAgo("2026-10-19T16:10:00Z", NY, now)).toBe("Oct 19");
  });
});
