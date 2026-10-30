# ToolNet Fplus24h — 9.7.19A: AI Caption Engine

## Actual scope

- Admin locks one destination handle per Pipeline (for example `@hiu9h`) and chooses optional auto-generation / auto-approval. CTV is not allowed to change destination.
- Each Pipeline has its own caption example library. Examples inform tone/length but are *not executable instructions*. Examples with any @handle are sanitized before being sent to the AI provider.
- Each Job receives a separate AI-generated caption and its revision history. On approval, the caption is written to `PublishingJob.caption` in the same PostgreSQL transaction.
- The final server-side validator rejects foreign @handles, normalizes the destination to exactly one occurrence, enforces max length, and prevents any generation on in-flight or manually handed-off Jobs.
- With the feature enabled, worker claims and manual handoffs are blocked unless the Job has an approved caption with the current destination and settings version.
- Existing Pipeline behavior remains unchanged until Admin opts in to caption generation. This module does **not** post to Facebook.

## API provider configuration (on the VPS, not in Git)

Set these variables for Django and the optional systemd timer:

```
TOOLNET_CAPTION_API_URL=https://api.toolnet.tech/v1/chat/completions
TOOLNET_CAPTION_API_KEY=<YOUR_SECRET>
TOOLNET_CAPTION_MODEL=<AN_AVAILABLE_MODEL_ID>
```

The URL is an example of an OpenAI-compatible completion endpoint, not a claim that any specific model is enabled. **Never commit keys.** Django must receive these env vars through its service environment. An optional `.env` file is not automatically loaded by the caption service itself; it reads `os.environ`. The systemd template uses `EnvironmentFile=-/root/toolnet-group-publisher/backend/.env`.

## UI

- Admin: Pipeline → Thao tác → **AI Caption & Trang đích** (`/pipelines/<uuid>/caption-settings/`). Set destination and enable module.
- CTV: Workspace → **AI viết Caption**. Add examples, generate/rewrite captions for queued Jobs, approve/reject each draft.
- Scheduler: Creates Jobs as before, but when enabled they cannot progress to a worker/handoff until their caption has been approved. Caption Tick creates drafts automatically for new queued Jobs. No LLM network calls inside Scheduler transactions.

## Automatic operation (24/7)

The automatic caption pipeline runs as two independent services; neither ever posts to Facebook.

| Unit | Cycle | Behavior |
| --- | --- | --- |
| `toolnet-scheduler-tick.service` | 30s | Enqueues due Jobs only (`facebook_dispatch_enabled: false`). |
| `toolnet-caption-tick.service` | 60s | Scans every eligible Pipeline, generates + auto-approves captions (limit 5/tick). Retries `failed` after 900s, retries stale `generating` after 10min, max 3 failed revisions. Uses `flock /run/toolnet-caption-tick.lock`. |
| `toolnet-recovery-tick.timer` | 5min | Resets captions stuck in `generating` >30min to `failed` (revision `generation_stale_reset`) and quarantines expired worker leases to `uncertain` (`WORKER_LEASE_EXPIRED`, no auto-retry). |

Install and enable:

```bash
cp deploy/systemd/toolnet-caption-tick.service /etc/systemd/system/
cp deploy/systemd/toolnet-recovery-tick.service deploy/systemd/toolnet-recovery-tick.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now toolnet-caption-tick.service
systemctl enable --now toolnet-recovery-tick.timer
```

`toolnet-caption-tick.service` requires `TOOLNET_CAPTION_*` variables in the Django service environment (or `backend/.env`) and honors `TOOLNET_CAPTION_TIMEOUT` (default 120s). It is `Restart=always`; the scheduler is `Restart=on-failure`.

### Manual one-shot commands

```bash
cd /root/toolnet-group-publisher/backend
../.venv/bin/python manage.py publishing_caption_tick --generate --limit 5
../.venv/bin/python manage.py publishing_caption_tick --generate --watch --poll-seconds 60 --limit 5
../.venv/bin/python manage.py publishing_recovery_tick            # preview
../.venv/bin/python manage.py publishing_recovery_tick --apply    # write recovery actions
```

`--pipeline-id` is optional: without it the tick scans all eligible Pipelines. `APPROVED` only means the caption is ready for handoff; the Facebook Groups adapter is fail-closed (`GROUPS_API_REMOVED_2024_04_22`), so nothing is published automatically.

The older per-Pipeline `toolnet-caption-tick@.timer` template remains available for deployments that prefer one timer per Pipeline, but the watch service above replaces it for normal operation.

## Acceptance

1. Admin can configure exactly one destination; another CTV or an unprivileged user cannot alter it.
2. Pipeline A cannot read/edit Pipeline B examples or Job captions.
3. No AI output can be approved with an @handle other than the Pipeline destination.
4. Final caption contains the exact locked destination once, even when inputs already include it.
5. Each Job gets a separately generated draft; no duplicate caption is reused within a Pipeline.
6. A Job with a pending draft cannot be prepared by a worker/handoff. After explicit approval it is eligible (subject to other existing safety checks).
7. Changing the locked destination while there is any active/inconclusive Job is blocked.
8. Provider token/URL are not returned through APIs or saved in the database; provider failures do not publish or approve.
9. All migration changes are reviewed; rollback of data schema requires an explicit migration plan and backups.

## Known limitations

- HTTP AI generation is a synchronous request, with a 120-second network timeout (`TOOLNET_CAPTION_TIMEOUT`). The watch service processes max 5 Jobs per tick. Failed generations are retried after 15 minutes, up to 3 failed revisions. It does not imply automatic Facebook posting.
- The Job list UI displays the most recent 50 Jobs. Caption examples are paginated 30 per page.
- Model training is retrieval-guided prompting from examples, **not** fine-tuning.
- The service does not inspect image content; it writes from examples and the Group name.
- This ZIP is prepared against a known commit and still requires Django/Neon/Next.js tests on the VPS.
