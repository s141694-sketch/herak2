# Baseline form — before using Harak

This form measures two things in the organization's current way of working, before Harak:

1. **Review rounds** per training program, until its approval.
2. **Time from the first draft to approval.**

After the pilot, Harak measures the same two things from its own records (the `pilot_metrics` command, decision D86). The definitions below are the tool's own, word for word, so the two results compare. Success measures: spec 1.6.

## 1. Definitions

| Term | Definition |
|---|---|
| **First draft** | The day the program was opened for work: the day its team was given it and its file was made. In Harak: the day the program was created, which creates its first version before anything is written in it |
| **Review round** | A submission for review that ended with a decision: **returned for changes** or **approved**. A submission withdrawn before any decision is not a round. A program approved at its first submission had one round |
| **Approval** | The program's first final approval. A later revision (a periodic review) is another cycle, not counted here |
| **Days** | The time from the first draft to approval, in days. Harak counts it from the hours, divided by 24, to one decimal. On this form: the difference between the two dates in days; the two ways differ by less than a day for one program |
| **Work days** | The work days after the day of the first draft, up to and including the day of approval. Work days are the organization's weekly work days (for example Sunday to Thursday). **Public holidays are not taken out:** Harak counts a holiday that falls on a work day as a work day, so count it the same way |

## 2. Which programs

- **Every** program approved in the last 12 months, or the last 10 approved if there are more. No picking of easy or hard ones.
- Programs not approved yet go in the table too, with their rounds so far, and stay out of the summary.
- Where a date is not known exactly, write the closest estimate and mark "estimate" in the source column.

## 3. The table

| # | Program | First draft (date) | Approval (date) | Review rounds | Days | Work days | Source (email, minutes, file) and accuracy (exact / estimate) |
|---|---|---|---|---|---|---|---|
| 1 | | | | | | | |
| 2 | | | | | | | |
| 3 | | | | | | | |
| 4 | | | | | | | |
| 5 | | | | | | | |
| 6 | | | | | | | |
| 7 | | | | | | | |
| 8 | | | | | | | |
| 9 | | | | | | | |
| 10 | | | | | | | |

## 4. Summary

Over approved programs only, as Harak computes it:

| Measure | Value |
|---|---|
| Programs in the table / approved | |
| Review rounds: mean | |
| Review rounds: median | |
| Time to approval: median days | |
| Time to approval: median work days | |

## 5. About this form

| Item | Value |
|---|---|
| Organization | |
| Filled in by, and their role | |
| Date | |
| The organization's work days | |
| Notes (the usual review stages, who approves) | |

## 6. After the pilot

The operator runs the command on the pilot's records (runbook, section 10):

```sh
python manage.py pilot_metrics --organization <slug> --since <the pilot's first day>
```

and compares its summary with section 4.

**When comparing:** Harak does not take public holidays out of the work days. If long holidays fell in either period, say so beside the comparison.
