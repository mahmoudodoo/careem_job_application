# Smart Code Reviewer report

| | |
|---|---|
| Reviewed | `samples/eta_service.go`, `samples/routing.go` |
| Provider | `mock` |
| Model | `offline-heuristics` |
| Elapsed | 0.0s |

> Offline mock mode: findings come from the deterministic static pass only. No model was called.

**Verdict: REQUEST CHANGES**

Static review of 2 file(s) (188 LOC): samples/eta_service.go, samples/routing.go. Found 1 blocker(s), 6 major, 8 minor and 5 nit issue(s). Generated in offline mock mode - deterministic static analysis only, no model call; run without --mock for reasoning about intent, root causes and suggested fixes.

## Scores

| Dimension | Score |
|---|---|
| Readability | 3/5 `###..` |
| Structure | 4/5 `####.` |
| Maintainability | 1/5 `#....` |
| Test Readiness | 4/5 `####.` |

## Findings

20 total - 1 BLOCKER, 6 MAJOR, 8 minor, 5 nit

### 1. [BLOCKER] ignored-error - samples/eta_service.go:44

Return value discarded with `_` - a failure here is silent.

**Fix:** Handle the error, or comment why discarding it is safe.

<sub>category: reliability | confidence: high</sub>

### 2. [MAJOR] missing-context - samples/eta_service.go:33 in `GetTrafficFactor`

`GetTrafficFactor` looks like an I/O call but takes no context.Context, so callers cannot set a deadline or cancel it.

**Fix:** Make `ctx context.Context` the first parameter and honour it.

<sub>category: reliability | confidence: high</sub>

### 3. [MAJOR] long-function - samples/eta_service.go:48 in `ComputeETA`

`ComputeETA` is 61 lines (limit 60) - it does several jobs at once.

**Fix:** Split the distinct steps into named helpers so each can be tested alone.

<sub>category: structure | confidence: high</sub>

### 4. [MAJOR] deep-nesting - samples/eta_service.go:48 in `ComputeETA`

`ComputeETA` nests 5 levels deep (limit 4).

**Fix:** Use early returns / guard clauses to flatten the happy path.

<sub>category: readability | confidence: high</sub>

### 5. [MAJOR] high-complexity - samples/eta_service.go:48 in `ComputeETA`

`ComputeETA` has cyclomatic complexity 18 (limit 12); that is 18 paths to cover in tests.

**Fix:** Extract branches into helpers or replace the chain with a lookup table.

<sub>category: maintainability | confidence: high</sub>

### 6. [MAJOR] blocking-sleep - samples/eta_service.go:89

Blocking sleep on a request path stalls the goroutine/thread.

**Fix:** Use a context deadline, a ticker, or a backoff helper instead.

<sub>category: reliability | confidence: high</sub>

### 7. [MAJOR] panic-in-library - samples/eta_service.go:104

panic() in service code takes down the whole process.

**Fix:** Return an error and let the caller decide.

<sub>category: reliability | confidence: high</sub>

### 8. [minor] magic-number - samples/routing.go:62

Unexplained literal `111.32` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 9. [minor] magic-number - samples/routing.go:63

Unexplained literal `111.32` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 10. [minor] magic-number - samples/eta_service.go:66

Unexplained literal `1320` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 11. [minor] magic-number - samples/eta_service.go:70

Unexplained literal `480` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 12. [minor] magic-number - samples/eta_service.go:72

Unexplained literal `120` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 13. [minor] magic-number - samples/eta_service.go:76

Unexplained literal `1800` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 14. [minor] magic-number - samples/eta_service.go:79

Unexplained literal `900` - the reader cannot tell what it means.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 15. [minor] tracked-todo - samples/eta_service.go:97

TODO comment left in code with no linked ticket.

**Fix:** Link a ticket ID or resolve before merge.

<sub>category: maintainability | confidence: medium</sub>

### 16. [nit] missing-doc-comment - samples/routing.go:26 in `PlanRoute`

Exported `PlanRoute` has no doc comment.

**Fix:** Add a `// PlanRoute ...` comment describing the contract.

<sub>category: readability | confidence: medium</sub>

### 17. [nit] missing-doc-comment - samples/eta_service.go:48 in `ComputeETA`

Exported `ComputeETA` has no doc comment.

**Fix:** Add a `// ComputeETA ...` comment describing the contract.

<sub>category: readability | confidence: medium</sub>

### 18. [nit] missing-doc-comment - samples/routing.go:67 in `SortByProximity`

Exported `SortByProximity` has no doc comment.

**Fix:** Add a `// SortByProximity ...` comment describing the contract.

<sub>category: readability | confidence: medium</sub>

### 19. [nit] magic-number-repeated - samples/eta_service.go:82

8 further `magic_number` occurrence(s) in this file (L82, L83, L85, L88, L89, L95, L137, L138). Reported once so they do not bury the rest.

**Fix:** Promote it to a named constant or a config field.

<sub>category: maintainability | confidence: medium</sub>

### 20. [nit] long-line - samples/eta_service.go:110

Line is 171 characters (limit 120).

**Fix:** Break the expression across lines or extract a named local.

<sub>category: readability | confidence: medium</sub>

## What the author got right

- samples/eta_service.go: `GetTrafficFactor`, `haversine` stay small enough to hold in your head, which is what makes them cheap to unit test.
- samples/eta_service.go: exported symbols such as `GetTrafficFactor` carry doc comments, so the package reads correctly in godoc.
- samples/routing.go: `dist`, `SortByProximity` stay small enough to hold in your head, which is what makes them cheap to unit test.

## Still needs a human

- Does the change keep the ETA contract intact for every vertical it touches?
- Is every new I/O path covered by a context deadline and a retry policy?
- Which of these findings are pre-existing, and which did this change introduce?

## CI gate

FAIL - policy violations:
- 1 blocker finding(s); policy allows 0.
- 6 major finding(s); policy allows 3.

---

<sub>Generated by careem-ai-reviewer.</sub>
