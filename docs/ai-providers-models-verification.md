# AI Providers, Keys, Models and Routing

Date: 2026-10-31. Implementation and isolated runtime verification completed. **Live provider acceptance, production build and deployment are not certified complete.**

## Delivered behavior

Admin → Cấu hình → **AI & API** has three white-background, responsive subviews based on the supplied reference images: Nhà cung cấp, Models, Định tuyến. Database, R2 Drive/connection and System Services remain intact.

- Registry-driven templates/adapters: OpenAI, Anthropic, Gemini, OpenRouter, Groq, ToolNetAPI and custom OpenAI-compatible endpoints.
- Provider CRUD, enabled confirmation, connection state/counts, HTTPS Base URL, timeout and optional validated custom headers. Header values and API keys are encrypted using the existing stable system-config cipher; GET returns header names and key metadata only. Blank keys on edit preserve the current secret. New providers are disabled unless the administrator explicitly enables them.
- Named encrypted keys, add/edit/rotate/delete, enable/disable, priority, last-test metadata and individual connection tests. Priority and authorized round-robin selection are available per route step. Selection happens at request start; errors never trigger key switching. HTTP 429 sets a provider-wide cooldown honoring a bounded numeric Retry-After (60 seconds otherwise), so immediate subsequent requests cannot switch keys to bypass the limit.
- Actual Models API discovery with Gemini pageToken, Anthropic after_id and compatible has_more/after pagination. Discovery is bounded and completes before inventory updates. Sync never deletes models or resets administrator settings. Unsupported list APIs report that manual configuration is needed. Synced models start disabled and untested; successful inference marks available, denied/missing-model responses mark unavailable, and transient transport failure does not assert lost access.
- Paginated model search, manual add/update, enabled state, default model, nullable sampling capability/settings, output token settings, configurable max_tokens/max_completion_tokens, known output limits, timeout and bounded retry policy. Unsupported/unknown sampling parameters are omitted. Anthropic requires an explicit max output token setting. Editing inference parameters resets test status.
- Real Model Test accepts a short prompt and returns response, actual provider/model, HTTP status, latency and numeric token usage when supplied. Prompt/response are not persisted in audit logs. Test endpoints do not create Caption/Job records. Web model tests are bounded to 45 seconds; configured runtime timeout remains effective within the route budget.
- Versioned task routes with primary model, key policy, ordered fallbacks, per-fallback timeout/retry and validation. Stale updates return 409; protected routed models prevent deleting their provider. Transient timeouts/network/service errors can fall back; input/auth/permission/model-access/security/quota errors stop. Retries use the same selected key and only configured HTTP 500/502/503 retries; ambiguous timeout is not retried against the same provider. Routes have a bounded overall runtime budget.
- Explicit model-default selection updates the provider default and an existing Caption primary route, preserving fallback ordering. New Caption calls use the router; existing destination locking, generation token/CAS commit, approvals, revision history and Pipeline isolation are unchanged. There is no pipeline-level model override in the current schema. Caption Review routing is available for callers but does not automatically approve or change existing review behavior.

## Existing production configuration

Legacy AI_URL/AI_MODEL/AI_KEY (or TOOLNET_CAPTION_* equivalents) are recognized without writing .env or copying secrets on GET. Current detected model: `agnes/agnes-3.0-flash`. Until a route is explicitly enabled or a provider/model default chosen, Caption continues to use legacy settings.

An explicit **Tiếp nhận cấu hình** action imports an encrypted copy as a disabled Provider/Model and is idempotent. It does not replace keys or activate a new provider automatically. No legacy import was performed against production during verification.

New migration `0004_aiprovider_custom_headers_encrypted_and_more.py` adds registry tables/provider fields and preserves existing encrypted single keys plus default/available model IDs. Previously applied migrations 0001–0003 were not edited. Only the active legacy default model remains enabled during preservation; additional legacy IDs remain visible without activation. No production migration was applied in this session.

## REST API

All new endpoints use SessionAuthentication, backend Super Admin checks, CSRF on mutations and private/no-store responses. All configuration changes and tests have audit records containing only IDs/status/counts.

Base: `/api/v1/admin/config/ai/`

