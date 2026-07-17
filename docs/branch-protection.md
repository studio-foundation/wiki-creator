# Branch protection on `main`

The PR-based workflow is convention, not enforcement: nothing on the server
stops a direct push to `main` or a merge on red CI (STU-581). The rule below
lives in GitHub settings, not in the repo — it cannot be committed as a file,
so it has to be applied once by an admin. `.github/CODEOWNERS` supplies the
review mechanism; this rule makes it binding.

## Settings to apply

Settings → Rules → Rulesets → **New branch ruleset** (or Settings → Branches →
Add classic branch protection rule), targeting `main`:

- **Require a pull request before merging**
  - Required approvals: `0` (single-maintainer repo; CODEOWNERS still records
    ownership and can be raised to `1` later)
  - Require review from Code Owners: on
- **Require status checks to pass before merging**
  - Require branches to be up to date before merging: on
  - Required check: **`test`** — the job id in `.github/workflows/ci.yml`
- **Do not allow bypassing the above settings** (classic: *Include
  administrators*) — without this, the sole admin can still push straight to
  `main`, which is exactly acceptance criterion 3.
- Block force pushes and deletions on `main` (both on by default in rulesets).

## Apply via CLI (alternative to the UI)

```bash
gh api --method POST repos/studio-foundation/wiki-creator/rulesets \
  -f name='main protection' \
  -f target='branch' \
  -f enforcement='active' \
  -F 'conditions[ref_name][include][]=refs/heads/main' \
  -F 'conditions[ref_name][exclude][]=' \
  -F 'rules[][type]=pull_request' \
  -F 'rules[][type]=non_fast_forward' \
  -F 'rules[][type]=required_status_checks' \
  -F 'rules[][parameters][required_status_checks][][context]=test' \
  -F 'rules[][parameters][strict_required_status_checks_policy]=true'
```

Leave the ruleset **bypass list empty** so it applies to admins too.

## Verify

After enabling, a direct push must be rejected:

```bash
git checkout main && git commit --allow-empty -m 'protection probe' && git push
# expected: remote rejected — protected branch hook declined
```

Reset the probe: `git reset --hard @{u}`.
