# auto-reviewer

Reviews GitHub PRs that are assigned to you, with Claude Code in headless mode (`claude -p`).

- **accept**: approves the PR. No body, no comments.
- **comment** / **needs_changes**: posts one review with inline code comments only.

Draft PRs and PRs with failed CI are skipped. When CI is pending, the tool tries again on the next run. It does not review your own PRs, and it reviews each head commit one time only.

## Requirements
- macOS, [`uv`](https://docs.astral.sh/uv/), `gh` (logged in), `claude` (logged in)

## Setup
```bash
cp config.example.yaml config.yaml   # edit allow list, model, auth
uv sync
uv run python -m auto_reviewer --dry-run
```
Look at the output in `~/Library/Logs/auto-reviewer.log`. When it is correct, set `dry_run: false`.

## How Claude reviews
Edit `review-guide.md`. Claude gets it as the system prompt. To use a different guide for a repo, add it to `repo_guides` in `config.yaml`.

## Claude account
- `claude.auth: login`: uses your current `claude` login.
- `claude.auth: token`: uses a long-lived token from the Keychain, for example for an Enterprise account:
  ```bash
  claude setup-token   # log in with the account you want
  security add-generic-password -a "$USER" -s auto-reviewer-claude-token -w <token>
  ```

## Run every 2 minutes
```bash
scripts/install-launchd.sh
```
To stop: `launchctl bootout gui/$(id -u)/com.moonquddus.auto-reviewer`

## Tests
```bash
uv run pytest
```
