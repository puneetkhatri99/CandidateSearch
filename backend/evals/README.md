# Search evaluation (golden set)

Measures how well **search by meaning** ranks candidates, and checks that it treats groups
fairly. Required by RULES section 8 (run before merging any prompt or model change) and
section 9 (golden set, NDCG@10, precision@k, bias checks).

Run every command from `backend/`.

## Files

- `golden_set.json`: the searches and the hand-given grades. Committed to git, so it may
  only name **synthetic seed profiles** (`seed.NNNNN@example.com`, source `synthetic`).
  `eval-label` enforces this.
- `results/`: one `.json` and `.md` report per run. Commit the report that goes with a
  prompt or model change, so reviewers can compare it with the previous one.

The grades refer to profiles created by `python -m scripts.seed_candidates --count 1000`
with the default seed. They only mean something on a database seeded that way.

## 1. Grade (a person, never the AI)

For each search in `golden_set.json`, read each candidate's `profile` line and replace
`"grade": null` with:

| Grade | Meaning |
|---|---|
| 3 | Perfect fit: you would contact them first |
| 2 | Good fit: worth contacting |
| 1 | Weak: related, but missing something important |
| 0 | Not relevant |

Grade what the search asks for and nothing else (the same rule as prompt `rank_v7`). If the
search names a city, a nearby commutable city is still a fit. A search is only scored once
**every** candidate in it has a grade; partly graded searches are skipped and listed in the
report.

The candidates come from the hybrid fetch (meaning + keywords) **without** the AI ranking,
and in shuffled order, so the grades don't echo the system being tested.

## 2. Run

```
python -m app.cli eval-search
```

This runs every graded search for real: about **$0.05 per search**, metered and capped by the
AI budget like any search. Repeat runs within 10 minutes reuse cached rankings. Nothing is
audited or saved as a search history entry.

## 3. Read the report

- **NDCG@10** (0 to 1): how close the top 10 is to the best possible order of the graded
  people. **Precision@5**: share of the top 5 graded 2 or 3. A change that lowers either
  needs an explicit justification (RULES section 9).
- **Ungraded in top 10**: people the search returned that nobody graded. They count as 0.
  If this grows, add them: `eval-label` can't extend a case, so grade them by adding entries
  to that case by hand (copy the email from the report).
- **Ranked by `search`** means the AI ranking didn't run (budget used up, no key, provider
  error). That run doesn't measure the AI; fix the cause and run again.
- **Fairness**: of the people graded 2 or 3, the share of each group (country, experience
  band) that reached the top 10. A group with at least 5 such people found at under 80% of
  the best group's rate (the four-fifths rule) is flagged. Experience band stands in for age,
  which isn't collected. Small samples are noisy: treat a flag as a reason to look, not as
  proof.
- Gender, age and ethnicity aren't collected, so they can't be checked here. If the tool is
  used for hiring in New York City, Local Law 144 requires an independent bias audit; this
  report doesn't replace it.

## Adding a search

```
python -m app.cli eval-label --id short-unique-name --query "what a recruiter would type"
```

This adds the 20 best hybrid matches (synthetic only) with empty grades. It costs one query
embedding (about $0.000001).
