# ToolNet Fplus24h — Production Release / Final Acceptance

Version: Step **9.7.20**.  Deployment root: `/root/toolnet-group-publisher`. Branch: `main`.

**Release scope**: Multi-tenant Pipeline management, CTV UI, media selection, scheduler, human-operated Facebook Group publishing handoff, independent readback, alerts, reconciliation, security and performance diagnostics.

**Not implemented**: automatic Facebook Group posting, unattended verified publication, Meta Group API publishing, autonomous Facebook comment posting. A Facebook HAR file is not proof of a supported API. Do not replay cookie/token/GraphQL data or mark manually reported posts as `published`.

## Stage A — Before merge/deployment

1. Confirm `git status --short` empty and `git branch --show-current` is `main`; create a deploy snapshot tag, do not expose secrets: `git tag -a "pre-9.7.20-$(date -u +%Y%m%dT%H%M%SZ)" -m 'Pre-release snapshot'`. Tags are local until explicitly pushed.
2. Have a VERIFIED Neon backup/restore strategy. Take a manual database snapshot via Neon console; capture snapshot identifier outside Git. **Test restoring to a separate database**, never on production. Check R2 storage retention/versioning where available; R2 objects are not part of a Neon backup.
3. Check `.env`, `DATABASE_URL`, Fernet keys, R2 keys, GitHub credentials and Cloudflare tokens are never printed or committed.
4. Run Django `manage.py check`, `makemigrations --check --dry-run`, and rollback-fixture tests. For Next.js run `npm run build`. Preserve the exact installed dependency versions.
5. Keep the scheduler and alert timer configuration unchanged during initial release. There must be no new auto-posting or retry mechanism.

## Stage B — Read-only release evidence

In `/root/toolnet-group-publisher/backend`:

```bash
../.venv/bin/python manage.py publishing_release_gate --pipeline-id 698d2a9f-9264-4d06-a871-037640ce51a0 --limit 50
../.venv/bin/python manage.py publishing_operations_health --pipeline-id 698d2a9f-9264-4d06-a871-037640ce51a0 --strict
../.venv/bin/python manage.py publishing_security_audit --pipeline-id 698d2a9f-9264-4d06-a871-037640ce51a0 --strict
../.venv/bin/python manage.py publishing_performance --pipeline-id 698d2a9f-9264-4d06-a871-037640ce51a0 --repeats 3 --limit 25
../.venv/bin/python manage.py publishing_pilot --pipeline-id 698d2a9f-9264-4d06-a871-037640ce51a0 --limit 50
```

The release gate never returns `release_approved: true`. `--strict` always fails closed until **external** sign-off exists; this is deliberate. If any scan is truncated, result is blocked (increase bounded limit within supported bounds only after investigating load). An empty Pipeline cannot be certified.

## Stage C — Human-required checks

- Check with `systemctl is-active toolnet-publisher toolnet-publisher-frontend toolnet-scheduler-tick` and `systemctl list-timers` for the alert scanner timer, if enabled. Confirm status via existing service logs without exposing cookies/credentials.
- Test public HTTPS on the actual configured domain, authentication landing, admin login, CTV login, tenant 404, logout and session expiry from a trusted browser. Verify CSP, CSRF, secure cookies, no sensitive logs. Do **not** infer success solely from an HTTP 200/405 health endpoint.
- Confirm a CTV can prepare one permitted Job, fetch allowed R2 images, open the correct Facebook Group in their own browser, submit manually and record `pending_reported` without the Job being marked `published`. Only an independent authorized readback chain can promote published. Verify this in a small pilot with appropriate Group permissions.
- Verify backups and a complete restoration practice to a separate environment; record UTC time, operator, result and snapshot identifier **outside source control**.
- Verify there are no unresolved lease-expired, unknown-result or cross-Pipeline incidents. Inspect proxy pin/IP health for the account used in the pilot.
- Explicitly approve go/no-go by a responsible human **after** reading evidence. This version does not store approval or modify any release automation.

## Stage D — Deploy (human controlled)

After the installer has passed tests on the target VPS, review `git diff` and `git diff --check`, commit approved code and push `origin/main`. Build the frontend on the target using `npm run build`, then restart `toolnet-publisher` and `toolnet-publisher-frontend`. Do not restart the scheduler or enable a new timer unless a separate change requires it.

Repeat Stage B and Stage C. Record the released commit SHA and result of each check. If `blocked`, treat release as **NO-GO**; finish an incident report, fix the cause and repeat gates. Avoid auto-retry of uncertain jobs.

## Rollback / incident response

1. Stop only the affected request-facing services as required by incident severity. **Do not blindly restart a worker/scheduler if Job states are uncertain**.
2. Preserve logs, current git SHA, Neon snapshot and R2 state. Never place secrets in incident artifacts.
3. No new database migration is introduced by 9.7.20. Roll back code by an reviewed `git revert <release-commit>` (prefer a follow-up revert commit on the shared branch). Run build and Django check before restarting affected services. Do not use `git reset --hard` on a shared production checkout or drop database tables.
4. If a rollback encounters pre-existing migrations from prior steps, assess them individually. **Do not automatically reverse historical schema migrations**: app code/schema mismatch can cause data loss.
5. Re-run health, tenant tests and manual pilot evidence before reopening traffic. Job `uncertain` and previously reserved media must remain quarantined for review.

## Acceptance rubric

`blocked`: at least one failed, incomplete or skipped internal check. `pending_operator_signoff`: all internal probes pass, but VPS, HTTP, backup and real Facebook pilot must be checked by a human. Neither state is approval to publish, deploy, or schedule Facebook posts.

**Scope of tests**: database queries and simulated rollback tests. It does not establish concurrency throughput, penetration-test certification, a real Meta publishing API, legal permission to post, or running systemd health.
