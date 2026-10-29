export type RoadmapTag = "capture" | "extract" | "judge" | "organize" | "act" | "cost" | "deferred";

export const ROADMAP_TAGS: Record<RoadmapTag, { label: string; meaning: string }> = {
  capture: { label: "Capture", meaning: "gets a post into Sift with the least effort." },
  extract: { label: "Extract", meaning: "pulls the useful part out of it." },
  judge: { label: "Judge", meaning: "weighs it against your goals and values." },
  organize: { label: "Organize", meaning: "puts it next to related posts." },
  act: { label: "Act", meaning: "gets you to do the thing." },
  cost: { label: "Cost", meaning: "changes what Sift spends on AI calls." },
  deferred: { label: "Deferred", meaning: "planned, but waiting on something else first." },
};

export type Progress = "built" | "next" | "later";

export type RoadmapEntry = {
  title: string;
  body: string;
  tags: readonly RoadmapTag[];
  yours?: boolean;
};

export type RoadmapStage = {
  when: string;
  progress: Progress;
  title: string;
  intro: string;
  entries: readonly RoadmapEntry[];
};

export const ROADMAP_UPDATED = "Oct 27, 2026";

export const ROADMAP_STAGES: readonly RoadmapStage[] = [
  {
    when: "Shipped",
    progress: "built",
    title: "The loop works end to end",
    intro: "On your laptop, reached from your phone over Tailscale.",
    entries: [
      {
        title: "Paste or share a link",
        body: "From Instagram or Threads, in the web app or from the iPhone share sheet.",
        tags: ["capture"],
      },
      {
        title: "Reads the post",
        body: "Video transcript, frames, caption and carousel slides.",
        tags: ["extract"],
      },
      {
        title: "Keeps or archives",
        body: "Every post is scored against your goals, and your overrides teach it.",
        tags: ["judge"],
      },
      {
        title: "Goals and values from real questions",
        body: "A few questions about why you save things. Claude drafts your goals and values, and you edit them before they count.",
        tags: ["judge"],
        yours: true,
      },
      {
        title: "Guard against instructions hidden in posts",
        body: "Captions and transcripts are read as data, never as orders, so a post cannot talk its way into Kept.",
        tags: ["judge"],
      },
      {
        title: "Topics and briefs",
        body: "Kept posts are grouped by subject, each with a brief. Drag a post onto a topic to move it.",
        tags: ["organize"],
        yours: true,
      },
      {
        title: "Weekly digest",
        body: "The top three to act on. Mark one done and the next takes its place.",
        tags: ["act"],
      },
      {
        title: "Import",
        body: "Posts you saved on Instagram before Sift, from Instagram's download of your data.",
        tags: ["capture"],
      },
    ],
  },
  {
    when: "Just built, Oct 27",
    progress: "built",
    title: "Keeps that explain themselves",
    intro:
      "A post you keep against Sift's call is the clearest sign its picture of your goals is off. Now it learns why.",
    entries: [
      {
        title: "Say why you kept it",
        body: "Pick the goal it serves, or none of them, and add a note. Scoring sees the reason, and Redo setup can widen a goal or propose a new one from it.",
        tags: ["judge"],
      },
      {
        title: "Whole Threads threads",
        body: "Every post of a thread is read with its photos, whichever post you share. One video is watched; any others are read from their cover.",
        tags: ["extract"],
        yours: true,
      },
      {
        title: "Import reads Instagram only",
        body: "Threads has no way to download only your saved posts, so share or paste those instead.",
        tags: ["capture"],
      },
      {
        title: "Wishlist",
        body: "Things you want to buy get their own shelf even when they serve no goal, and two come back in each digest. Bought marks one done.",
        tags: ["judge", "act"],
        yours: true,
      },
    ],
  },
  {
    when: "Next",
    progress: "next",
    title: "Take a post to your AI",
    intro:
      "Acting on a post often starts with talking it through in Claude or ChatGPT, so a post should leave Sift ready to paste.",
    entries: [
      {
        title: "Copy for AI",
        body: "One button on a post copies everything Sift has on it as one block: the link and author, the goal it serves and why you kept it, the summary and next step, then the caption, transcript and slide text, marked as the post's own words. The summary stays short for lists and the digest. The copy is built from what Sift already saved, so it costs no AI calls.",
        tags: ["act"],
        yours: true,
      },
    ],
  },
  {
    when: "Then",
    progress: "next",
    title: "Judge better",
    intro:
      "New goals only help if they reach the posts you already saved, and every correction should sharpen the next verdict.",
    entries: [
      {
        title: "Re-judge saved posts when goals change",
        body: "After a new setup, score what you already kept and archived against the new goals, so old verdicts do not linger. One small AI call per post.",
        tags: ["judge", "cost"],
      },
      {
        title: "Topic moves teach scoring",
        body: "Moving a post between topics becomes a correction, the way Keep and Archive overrides already are.",
        tags: ["judge"],
        yours: true,
      },
      {
        title: "Friends or a date",
        body: "For New York food and experiences, tell spots for a group from spots for a date.",
        tags: ["organize"],
        yours: true,
      },
    ],
  },
  {
    when: "Then",
    progress: "later",
    title: "Read more, spend less",
    intro: "With judgment in good shape, widen what Sift can read and lower the cost per post before volume grows.",
    entries: [
      {
        title: "Cheaper carousels",
        body: "A carousel costs about $0.055 to read against $0.02 for a reel, mostly from copying slide text word for word.",
        tags: ["extract", "cost"],
      },
    ],
  },
  {
    when: "Then",
    progress: "later",
    title: "Telegram bot",
    intro: "The share sheet already covers sending from your phone, so the bot waits until here.",
    entries: [
      {
        title: "Share to a chat, get the verdict back",
        body: "The verdict comes back with Keep and Archive buttons, and the digest arrives in the chat. Part of the original spec.",
        tags: ["capture", "act", "deferred"],
      },
    ],
  },
  {
    when: "Later",
    progress: "later",
    title: "From a saved post to a plan",
    intro: "The biggest step toward acting on what you save. It needs its own design pass.",
    entries: [
      {
        title: "Plans with friends",
        body: "Turn an event into a calendar invite, a poll for a time, or a time when everyone is free, found from their calendars. A bit like Partiful.",
        tags: ["act"],
        yours: true,
      },
    ],
  },
  {
    when: "Later",
    progress: "later",
    title: "Beyond one person and one laptop",
    intro: "These change what Sift is, so they come last, once the loop is worth sharing.",
    entries: [
      {
        title: "Collections that grow with you",
        body: "Claude builds tabs for life projects, such as a wedding, date ideas or fitness, maybe reachable from any AI chat through an MCP server.",
        tags: ["organize"],
        yours: true,
      },
      {
        title: "iPhone app with a share extension",
        body: "Sift in the share sheet without a Shortcut. Needs Xcode, and a $99 a year developer account for anything past your own phone.",
        tags: ["capture"],
      },
      {
        title: "Friends testing",
        body: "Tailscale invites, Google sign-in and separate data per person. The limits are one Instagram account doing all the fetching, AI costs on your key, and a laptop that has to stay awake.",
        tags: ["cost", "deferred"],
      },
    ],
  },
];

export const ROADMAP_SET_ASIDE =
  "Agent Reach does not remove the Keychain password prompt. It wraps tools like yt-dlp, which Sift already uses, does not list Instagram or Threads, and still needs your browser session. Checked Oct 22, 2026.";
