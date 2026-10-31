# R2 Drive implementation and verification

Date: 2026-10-31. Source implementation complete; production acceptance and deployment remain **blocked by this execution environment**.

## UI and behavior

Admin → Cấu hình → Cloudflare R2 now has two areas: **Quản lý tệp** (default) and **Kết nối R2** (existing credentials form and Test Connection).

The user's reference layout is implemented with the subsequent requested **white background and blue folders**, grid/list modes, CTV search, Album/filename search, breadcrumbs, parent navigation, counts, private thumbnail proxies, a large-image dialog, metadata, and device download. Mobile uses two columns, flexible controls, wrapped breadcrumbs, and a vertically stacked image viewer. Every list is paged at 24 entries (API maximum 48); thumbnails are lazy loaded and generated at a maximum of 360 × 280 pixels. Native images and fetch use authenticated same-origin endpoints. No public bucket URL or presigned credential-bearing object URL is returned.

Directory folders are virtual: Pipeline.ctv is a OneToOneField, and the existing Pipeline → Album → AlbumImage relations supply folders, names and image counts. No models/migrations or existing upload/content APIs were changed for this task. Existing image keys and production data remain unchanged. Album uploads are WebP; the original filename is displayed, while downloads use its basename with `.webp` to match the stored format.

The alternate R2 prefix browser lists existing CommonPrefixes/objects with S3 Delimiter and continuation-token paging. It uses time-limited, purpose-specific signed references issued by the server; arbitrary client storage_key, prefix, key, bucket or url parameters are rejected. Known AlbumImage objects are mapped back to their original filenames and database-scoped image APIs. Raster images outside the Album registry have private proxy preview/download and metadata. Non-image objects are displayed without executable preview/download.

## API

All routes below require an active Super Admin with both is_staff and is_superuser. GET/HEAD/OPTIONS only; POST/PUT/PATCH/DELETE return 405. Permission checks happen before object resolution or R2 calls. All responses use private/no-store and nosniff.

Base: `/api/v1/admin/config/r2-drive/`

- Root: CTV/Pipeline folders; `q` searches Pipeline/CTV, Album and image filename with bounded database slices.
- `pipelines/{pipeline_id}/`: Albums and scoped search.
- `pipelines/{pipeline_id}/albums/{album_id}/`: image metadata and pagination.
- `pipelines/{pipeline_id}/albums/{album_id}/images/{image_id}/`: image metadata.
- Same image path + `content/`: original preview; `?thumbnail=true` or `?download=true`.
- `prefixes/`: existing bucket prefixes with server-issued `ref` and `cursor`.
- `objects/content/` and `objects/metadata/`: signed object references only.

Database images resolve all three IDs together and verify the exact canonical key `pipeline-albums/{pipeline_id}/{album_id}/{image_id}.webp`, MIME, bounded byte size and SHA-256 before serving. Image decoding is bounded by the existing pixel limit. R2 errors and database outages return safe messages without exception payloads/credentials. R2 bodies are closed even when size checks fail.

The Drive service contains no object writes, deletes, copies, renames, uploads, folder markers or database mutation calls. Pipeline configuration, publishing jobs, proxies and existing CTV flows are untouched.

## Local verification

```sh
.venv/bin/python backend/manage.py check
.venv/bin/python backend/manage.py test modules.system_config --settings=config.settings_test_config --noinput
.venv/bin/python backend/manage.py makemigrations --check --dry-run --settings=config.settings_test_config
cd frontend
npx tsc --noEmit
npx eslint 'src/app/(admin)/config/page.tsx' src/features/r2-drive/*.tsx src/features/r2-drive/api.ts
```

36 tests pass on disposable SQLite, including 17 new Drive tests for real model relations (isolated fixtures), permissions on every route, rejected mutation methods, cross-CTV isolation, exact image identity, filename search, page boundaries, metadata, thumbnails, attachment downloads, integrity, safe errors, expired/tampered signed references, prefix cursors scoped to folders, oversized reads, and absence of storage writes. No production test rows or sessions were created.

TypeScript and lint pass. Model/migration check reports no changes. Django system check passes.

## Blocked production verification

Read-only probes were attempted against the configured production environment:

- Neon hostname and github.com fail DNS resolution (`gaierror`). Live API acceptance using an existing Super Admin (no new session/user) fails with OperationalError before data retrieval.
- Real R2 prefix listing fails with StorageUnavailable. No test object was written.
- systemd access fails: `Failed to connect to bus: Operation not permitted`.
- `http://127.0.0.1:3000/config/` refuses connection in this process namespace.
- `npm run build` remains at Turbopack compile and times out after 55 seconds. `npm run build -- --webpack` fails: `Could not parse output from TypeScript's --showConfig` (the subprocess EPERM restriction previously diagnosed in admin-config-verification.md). Production build has not passed; no checks were bypassed and next.config.ts was not changed.
- Browser launch was attempted. WebKit cannot start because required GTK/GStreamer libraries are missing. Chromium aborts in sandbox_host_linux.cc with `shutdown: Operation not permitted`. Actual Safari iPhone layout and interactive browser acceptance cannot be certified in this environment.

Pending host verification: Admin list → hiu9h → Albums → actual image thumbnails → full preview → device download → back navigation; cross-CTV isolation and pagination with production data; Safari no horizontal overflow; production build; backend/frontend service update; Cloudflare Tunnel verification. No restart was attempted against an incomplete production build. Only backend/frontend need updating for this task.
