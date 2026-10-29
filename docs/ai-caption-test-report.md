# AI Caption Engine - Test Report & Production Safety

## Executive Summary

**Status:** ✅ ALL TESTS PASS  
**Production Safety:** ✅ VERIFIED  
**Date:** 2026-10-29

## Test Data Cleanup

### Remnant Data Removed
From Pipeline "Lê Tấn Media" (4237b562-e8f3-4f35-b074-ec92901ce897):

1. **JobCaption:** 1 record removed
   - ID: `0865490e-4f2c-4e00-a55b-c6a4622bbf66`
   - State: `generating` (stuck)

2. **PublishingJobs:** 2 records removed
   - `f434a58b-257b-4ec1-8795-57659f40199a` (e2e-job-1-65bfbacc)
   - `04b9a33c-ac07-42d0-9fa4-1d34b42e6e32` (e2e-job-2-1a59ca7c)

3. **FacebookGroups:** 2 test groups removed
   - `391ea6c0-904c-43a9-b4b1-1bab4f8ebcf3` (Hội Doanh Nhân Khởi Nghiệp Trẻ)
   - `23bbdb34-ce86-4143-9cd5-4df5c439abee` (Cộng Đồng Bất Động Sản & Đầu Tư)

4. **FacebookAccount:** 1 test account removed
   - `65d37b89-4839-42f9-90bf-9293379717cc` (E2E Test Account 51420b)

### Production Data Preserved
✅ **Caption Samples:** 6 samples kept (useful for AI learning)  
✅ **Pipeline Settings:** Configuration preserved  
✅ **Audit History:** 6 CaptionSettingsEvent records kept

## Test Suite

### Django Unit Tests (Test Database)
**Location:** `backend/modules/publishing/tests/test_caption_isolated.py`

```
Ran 18 tests in 80.349s

OK
```

**Test Coverage:**
1. ✅ Destination validation (valid & invalid handles)
2. ✅ Caption finalization (idempotent, foreign handle rejection)
3. ✅ Admin-only settings update
4. ✅ Destination lock with pending jobs
5. ✅ Caption sample creation
6. ✅ Job caption generation
7. ✅ Caption lifecycle (generate → approve → reject → regenerate)
8. ✅ Dispatch guard (blocks unapproved jobs)
9. ✅ Multi-tenant isolation
10. ✅ API views (CTV vs Admin permissions)
11. ✅ Cross-tenant access blocking
12. ✅ Duplicate caption prevention
13. ✅ Provider HTTP error retry
14. ✅ Version conflict detection
15. ✅ Auto-generate functionality

### Smoke Tests (Rollback-Only)
**Location:** `backend/scripts/test_caption_engine.py`

```
DESTINATION EXACT-ONE, IDEMPOTENT, FOREIGN-DESTINATION: PASS
CTV ADMIN DESTINATION-LOCK AND TENANT ISOLATION: PASS
SAMPLE LIBRARY + NO DESTINATION ROTATION WHILE JOB IS PENDING: PASS
AI DRAFT, HUMAN APPROVAL, VERSION, JOB CAPTION AND DISPATCH GUARD: PASS
ROLLBACK: PASS — NO FIXTURE ROWS PERSISTED
```

### Frontend Build
**Location:** `frontend/`

```
✓ Compiled successfully in 1338ms
```

## Key Features Tested

### 1. Caption Generation Flow
- ✅ AI generates captions via ToolNet API (agnes/agnes-3.0-flash)
- ✅ Caption stored as DRAFT initially
- ✅ CTV can approve/reject captions
- ✅ Approved captions sync to Job.caption field
- ✅ Rejected captions clear Job.caption

### 2. Destination Lock
- ✅ Admin locks destination (e.g., @hiu9h)
- ✅ CTV cannot change destination
- ✅ Destination cannot change while jobs are pending
- ✅ All captions contain exactly ONE destination handle
- ✅ Foreign handles are rejected

### 3. Dispatch Guard
- ✅ Jobs with DRAFT caption: blocked from dispatch
- ✅ Jobs with APPROVED caption: allowed to dispatch
- ✅ Jobs with mismatched settings_version: blocked

### 4. Multi-Tenant Isolation
- ✅ CTV can only access own pipeline's captions
- ✅ Cross-tenant GET/POST returns 404
- ✅ Caption samples isolated per pipeline
- ✅ Job captions isolated per pipeline

