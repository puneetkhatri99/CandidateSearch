# Candidate priority: skills and budget first

Approved by the user on 2026-11-02. The flow is described in [guide/03-flows.md](../guide/03-flows.md), section 6.

## Rules
- **Primary:** skills, and location too unless the role is remote. Budget is a hard filter.
- **Secondary:** experience. For remote roles, the wanted country breaks ties.
- **Budget:** a stated salary in the same currency that is above the budget is filtered out. No stated salary passes. Another currency passes, with a "can't compare" note.
- **Where the budget comes from:** the job's `salary_max`, or the search text ("under 25 LPA"). A budget without a currency is ignored.
- **Who decides:** code checks pay. The AI never sees pay.

## Acceptance criteria
1. A job with `salary_max` puts a candidate expecting more (same currency) in "Filtered out" with `max_salary`, and keeps one expecting exactly `salary_max`.
2. A search "... under 25 LPA" filters the same way, and the first progress step says "budget up to 2,500,000 INR".
3. No expected salary, or a salary in another currency, is never filtered by the budget.
4. The SQL prefilter and the Python split agree on every budget case.
5. For an office/hybrid role, a location miss ranks below a location hit even with a better skills band.
6. For a remote role, location never lowers the fit; between otherwise equal people, the wanted country comes first.
7. Neither the ranking prompt nor the job brief contains pay.