- GET `registry/` — adapter catalog, tasks, redacted legacy status.
- POST `import-legacy/` — explicitly import without activation.
- GET/POST `providers/`; GET/PATCH/PUT/DELETE `providers/{provider}/`.
- POST `test-provider/` — unsaved provider connection check.
- POST `providers/{provider}/test/`.
- GET/POST `providers/{provider}/keys/`; PATCH/DELETE `.../keys/{key}/`; POST `.../keys/{key}/test/`.
- GET/POST `providers/{provider}/models/`; POST `.../models/sync/`.
- PATCH `.../models/{model}/`; POST `.../models/{model}/default/`; POST `.../models/{model}/test/`.
- GET `routes/`; PUT `routes/{task}/`; POST `routes/{task}/test/`.

Existing admin-config endpoints remain compatible, with managed-key rotation/revocation integrated. No database, R2, worker or publishing-queue API is changed by this task.

## Local verification

```sh
.venv/bin/python backend/manage.py check
.venv/bin/python backend/manage.py makemigrations --check --dry-run --settings=config.settings_test_config
.venv/bin/python backend/scripts/test_admin_config_isolated.py
cd frontend
npx tsc --noEmit
npx eslint 'src/app/(admin)/config/page.tsx' src/features/ai-config/*.tsx src/features/ai-config/api.ts
```

**81 tests pass**, including provider/key/model CRUD, encryption/redaction, CSRF and permissions, audit rollback, native request bodies/pagination, migration preservation, default switching, route versions, fallback classification, rate-limit cooldown, and complete Caption generation through the selected model. The Caption integration test creates/approves a fixture caption, switches default, proves the approved record remains unchanged, generates a new caption with the new model and verifies `@hiu9h` exactly once and cross-Pipeline denial. Remote responses are mocked in isolated tests; these results do not claim live provider connectivity.

All database aliases are replaced with disposable SQLite. The runner refuses a non-SQLite backend and uses temporary worker lock paths rather than production /run locks. Earlier expanded tick tests hit the host lock location; the isolated runner resolves that test-environment issue without changing worker/command implementation.

Django checks, migration consistency, TypeScript and targeted lint pass. A GitHub Actions workflow is added for isolated backend checks and frontend production build on a standard runner. **It has not run**, because publication is blocked.

## Live/deployment evidence and remaining acceptance

- ToolNetAPI legacy configuration is present. Live Models API and live model test were attempted directly using the securely loaded existing key. Both fail with `network_error`; DNS resolution for api.toolnet.tech fails (`gaierror`). No provider/model was actually connected or synchronized live, and no real caption is claimed.
- Local GitHub DNS fails. The GitHub connector can read main at `328d0202135ad518308e5292cb3e85337f053413`, but write preflight is denied: `403 Resource not accessible by integration` on create-blob. No connector ref update or remote commit occurred.
- Default Next.js build times out after 55 seconds at Turbopack compile. Webpack build fails parsing TypeScript --showConfig because subprocess execution is restricted (previously diagnosed EPERM). No production build bypass is committed; frontend/next.config.ts is unchanged.
- Host services are unavailable from this execution namespace: systemctl returns `Failed to connect to bus: Operation not permitted`; localhost:3000 refuses connection. Backend/frontend were not restarted against an unverified build. Production migration, Tunnel verification and authenticated Safari/iPhone browser acceptance remain blocked. Previous browser launch checks in this environment found Chromium sandbox operations denied and WebKit system libraries missing; no responsive PASS is fabricated.

Required remaining host acceptance: build successfully; apply the new system_config migration; restart backend/frontend and the caption worker so its existing facade loads the new router (leave publishing/scheduler services untouched); authenticate through the current Cloudflare Tunnel; add/test/sync a real provider, select model/default, save a route, and verify a new Caption uses it. Do not seed test rows in Neon or alter production pipeline destination/data. Local unrelated Facebook worker/browser edits are excluded from this task's commit.

## Changed code groups

- Existing models/serializers/facade/adapters and compatibility key management.
- New ai_serializers, provider_registry, key_manager, model_discovery, ai_router and shared wire protocol.
- New Super Admin ai_views and URL routes.
- New AIConfig/ModelPicker/API/types/styles; config page integration.
- Migration 0004, registry/integration/security tests, isolated regression runner, CI workflow and this report.

Protocol references used: [OpenAI Models API](https://developers.openai.com/api/reference/resources/models/methods/list/), [Anthropic Models API](https://docs.anthropic.com/en/api/models-list), [Gemini Models API](https://ai.google.dev/api/models). Provider-specific catalogs, pagination and sampling limits follow their native protocols; listing is not treated as proof of successful inference.
