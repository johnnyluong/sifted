import type { Import, Item, ItemDetail, ItemMotion, Status, Topic, TopicDetail } from "@/api";

export function status(overrides: { revision?: string; busy?: boolean; in_motion?: ItemMotion[] } = {}): Status {
  return {
    counts: {},
    nav: { inbox: 1, kept: 4, wishlist: 3, archived: 9, topics: 2 },
    llm: "fake",
    active_goals: 2,
    has_digest: false,
    notice: null,
    threshold: 60,
    timezone: "America/New_York",
    digest_schedule: "Sundays at 6:00pm",
    pulse: { revision: overrides.revision ?? "r1", busy: overrides.busy ?? false },
    in_motion: overrides.in_motion ?? [],
  };
}

export function item(overrides: Partial<Item> = {}): Item {
  return {
    id: 1,
    source: "instagram",
    url: "https://www.instagram.com/reel/ABC/",
    origin_channel: "web",
    status: "kept",
    state_label: "Kept",
    waiting_for: null,
    status_reason: null,
    received_at: "2026-10-21T19:04:00Z",
    author_handle: "nycfoodie",
    thumbnail_url: null,
    media_kind: "video",
    item_type: "place",
    title: "Los Tacos No. 1",
    summary: "Adobada tacos in Chelsea Market.",
    next_action: "Go on a weekday before noon.",
    relevance_score: 72,
    matched_goal_id: 1,
    matched_goal_title: "NYC food and experiences",
    user_override: null,
    threshold_decision: "keep",
    stage: null,
    failure_kind: null,
    failure_hint: null,
    next_attempt_at: null,
    last_error: null,
    actions: ["archive", "done", "reprocess"],
    can_delete: false,
    wishlist: false,
    wishlist_post: false,
    product: null,
    in_motion: false,
    gist: "Adobada tacos worth the Chelsea Market line.",
    labels: ["tacos", "with friends"],
    topic: { id: 1, name: "NYC restaurants" },
    covered_by: null,
    display_title: "Los Tacos No. 1",
    ...overrides,
  };
}

export function detail(overrides: Partial<ItemDetail> = {}): ItemDetail {
  return {
    ...item(),
    card: null,
    relevance_reason: "Matches NYC food and experiences.",
    model_decision: "keep",
    caption: "Best tacos.",
    post_text: null,
    transcript: null,
    ocr_text: null,
    attempts: 1,
    extract_model: "claude-sonnet-5-5",
    score_model: "claude-sonnet-5-5",
    processed_at: "2026-10-21T19:06:00Z",
    done_at: null,
    organization: null,
    can_wishlist: true,
    wishlist_override: null,
    asks_keep_reason: false,
    keep_reason: null,
    images: [],
    ...overrides,
  };
}

export function importView(overrides: Partial<Import> = {}): Import {
  return {
    id: 1,
    filename: "instagram-2026-10-23.zip",
    phase: "preview",
    created_at: "2026-10-23T14:00:00Z",
    started_at: null,
    files_read: ["your_instagram_activity/saved/saved_posts.json"],
    files_skipped_large: [],
    files_skipped_budget: [],
    unsupported_count: 5,
    unsupported_sample: ["https://www.instagram.com/stories/chef/1/"],
    counts: {
      links: 412,
      found: 375,
      waiting: 0,
      released: 0,
      duplicate: 37,
      skipped: 0,
      kept: 0,
      archived: 0,
      failed: 0,
      in_progress: 0,
    },
    max_posts: null,
    per_post: { usd: 0.0238, tokens: 9900 },
    options: [
      { limit: 50, estimate: { posts: 50, usd: 1.19, seconds: 9000 } },
      { limit: 100, estimate: { posts: 100, usd: 2.38, seconds: 18000 } },
      { limit: null, estimate: { posts: 375, usd: 8.93, seconds: 272700 } },
    ],
    remaining: null,
    pace: { gap_seconds: 180, daily_cap: 100 },
    hold: null,
    hold_until: null,
    pause_reason: null,
    current: null,
    actions: ["start", "cancel"],
    ...overrides,
  };
}

export function topicDetail(overrides: Partial<TopicDetail> = {}): TopicDetail {
  const ref = (id: number, title: string) => ({ id, title });
  return {
    id: 3,
    name: "NYC restaurants",
    description: "Places to eat in the city.",
    goal: ref(1, "NYC food and experiences"),
    kept: 3,
    archived: 0,
    folded: 1,
    scores: [86, 72, 64],
    top_labels: ["date night", "with friends"],
    overview: "Where to eat and how to get in.",
    brief_state: "fresh",
    brief_at: "2026-10-23T14:00:00Z",
    freshness: { posts: 3, in_brief: 3 },
    labels: [
      { label: "date night", count: 2 },
      { label: "pizza", count: 1 },
    ],
    brief: {
      overview: "Where to eat and how to get in.",
      model: "claude-haiku-5-5",
      written_at: "2026-10-23T14:00:00Z",
      sections: [
        {
          heading: "Lucali",
          points: [
            {
              text: "Join the line by 4:45pm.",
              corroborated: true,
              cites: [
                { n: 1, item_id: 1, point: "Line up by 4:45" },
                { n: 2, item_id: 2, point: "Get there before five" },
              ],
            },
            { text: "Cash only.", corroborated: false, cites: [{ n: 3, item_id: 7, point: "Cash only" }] },
          ],
        },
      ],
      sources: [
        {
          n: 1,
          item: ref(1, "Lucali: how to get a table"),
          thumbnail_url: null,
          item_type: "place",
          covered_by: null,
          current: true,
        },
        {
          n: 2,
          item: ref(2, "Lucali in 30 seconds"),
          thumbnail_url: null,
          item_type: "place",
          covered_by: 1,
          current: true,
        },
        {
          n: 3,
          item: ref(7, "BYOB pizza in Brooklyn"),
          thumbnail_url: null,
          item_type: "place",
          covered_by: null,
          current: true,
        },
      ],
    },
    ...overrides,
  };
}

export function topicSummary(overrides: Partial<Topic> = {}): Topic {
  return {
    id: 3,
    name: "Date night",
    description: "Places for a date.",
    goal: null,
    kept: 2,
    archived: 0,
    folded: 0,
    scores: [80, 70],
    top_labels: [],
    overview: null,
    brief_state: "none",
    brief_at: null,
    ...overrides,
  };
}
