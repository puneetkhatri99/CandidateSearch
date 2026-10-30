# candidateSearch: developer guide

This guide explains how the whole project works, in plain words. It is written for a developer who knows some Python but has never seen this code.

Read it in order the first time. Later, use it as a reference.

| # | File | What you learn |
|---|---|---|
| 1 | [01-big-picture.md](01-big-picture.md) | What the app does, the key words (embedding, vector, LLM, hybrid search), and how to run it |
| 2 | [02-architecture.md](02-architecture.md) | How the folders are organised, the three layers, which code may import which |
| 3 | [03-flows.md](03-flows.md) | Step by step: what happens on login, saving a candidate, embedding, search, job matching |
| 4 | [04-backend-core.md](04-backend-core.md) | Every function in `backend/app/core/` and `backend/app/shared/` |
| 5 | [05-backend-features.md](05-backend-features.md) | Every function in each feature (`auth`, `candidates`, `jobs`, `embeddings`, `ai_usage`, `semantic_search`, ...) |
| 6 | [06-frontend.md](06-frontend.md) | How the React app is built and how it talks to the API |
| 7 | [07-coding-style.md](07-coding-style.md) | The rules every new line of code must follow, with examples |
| 8 | [08-decisions.md](08-decisions.md) | Why things are built the way they are, and which function does it |
| 9 | [09-testing-and-debugging.md](09-testing-and-debugging.md) | How tests work, how to run them, and common traps |

## Other documents

- [../RULES.md](../RULES.md): the engineering rules. They are binding. This guide explains them; RULES.md wins if the two disagree.
- [../LEARNINGS.md](../LEARNINGS.md): a dated log of surprises, bugs and decisions. Add an entry when you learn something non-obvious.
- [../../README.md](../../README.md): setup commands.

## A 60-second summary

1. Candidates are added through a public form or by staff. Each candidate gets a **search document**: their profile as plain text, with name, email, phone and links removed.
2. A background task sends that text to OpenAI and stores the answer, a list of 1,536 numbers called an **embedding**, in Postgres (pgvector).
3. A recruiter types a search like "fastapi developer in noida, 5 years". The search text is turned into an embedding too.
4. The app finds the 20 closest candidates in two ways at once, by meaning (embeddings) and by keywords (Postgres full-text search), and merges the two lists.
5. An LLM (`gpt-5.4-mini`) judges each of the 20 on skills, location, experience and pay. Our code, not the LLM, turns those judgements into an order.
6. Hard filters (min years, skills, city, country, source) split the ranked list into "perfect matches" and "filtered out".
7. The same pipeline matches candidates to a saved job.
8. Every paid AI call is checked against a spending limit and recorded.

## Keeping this guide true

When you change how something works, update the matching page here in the same change. Function names are the stable reference; line numbers are not used on purpose, because they drift.
