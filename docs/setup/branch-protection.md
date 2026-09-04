# Branch Protection Setup

GitHub branch protection rules must be configured manually in the repository settings. These cannot be set via files in the repository.

## How to Configure

Go to: **Settings → Branches → Add branch protection rule**

Configure the following for the `main` branch:

---

### Required Settings

| Setting | Value | Why |
|---------|-------|-----|
| **Branch name pattern** | `main` | Protects the main branch |
| **Require a pull request before merging** | On | Prevents direct pushes |
| **Required approving reviews** | `1` | At least one review before merge |
| **Dismiss stale pull request approvals when new commits are pushed** | On | Re-reviews if PR changes |
| **Require review from Code Owners** | On | Domain-specific PRs need domain team approval |
| **Require status checks to pass before merging** | On | CI must pass |
| **Required status checks** | `lint`, `test`, `build` | Match the job names in `.github/workflows/ci.yml` |
| **Require branches to be up to date before merging** | On | Must rebase on latest main |
| **Require conversation resolution before merging** | On | All review comments must be resolved |
| **Require linear history** | On | Squash or rebase only - no merge commits |
| **Do not allow force pushes** | On | Protects commit history |
| **Do not allow deletions** | On | Cannot delete main |
| **Restrict who can push to matching branches** | On | Only allow PR merges via GitHub UI |
| **Allow force pushes** | Off | - |
| **Allow deletions** | Off | - |

---

### Optional Additional Branch Rules

For release branches or protected tags:

| Pattern | Setting | Purpose |
|---------|---------|---------|
| `release/*` | Require 1 review + CI | Protect release branches |
| `v*` tags | Require 1 review | Protect version tags |

---

### How to Set via GitHub CLI

```bash
gh api repos/{owner}/{repo}/branches/main/protection \
  --method PUT \
  --field required_status_checks='{"strict":true,"contexts":["lint","test","build"]}' \
  --field enforce_admins=true \
  --field required_pull_request_reviews='{"required_approving_review_count":1,"dismiss_stale_reviews":true,"require_code_owner_reviews":true}' \
  --field restrictions=null
```

---

### Verification

After setup, verify by attempting a direct push to main:

```bash
git checkout main
echo "test" >> test.txt
git add test.txt && git commit -m "test: direct push attempt"
git push origin main
```

This should be **blocked** with a message like:

```
remote: error: GH006: Protected branch update failed.
remote: error: Required status check "lint" has not succeeded.
```

Clean up:

```bash
git reset HEAD~1
rm test.txt
```