### 5. Error Handling
- ✅ Provider HTTP 429/503/502/504: automatic retry with backoff
- ✅ Provider timeout: automatic retry
- ✅ Duplicate captions: prevented via database check
- ✅ Concurrent edits: version conflict detection

### 6. Scheduler Integration
- ✅ Auto-generate flag creates captions automatically
- ✅ Caption tick command (preview mode)
- ✅ Settings version increment triggers regeneration

## Production Configuration

### Current Settings (Pipeline "Lê Tấn Media")
```json
{
  "ai_provider": "https://api.toolnet.tech/v1",
  "ai_model": "agnes/agnes-3.0-flash",
  "ai_caption_enabled": true,
  "destination": "@hiu9h",
  "auto_generate": false,
  "auto_approve": false,
  "settings_version": 7
}
```

### Safety Guards
- ✅ Auto-generate: **OFF** (manual caption creation only)
- ✅ Auto-approve: **OFF** (manual approval required)
- ✅ Facebook posting: **OFF** (not enabled)
- ✅ Timer: **OFF** (manual trigger only)

## API Endpoints Tested

1. **GET** `/api/v1/pipelines/{pipeline_id}/caption-config/`
   - CTV: 200 (own pipeline), 404 (other pipeline)
   - Admin: 200 (any pipeline)

2. **PUT** `/api/v1/pipelines/{pipeline_id}/caption-config/`
   - CTV: 404 (not allowed)
   - Admin: 200 (allowed)

3. **GET** `/api/v1/pipelines/{pipeline_id}/caption-samples/`
   - CTV: 200 (own pipeline), 404 (other pipeline)

4. **POST** `/api/v1/pipelines/{pipeline_id}/caption-samples/`
   - CTV: 201 (own pipeline), 404 (other pipeline)

5. **GET** `/api/v1/pipelines/{pipeline_id}/caption-jobs/{job_id}/`
   - CTV: 200 (own pipeline), 404 (other pipeline)

6. **POST** `/api/v1/pipelines/{pipeline_id}/caption-jobs/{job_id}/generate/`
   - CTV: 201 (own pipeline), 404 (other pipeline)

7. **POST** `/api/v1/pipelines/{pipeline_id}/caption-jobs/{job_id}/approve/`
   - CTV: 200 (own pipeline), 404 (other pipeline)

8. **POST** `/api/v1/pipelines/{pipeline_id}/caption-jobs/{job_id}/reject/`
   - CTV: 200 (own pipeline), 404 (other pipeline)

## Architectural Invariants

1. **1 Pipeline = 1 CTV:** Enforced at model level
2. **Database:** Neon PostgreSQL (production & test)
3. **AI Provider:** ToolNet API (centralized)
4. **Caption Storage:** Per-job, versioned with CAS tokens
5. **Dispatch Guard:** Checked before every publish attempt

## Known Issues (Resolved)

1. ~~E2E test leaves test data in production~~ → Fixed by cleanup script
2. ~~Test database connection not closed~~ → Use `--keepdb` flag
3. ~~Duplicate caption not prevented~~ → Fixed by unique check

## Recommendations

### Before Production Use
1. ✅ Test data cleaned from production database
2. ✅ Unit tests pass in isolated test database
3. ✅ Frontend builds without errors
4. ⚠️ **Manual test required:** CTV UI workflow (generate → review → approve)
5. ⚠️ **Manual test required:** Caption tick scheduler with `--generate` flag
6. ⚠️ **Manual test required:** Backend restart during caption generation

### For Future Tests
1. Use isolated test database (test_caption_isolated.py)
2. Avoid running e2e_production_test_caption.py on production
3. If running production tests, verify cleanup completes
4. Monitor `JobCaption` state for stuck `generating` records

### Monitoring
1. Check for `JobCaption` records stuck in `generating` state
2. Monitor `CaptionSettingsEvent` for unauthorized changes
3. Alert on duplicate captions in same pipeline
4. Track AI API latency and error rates

## Conclusion

✅ **All automated tests pass**  
✅ **Production data safe**  
✅ **Test data cleaned**  
✅ **Multi-tenant isolation verified**  
✅ **Dispatch guard working**  
✅ **Error handling robust**  
✅ **Frontend build successful**

**Ready for commit and push to origin/main.**
