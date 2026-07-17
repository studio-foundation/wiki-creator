# Branch protection on `main`

The PR-based workflow is convention, not enforcement: nothing on the server
stops a direct push to `main` or a merge on red CI (STU-581). The rule below
lives in GitHub settings, not in the repo — it cannot be committed as a file,
so it has to be applied once by an admin. This rule makes the PR + green-CI
requirement binding. `.github/CODEOWNERS` records ownership, but code-owner
review only *gates* a merge once required approvals ≥ 1 — see the note under
"Settings to apply".

## Settings to apply

Settings → Rules → Rulesets → **New branch ruleset** (or Settings → Branches →
Add classic branch protection rule), targeting `main`:

- **Require a pull request before merging**
  - Required approvals: `0`. A solo maintainer cannot approve their own PR, so
    `1` would make every PR unmergeable. At `0`, code-owner review does **not**
    block a merge — CODEOWNERS records ownership, and this gate only starts
    binding when a second maintainer exists and approvals are raised to `1`.
  - Require review from Code Owners: on (inert until approvals ≥ 1, per above)
- **Require status checks to pass before merging**
  - Require branches to be up to date before merging: on
  - Required check: **`test`** — the job id in `.github/workflows/ci.yml`
- **Do not allow bypassing the above settings** (classic: *Include
  administrators*) — without this, the sole admin can still push straight to
  `main`, which is exactly acceptance criterion 3.
- Block force pushes and deletions on `main` (both on by default in rulesets).

## Apply via CLI (alternative to the UI)

`gh api`'s `-f`/`-F` flags cannot build an array of rule objects, so pass the
body as JSON on stdin. An empty `bypass_actors` applies the ruleset to admins
too.

```bash
gh api --method POST repos/studio-foundation/wiki-creator/rulesets --input - <<'JSON'
{
  "name": "main protection",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": { "ref_name": { "include": ["refs/heads/main"], "exclude": [] } },
  "rules": [
    { "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "require_code_owner_review": true,
        "dismiss_stale_reviews_on_push": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false
      } },
    { "type": "non_fast_forward" },
    { "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [ { "context": "test" } ]
      } }
  ]
}
JSON
```

## Verify

After enabling, a direct push must be rejected:

```bash
git checkout main && git commit --allow-empty -m 'protection probe' && git push
# expected: remote rejected — protected branch hook declined
```

Reset the probe: `git reset --hard @{u}`.
