---
extends: bug-fix
when: Fixing a reported defect in inertia.io.
---

- **Before** "Reproduce it yourself on the matching surface": Run `.claude/scripts/changes.sh start` so `/finish` can see what the fix touches.
- **Replace** "Verify on the same surface. The original repro now passes.": Verification is `/finish` step 4: drive the original repro there with `verify` and quote that it now passes.
- **Replace** "Stage the commits so the failing repro lands before the fix in git history.": With no git history, show the order in the report instead: quote the repro test failing before the fix, then passing after it. See the **tdd** skill for the failing-test-first cadence when the bug has a cheap local test path.
