# Screenshots

Put the PNGs in **this directory**, using exactly the filenames below. The README and
DOCUMENTATION already reference these paths, so the images appear as soon as the files
exist — no Markdown editing needed.

On Windows: `Win + Shift + S` to snip, paste into Paint, save as PNG. Maximise the
terminal and bump the font size before capturing a CLI shot.

| # | Filename | What to capture | Run this first |
|---|---|---|---|
| 1 | `01-web-ui-review.png` | Web UI, **Review** tab, findings + scores visible | `python review.py serve --mock` then **Run** |
| 2 | `02-web-ui-pair.png` | Web UI, **Pair** tab: design flaws + a generated test | same server, switch tab, **Run** |
| 3 | `03-web-ui-snippet.png` | Web UI, **Snippet 3+1** tab with `snippet.go` | load `snippet.go`, **Run** |
| 4 | `04-cli-scan.png` | Measured metrics and static findings in the terminal | `python review.py scan samples` |
| 5 | `05-cli-demo.png` | All three challenges running | `python review.py demo --mock` |
| 6 | `06-cli-gate-fail.png` | The CI gate rejecting the change | `python review.py review samples --mock --gate` |
| 7 | `07-report-markdown.png` | `out\01_review.md` in VS Code preview (`Ctrl+Shift+V`) | `python review.py demo --mock` |
| 8 | `08-tests-pass.png` | `Ran 51 tests ... OK` | `python -m unittest discover -s tests -t . -v` |
| 9 | `09-live-model-review.png` | A **live** review: header shows a live provider | set `LLM_API_KEY`, then `python review.py review samples\routing.go` |
| 10 | `10-github-action.png` | The workflow run or the PR comment | push a branch and open a PR |

**If short on time:** 1, 3, 4 and 6 are the ones embedded in the README. Number 9 is the
most persuasive — it shows findings the static pass cannot produce.
