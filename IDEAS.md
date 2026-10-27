# Ideas for after V1

Notes from testing the prototype, 2026-10-22. Nothing here is built yet.

## Onboarding: ask about saving habits, not abstract values

The values text used for scoring should come from questions about real behavior:

- What have been the recent reasons or patterns behind what you save?
- Why do you think you rarely go back to what you saved?

The answers become the scoring context, in place of a free-form "values" box.

## Categories that grow with the user

- The AI builds categories (tabs, topics, areas) from what the user saves: a wedding, date ideas, fitness.
- Once categories are established, the user can drag an item from one category to another. Each move is a correction that improves future scoring, the same way Keep and Archive overrides do now.
- Possibly expose categories through an MCP server, so an AI in a chat can create and organize them. It should call the same service layer as `/api/`.

## My own use cases (why I started building this)

- **Marketing my web app.** I need to start marketing it and don't know where to begin, so I'm trying everything. Recent saves cover SEO, organic ad formats, Google Search Console, and GEO (generative engine optimization).
- **New York food and experiences.** Restaurants, food spots, and novel experiences I want to try. Each one is either for friends or for a date with my partner, and the AI should help tell the two apart.

## Possible pivot: from a saved post to a plan with friends

When a saved post is about an event or experience, Sift could turn it into a plan, a bit like Partiful. That replaces sending the reel and starting a new group chat.

- Create a calendar event from the post and invite people in a few taps.
- Or poll the group for when they're available.
- Better still, each person grants read-only calendar access (the lowest level), and the app finds when everyone is free at the same time.

## Avoiding the Keychain password prompt

Agent Reach (checked 2026-10-22) does not help. It wraps tools such as yt-dlp (which Sift already uses) to read platforms without paid APIs. Its commonly listed platforms do not include Instagram or Threads, and logged-in platforms still need your browser session, so it would not remove the password prompt.
