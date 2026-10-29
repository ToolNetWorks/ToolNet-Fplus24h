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

## Tick: safe preview and opt-in generation

```bash
cd /root/toolnet-group-publisher/backend
../.venv/bin/python manage.py publishing_caption_tick --pipeline-id <UUID_PIPELINE> --limit 5
../.venv/bin/python manage.py publishing_caption_tick --pipeline-id <UUID_PIPELINE> --generate --limit 5
```

**Optional** per-Pipeline systemd timer. Do not enable until the AI API key is configured, the examples are uploaded and the exact destination is approved:

```bash
cp deploy/systemd/toolnet-caption-tick@.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now toolnet-caption-tick@<UUID_PIPELINE>.timer
systemctl list-timers 'toolnet-caption-tick*'
```

Tick **does not publish to Facebook** and does not backfill old drafts automatically. Manual `generate` permits retry of a failed/rejected draft. A live API endpoint must be available for actual AI text generation; a saved model name alone does not enable a provider.

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

- HTTP AI generation is a synchronous request, with a 25-second network timeout. The timer processes max 5 Jobs per run. It does not imply automatic Facebook posting.
- The Job list UI displays the most recent 50 Jobs. Caption examples are paginated 30 per page.
- Model training is retrieval-guided prompting from examples, **not** fine-tuning.
- The service does not inspect image content; it writes from examples and the Group name.
- This ZIP is prepared against a known commit and still requires Django/Neon/Next.js tests on the VPS.
