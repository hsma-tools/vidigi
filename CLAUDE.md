# Personality

- No sycophancy. Value honest, objective feedback over agreeableness — push back on weak ideas, biases, or poorly-thought-out requests, and explain better alternatives, while staying friendly.

# Git commit workflow

- Never run `git commit` unless explicitly asked that turn. Drafting/staging is fine anytime.
- Every commit needs a `Co-Authored-By: Claude <model-name> <noreply@anthropic.com>` trailer (via HEREDOC), one per contributing model.

# Fix scope

- If a bug report floats a bigger speculative fix alongside a smaller one matching existing patterns, don't default to the bigger one — surface the choice explicitly before planning.
- Fold in same-sized adjacent bugs found in passing (flag in summary); a structurally bigger one needs an explicit scope question first.

# Breaking changes

- vidigi is post-1.0: deprecation period required if breaking changes are occurring and functionality should only be fully removed/dramatically altered on major version bump.
- When removing/renaming public API, make failures legible: if it'd otherwise be absorbed by `**kwargs` and surface as an unrelated error, add an explicit check naming the replacement.
- Breaking = anything that changes results without the caller changing code, not just signature changes. Each needs a `**BREAKING:**` HISTORY.md bullet plus a line in that version's `### ⚠️ Breaking changes` summary (create if absent).

# Testing

- Don't monkeypatch core objects (e.g. `pd.DataFrame`) to cover a trivial/unreachable branch — skip it.
- For subtle-bug fixes (wrong direction, silent no-op, wrong ordering), prove the new test catches the regression by reverting the fix and confirming it fails, then restoring. "Tests pass" alone isn't proof.
- Reverting proves a test catches *that* regression; it doesn't prove the test pins the behaviour. Where reverting is tautological — a test asserting the DeprecationWarning a fix just added, say — mutate the code *towards* the plausible wrong behaviour instead and confirm the test fails.
- Assert whole mappings, not two sampled entries, when checking positional or derived data (icon assignment, rank→position, ordered lists). Spot checks pass by coincidence: reversing icon assignment left positions 0 and 3 unchanged, so a test asserting exactly those two entities passed against reversed output. Caught only by mutating.
- When a test's expected values are hand-computed, verify them against a scratch run *before* writing the assertion, then let the test encode the confirmed result. Several plausible-looking expectations here were wrong about existing behaviour, not about the code being wrong.
- Before mutating a file to prove a test catches a regression, `git add` the real (pre-mutation) change first, or apply the mutation as an `Edit` you can `Edit` back rather than a raw file overwrite. Reverting a mutation with `git checkout -- <file>`/`git restore <file>` discards *everything* uncommitted in that file, not just the mutation — it has already wiped a real, un-staged fix once. Prefer reverting via the same tool that applied the mutation.

# Deferred work

- Structural fixes that get deferred need a handover: context, repro, proposed design/trade-offs, implementation notes, testing guidance.
- `pending_fixes.md` is the running list of behaviours that look wrong but are deliberately unchanged because fixing them would alter output for callers who change nothing. Check it before "fixing" something that looks obviously broken — it may already be a recorded decision. Each entry needs the repro, why it's ambiguous, blast radius, and the test that pins current behaviour so the assertion can be updated alongside any fix.
- Where current behaviour is pinned rather than fixed, say so in the test itself with a comment, not just in `pending_fixes.md` — the next person to read the assertion needs to know it encodes a deferred decision rather than a verified expectation.

# Reporting

- State uncertainty plainly — distinguish directly-verified from inferred (e.g. "confirmed via code inspection, but couldn't trigger through the public API").
- Named external citations (papers, APIs, specs) need a primary-source check before landing in code/docs — a recalled name or detail can be subtly wrong even when the surrounding content is right.

# Third-party reuse

- Reusing external code, data, or test fixtures — even a small amount — needs a licence check and attribution in THIRD_PARTY_LICENCES.md as part of the same change, proposed proactively rather than waiting to be asked.

# Plotting

- Prefer plotly.go over plotly express for plotting outside of the main animation function.

# Example notebooks

- Lives at `examples/<name>/index.ipynb`. Front matter markdown cell: `title`, `toc: true`, `execute: {enabled: true}`, `image:`.
- `image:` is expected in practice, not truly optional -- it's the listing grid's thumbnail. This will need to be a manually generated gif, so remind the author to do so if a brand new notebook is created.
- Must be wired into either `examples/examples.qmd` or `examples/feature_breakdowns.qmd`  (both the `listing` metadata's `contents` list and the matching `:::{#id}:::` div) or it's invisible.
- Committed with real executed outputs. After editing code cells, run `python -m jupyter nbconvert --to notebook --execute --inplace <path>` from the notebook's own directory and check for error outputs.
- Don't fabricate numbers in prose — derive by running the scenario. Re-run and check any notebook whose narrated numbers a core-code change could have shifted.
- Revert re-execution diffs that are pure timestamp/widget-ID/execution-count churn with no value change.
- Hand-editing prose in an already-executed notebook (no re-run needed): edit `source` as a JSON list of lines (each ending `\n` except the last), matching existing style, for a line-granular diff.

# HISTORY.md

- Every user-facing change needs an entry — check as part of the task, don't wait to be asked.
- Add to the top section if it's unreleased; only start a new version header (bumping `pyproject.toml` to match) for the first change since the last release.
- Version headers are a single `#` with a bare number — `# 1.4.0`, not `## v1.4.0`.
- One top-level bullet per feature/fix, nested (4-space) sub-bullets for specifics.
- Versions with breaking changes open with `### ⚠️ Breaking changes` (scannable one-liners) then `### Notes` for full bullets — see 1.4.0. Otherwise either a plain flat list (1.3.1) or `### Enhancements` / `### Fixes` / `### New examples` groupings (1.3.0), whichever suits the release.
- Each breaking bullet under `### Notes` opens with `**BREAKING:**`, and says what happens to callers on the defaults — usually "nothing changes", which is the reassurance most readers need.
- Releases that meaningfully add test coverage get a `### Testing` section: a one-line before/after test count, then a few bullets on which areas gained coverage and what class of bug that guards against. High level only — users don't need individual test names, just confidence that the tested surface grew.
- Docs/example-only changes to already-documented features usually don't need a new bullet — refine existing wording instead.
