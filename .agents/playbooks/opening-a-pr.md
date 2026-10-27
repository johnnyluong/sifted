---
extends: opening-a-pr
when: Every playbook ends here; inertia.io has no git, so it hands the change to /finish instead of opening a PR.
---

- **Replace** "Work from a git worktree off main.": There is no git repository, so no worktree, commit or PR. List the live agents and stop every one that still writes files, then run `/finish` and stop. It replaces Commits, PRs, Titles, Descriptions, Forge, Built-in PR tool, Size and stacks, Readiness and Babysit; its report takes the place of the PR description.
