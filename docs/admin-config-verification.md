# Admin configuration implementation and verification

Date: 2026-10-31. Deployment is **blocked**, not verified complete.

Implemented from the existing system_config module:

- Super Admin session authorization and CSRF for every configuration mutation.
- Provider CRUD, validation, default selection, enable/disable, key rotation/revocation and connection probes.
- R2 saved overrides, encrypted access ID and secret, enable/disable override, reset to environment and temporary-object probes with cleanup.
- Read-only Neon status and alternate-URL connection testing without changing runtime database configuration or writing .env.
- Runtime service health observations, reporting unknown when systemd cannot be queried.
- Atomic configuration changes with audit logging; failed audit writes roll back changes.
- OpenAI-compatible, Anthropic and Gemini adapters integrated with the existing Caption Engine. An explicitly selected default takes precedence, then active fallbacks by priority. Until a default is selected, environment configuration remains primary. A missing/revoked provider key never receives the environment key.
- Responsive /config with four tabs, live API data, validation, loading/errors, CSRF and working action handlers. Secrets are write-only and never hydrated back into forms.

## Verified locally

Python: `/root/toolnet-group-publisher/.venv/bin/python`.

```sh
.venv/bin/python backend/manage.py check
.venv/bin/python backend/manage.py test modules.system_config --settings=config.settings_test_config --noinput
.venv/bin/python backend/manage.py makemigrations --check --dry-run --settings=config.settings_test_config
cd frontend
npx tsc --noEmit
npx eslint 'src/app/(admin)/config/page.tsx' src/components/layout/Sidebar.tsx
```

19 tests pass on disposable SQLite. All database aliases are replaced by the isolated settings module; no production test database is created. Tests cover permissions (including staff-only and superuser-only), CSRF, ciphertext storage, secret preservation, upstream error redaction across all three adapters, audit rollback, default selection through Caption Engine, environment preservation, revoked-key isolation, fallback, R2 CRUD and temporary-object cleanup.

## Environment blockers observed

- Neon: `failed to resolve host ...neon.tech: Temporary failure in name resolution`. Read-only `migrate --plan` could not run. Production migrations have **not** been applied in this session.
- R2 real HEAD connection probe: failed. No live R2 object was written by verification.
- AI real connection probe: failed. No production rows were created by verification.
- GitHub push transport: `Could not resolve host: github.com`.
- systemd: `Failed to connect to bus: Operation not permitted`.
- local frontend: connection refused at `127.0.0.1:3000`; no host services visible from this process namespace. Tunnel verification and authenticated browser/iPhone checks remain unverified.
- `npm run build`: Turbopack did not progress past compile and was interrupted. Webpack attempt failed because spawning the TypeScript CLI returns `EPERM` in this environment. A temporary in-process compiler configuration advanced the build but failed fetching Geist and Geist Mono from `fonts.googleapis.com` (`EAI_AGAIN`). The temporary configuration was restored; no build bypass, font mocks or skipped type checking are committed. A production build has **not** passed.

## Deployment still required in an environment with host access

After connectivity and host process access are restored: push main; run the production build; inspect and apply only system_config migrations (0001 if pending, 0002 encrypting access IDs, 0003 default uniqueness); restart toolnet-publisher, toolnet-publisher-frontend and the caption worker to load the new Caption Engine integration. Do not restart unrelated publishing/proxy/pipeline services. Confirm /config through the frontend Cloudflare Tunnel, authenticate with an existing Super Admin, and verify the four tabs and live probes without creating test rows in Neon. Existing production settings must remain primary unless the administrator explicitly chooses an override/default.
