# Saved searches and a search that stays

Approved by the user on 2026-11-02. The flow is described in [guide/03-flows.md](../guide/03-flows.md#saved-searches-reopening-without-paying-again).

## Decisions
- **What is saved:** every search by meaning, with its results, for its owner only.
- **How long:** the newest 50 un-starred searches per person are kept; starred ones stay until deleted.
- **What stays on screen:** the current search, until Clear, emptying the box, or a new Search, including after a refresh or in a new tab.

## Acceptance criteria
1. Search, open a profile, then "← Back to candidates" or the browser's Back: the same results, with no new AI call.
2. Refresh, or reopen Candidates in a new tab: the same results, with no new AI call.
3. Only Clear, emptying the search box, or a new Search replaces them.
4. Settings → Saved searches lists only your own searches, starred first. Open shows the saved results for free, Star keeps one past the 50 limit, and Delete removes it.
5. A deleted candidate disappears from every saved search, along with the AI's notes about them.
6. Another person's saved search answers 404.
