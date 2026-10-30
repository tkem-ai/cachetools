---
applyTo: ".github/copilot-review.md"
---

# Code Review Format

- Reviews amend `.github/copilot-review.md` in place (header: date, commit, CI status,
  coverage, one *Verified* paragraph); never new files, dated sections or per-commit
  change summaries (git history is the record).
- Findings are tables ordered High, Medium, Low, Info with columns
  `# | Priority | Location | Finding`; renumber after changes; cross-reference as
  "Code #3". Resolved issues are removed, never marked resolved.
- One or two sentences per row, numbers only where they decide something, current
  snapshot only (no comparisons with earlier releases).
- The `CHANGELOG.rst` section lists changes to tag "(breaking change)", "(potentially
  breaking change)" or "(broken since vX.Y.Z)".
- Settled matters go to *Maintainer Decisions* in `.github/copilot-instructions.md`,
  not into findings. A review changes nothing; fix only when asked.
