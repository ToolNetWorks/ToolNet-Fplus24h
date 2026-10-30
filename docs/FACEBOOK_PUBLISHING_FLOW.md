# Facebook Publishing Flow — HAR Analysis (Phase 1)

## 1. Overview

This document describes the Facebook Group anonymous-posting flow as captured in a HAR
file recorded on **2026-10-30**. All sensitive data (cookies, tokens, CSRF tokens,
user IDs, session identifiers) has been **redacted**. The HAR file was inspected only
in read-only mode; no requests were replayed or modified.

The recording captures a post being created in a Facebook Group with **anonymous
posting enabled** (`is_anonymous: true`, `composer_entry_point: publisher_bar_anonymous_author`).

**Total HAR entries**: 567 — 79 on `www.facebook.com`, 33 GraphQL POST requests,
2 photo-upload requests.

---

## 2. Target Request Analysis

### 2.1 GroupCometComposerCreateDialogQuery (Entry #448, #449)

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **URL** | `https://www.facebook.com/api/graphql/` |
| **Status** | `200` |
| **Time** | ~417ms (entry #448), ~313ms (entry #449) |
| **Content-Type** | `application/x-www-form-urlencoded` |
| **Headers** | `x-fb-friendly-name`, `x-fb-lsd`, `x-asbd-id`, `origin`, `referer` |
| **Operation** | `GroupCometComposerCreateDialogQuery` |

**Variables** (safe metadata only):

```json
{
  "displayActorID": "[REDACTED]",
  "enable_admin_assist_warnings": false,
  "feedLocation": "GROUP",
  "groupID": "[REDACTED]",
  "privacySelectorRenderLocation": "COMET_COMPOSER",
  "scale": 1
}
```

**Response structure** (`data.group`):

- `group.id` — Group ID
- `group.group_comet_composer.header_banner.__typename`:
  `GroupsCometComposerAnonymousPostToggle`
- `group.group_comet_composer.footer.__typename`:
  `GroupsCometComposerFooterWithSinglePostButton`
- `group.group_comet_composer.footer.post_button_label`: `"Đăng"` (Vietnamese for "Post")
- `group.if_viewer_can_see_anonymous_post_toggle_button` — toggle visibility (boolean)
- `group.group_anonymous_post_info` — anonymous-post disclaimer:
  - `disclaimer_headline`: present (indicates anonymous posting is available)
  - `disclaimer_messages`: array of 2 messages
- `group.post_pending_approval_toast_text` — present (indicates pending-approval path)
- `group.should_show_join_cta_on_pending_post_toast`: `false`
- `profile.__typename`: `GroupAnonAuthorProfile` (anonymous actor profile)
- `data.profile.id`: `"Người tham gia ẩn danh"` (Anonymous participant)

**Anonymous posting state**: The response confirms that anonymous posting is
available via the `if_viewer_can_see_anonymous_post_toggle_button` field. The group
info includes `group_anonymous_post_info` with a disclaimer, indicating the Group
permits anonymous posts.

### 2.2 Photo Upload (Entry #494)

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **URL** | `https://upload.facebook.com/ajax/react_composer/attachments/photo/upload` |
| **Status** | `200` |
| **Time** | ~2384ms |
| **Content-Type** | `multipart/form-data` |

**Multipart form fields** (names only, values redacted):

- `source` — upload source identifier
- `profile_id` — uploader's profile ID (REDACTED)
- `waterfallxapp` — app identifier
- `farr` — **the image file** (filename redacted)
- `upload_id` — upload session identifier (REDACTED)

**Response structure**:

```json
{
  "__ar": 1,
  "rid": "[REDACTED]",
  "payload": {
    "isSpherical": false,
    "height": 233,
    "width": 377,
    "imageSrc": "https://scontent.[REGION].fbcdn.net/[PATH]_n.png",
    "uploadID": "[REDACTED]"
  }
}
```

**Notes**:
- Response is prefixed with `for (;;);` anti-XSS padding.
- Response includes `height`/`width` of the uploaded image.
- Response includes `imageSrc` — a CDN-signed URL for the uploaded image.
- `upload_id` is used to reference the uploaded photo in the subsequent
  `ComposerStoryCreateMutation`.

### 2.3 ComposerStoryCreateMutation (Entry #500)

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **URL** | `https://www.facebook.com/api/graphql/` |
| **Status** | `200` |
| **Time** | ~3039ms |
| **Content-Type** | `application/x-www-form-urlencoded` |
| **Operation** | `ComposerStoryCreateMutation` |

**Key input variables** (safe metadata only):

```json
{
  "input": {
    "composer_entry_point": "publisher_bar_anonymous_author",
    "composer_source_surface": "group",
    "composer_type": "group",
    "logging": { "composer_session_id": "[REDACTED]" },
    "source": "WWW",
    "message": { "text": "[CONTENT REDACTED]", "ranges": [...] },
    "with_tags_ids": null,
    "inline_activities": [],
    "text_format_preset_id": "0",
    "group_flair": { "flair_id": null },
    "ask_admin_to_post_for_user": { "is_asking_admin_to_post": true },
    "attachments": [{ "photo": "[REDACTED: photo object from upload]" }],
    "composed_text": { ... },
    "navigation_data": { "attribution_id_v2": "..." },
    "tracking": [...],
    "event_share_metadata": { "surface": "newsfeed" },
    "audience": { "to_id": "[REDACTED: group ID]" },
    "actor_id": "[REDACTED]",
    "client_mutation_id": "1"
  },
  "feedLocation": "GROUP",
  "feedbackSource": 0,
  "groupID": null,
  "scale": 1,
  "isGroup": true,
  "privacySelectorRenderLocation": "COMET_STREAM"
}
```

**Critical field**: `composer_entry_point: "publisher_bar_anonymous_author"` — this
explicitly tells Facebook to post as an anonymous author.

**Response** (`data.story_create`):

```json
{
  "story_create": {
    "story_id": null,
    "post_id": null,
    "publishing_flow": "FALLBACK",
    "story": {
      "id": "[REDACTED]",
      "url": "https://www.facebook.com/groups/[GROUP]/permalink/[POST_ID]/",
      "legacy_story_hideable_id": "[REDACTED]",
      "is_anonymous": true,
      "default_actor": {
        "__typename": "GroupAnonAuthorProfile"
      }
    },
    "group_feed_story_edge": {
      "node": {
        "__typename": "Story",
        "post_id": "[REDACTED]",
        "permalink_url": "https://www.facebook.com/groups/[GROUP]/posts/[POST_ID]/"
      }
    },
    "logging_token": "[REDACTED]"
  }
}
```

**Key observations**:
- `story_id` and `post_id` at the top level of `story_create` are `null`, but the
  `story.id` and `story.post_id` (within `group_feed_story_edge.node`) contain the
  actual identifiers — the post was created.
- `is_anonymous: true` confirms the post is anonymous.
- `publishing_flow: "FALLBACK"` — this is a standard flow indicator.
- `default_actor.__typename: "GroupAnonAuthorProfile"` — confirms anonymous identity.
- The `permalink_url` is available immediately in the response.

### 2.4 groupsCometFetchStoryQuery (Entry #501, #502)

| Field | Value |
|-------|-------|
| **Method** | `POST` |
| **URL** | `https://www.facebook.com/api/graphql/` |
| **Status** | `200` |
| **Time** | ~434ms (#501), ~531ms (#502) |
| **Content-Type** | `application/x-www-form-urlencoded` |
| **Operation** | `groupsCometFetchStoryQuery` |

**Variables** (safe metadata only):

```json
{
  "id": "[REDACTED: story ID from mutation response]",
  "feedLocation": "GROUP",
  "feedbackSource": 0,
  "focusCommentID": null,
  "scale": 1,
  "isGroup": true,
  "privacySelectorRenderLocation": "COMET_STREAM"
}
```

**Response structure** (`data.node`):

```json
{
  "node": {
    "__typename": "Story",
    "__isNode": "Story",
    "id": "[REDACTED]",
    "cache_id": "[REDACTED]",
    "post_id": "[REDACTED]",
    "creation_time": [REDACTED: unix timestamp],
    "attachments": [{
      "media": "[REDACTED]",
      "styles": "[REDACTED]"
    }],
    "permalink_url": "https://www.facebook.com/groups/[GROUP]/posts/[POST_ID]/",
    "feedback": {
      "id": "[REDACTED]",
      "owning_profile": {
        "__typename": "GroupAnonAuthorProfile",
        "name": "[REDACTED]"
      },
      "associated_group": {
        "id": "[REDACTED]"
      }
    },
    "actors": [{
      "__typename": "GroupAnonAuthorProfile",
      "name": "[REDACTED]",
      "id": "[REDACTED]"
    }],
    "to": {
      "__typename": "Group",
      "name": "[REDACTED]",
      "id": "[REDACTED]"
    }
  }
}
```

**Post submission verification**:
- The `post_id` field in the fetched story confirms the post was successfully created.
- The `feedback.owning_profile.__typename: "GroupAnonAuthorProfile"` confirms the
  post is associated with the anonymous author identity.
- No "pending approval" or error state is visible in this response for this
  particular post.

---

## 3. Anonymity and Posting State Analysis

### 3.1 Anonymous Posting Indicators

| Check | Facebook Response Field | Value |
|-------|------------------------|-------|
| Toggle visible | `group.if_viewer_can_see_anonymous_post_toggle_button` | Present (dict with id) |
| Post is anonymous | `story.is_anonymous` | `true` |
| Actor type | `story.default_actor.__typename` | `GroupAnonAuthorProfile` |
| Author name | `story.default_actor.name` | `"Người tham gia ẩn danh"` |
| Entry point | `variables.input.composer_entry_point` | `"publisher_bar_anonymous_author"` |

### 3.2 Pending Approval States

- `group.post_pending_approval_toast_text` — present, indicating the group may show
  pending approval messages.
- `group.if_viewer_can_post_with_approval` — present (value redacted), indicating
  posts may require admin approval in some groups.
- In this HAR session, the post was immediately visible (no pending state in
  `group_cometFetchStoryQuery` response).

### 3.3 Group Membership Status

- The HAR does **not** show whether the posting account was a member or non-member
  of the group at time of posting.
- Facebook does not expose membership status in the composer flow responses shown
  here — it is determined by the `if_viewer_can_see_anonymous_post_toggle_button`
  and `group_anonymous_post_info` fields.
- The `ask_admin_to_post_for_user.is_asking_admin_to_post: true` field suggests the
  composer is configured to request admin review when the account cannot directly post.

---

## 4. Complete Posting Sequence

The HAR captures the following chronological request sequence for post creation:

```
1. [Entry #448] POST /api/graphql/ — GroupCometComposerCreateDialogQuery
   (Initialize composer, check anonymous posting eligibility)
   → Response: 417ms, 252KB — confirms anonymous posting toggle visible

2. [Entry #449] POST /ajax/relay-ef/ — GroupCometComposerCreateDialogQuery
   (Relay fragment fetch, additional composer data)
   → Response: 313ms

3. [Entry #490] POST /api/graphql/ — useComposerVideoUploaderConfigQuery
   (Get upload configuration)
   → Response: 270ms

4. [Entry #494] POST /ajax/react_composer/attachments/photo/upload
   (Upload image to Facebook CDN)
   → Response: 2384ms, 1.3KB
   → Returns: height, width, imageSrc URL, uploadID

5. [Entry #500] POST /api/graphql/ — ComposerStoryCreateMutation
   (Submit post with photo attachment and anonymous author)
   → Response: 3039ms, 129KB
   → Contains: story.id, post_id, permalink_url, is_anonymous=true

6. [Entry #501] POST /api/graphql/ — groupsCometFetchStoryQuery
   (Verify story was created)
   → Response: 434ms, 119KB
   → Contains: post_id, permalink_url, feedback info

7. [Entry #502] POST /api/graphql/ — groupsCometFetchStoryQuery
   (Additional story verification)
   → Response: 531ms, 119KB

8. [Entry #566] POST /api/graphql/ — CometUFIFeedbackReactMutation
   (Likely a reaction/interaction on the post)
   → Response: 1065ms
```

---

## 5. HTTP Transport Details

### 5.1 Required Headers

| Header | Purpose |
|--------|---------|
| `Content-Type` | `application/x-www-form-urlencoded` (GraphQL) or `multipart/form-data` (upload) |
| `x-fb-friendly-name` | GraphQL operation name (e.g., `ComposerStoryCreateMutation`) |
| `x-fb-lsd` | Facebook LSD token (session-dependent) |
| `x-asbd-id` | App identifier (`359341`) |
| `origin` | `https://www.facebook.com` |
| `referer` | Group URL: `https://www.facebook.com/groups/[GROUP_ID]/` |
| `accept-language` | `vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7` |
| `user-agent` | Browser user agent string |

### 5.2 Request Parameters

All GraphQL requests are POST to `/api/graphql/` with form-encoded body containing:
- `av` — actor/viewer ID (REDACTED)
- `__aaid` — app ID
- `__user` — user ID (REDACTED)
- `__req` — sequential request counter
- `__hs` — hashing signature
- `fb_dtsg` — page token (REDACTED)
- `__hsi` — host signature (REDACTED)
- `fb_api_req_friendly_name` — operation name
- `variables` — JSON-encoded variables
- `server_timestamps` — `true`

### 5.3 Photo Upload Parameters

Form fields (multipart):
- `source` — upload source (e.g., `"8"`)
- `profile_id` — uploader profile ID (REDACTED)
- `farr` — file payload (the actual image binary)
- `upload_id` — session upload ID (REDACTED)

Response format: `for (;;);{"__ar":1,"rid":"...","payload":{"height":N,"width":N,"imageSrc":"URL",...}}`

---

## 6. Key Response Fields for Worker Implementation

### 6.1 Composer Initialization Response

- `data.group.group_anonymous_post_info` — confirms anonymous posting is available
- `data.group.if_viewer_can_see_anonymous_post_toggle_button` — toggle visibility
- `data.group.group_comet_composer.footer.post_button_label` — "Đăng" (Post)
- `data.profile.__typename` — `GroupAnonAuthorProfile` (anonymous actor)

### 6.2 Story Creation Response

- `data.story_create.story.id` — story ID (non-null after successful creation)
- `data.story_create.group_feed_story_edge.node.id` — alternative story ID
- `data.story_create.group_feed_story_edge.node.post_id` — post ID
- `data.story_create.story.is_anonymous` — `true` confirms anonymous posting
- `data.story_create.story.default_actor.__typename` — `GroupAnonAuthorProfile`
- `data.story_create.story.url` / `permalink_url` — post URL
- `data.story_create.publishing_flow` — flow type (`FALLBACK`)

### 6.3 Story Fetch Response

- `data.node.post_id` — confirms post exists (null if not yet published)
- `data.node.permalink_url` — direct link to the post
- `data.node.feedback.owning_profile.__typename` — `GroupAnonAuthorProfile` (anonymous)
- `data.node.to.name` — group name

---

## 7. Technical Constraints for Worker Implementation

Based on this analysis, the Worker should:

1. **Use browser automation** (not raw GraphQL requests) because Facebook requires
   session cookies, CSRF tokens, LSD tokens, and dynamic anti-abuse headers that
   change per session.

2. **Verify anonymous posting eligibility** before submitting:
   - Check `if_viewer_can_see_anonymous_post_toggle_button`
   - Check `group_anonymous_post_info` presence

3. **Upload image to Facebook CDN** using the browser's native file input — the
   Worker should not bypass Facebook's own upload mechanism. The image is staged
   locally (downloaded from R2), uploaded via simulated file selection, then
   deleted from local temp after processing.

4. **Set anonymous posting mode** by enabling the anonymous post toggle in the
   browser UI, not by constructing raw GraphQL variables.

5. **Verify post creation** by checking the browser for the post's permalink URL
   and confirming the `post_id` appears in the UI.

6. **Never treat `publishing_flow: FALLBACK` as a success indicator** — this is
   an internal Facebook routing flag, not a confirmation of publication.

7. **Never auto-join Groups** — the HAR does not show a join action; the posting
   Account's membership status is not relevant to the anonymous posting flow.

8. **Preserve the fixed Proxy Pin** — each Account's browser session must route
   through its assigned proxy endpoint to maintain IP affinity.

---

## 8. Corrections to Phase 1 Conclusions

The following corrections apply to the initial analysis:

### 8.1 Post ID ≠ Published

- The presence of `post_id` (in `data.story_create.group_feed_story_edge.node.post_id`
  and `data.node.post_id` from the story fetch) only proves that Facebook **created**
  a post object. It does **not** prove the post is publicly visible or has cleared
  admin approval.
- Facebook can return a 200 status with a `post_id` even when the post is held in
  pending-admin-approval state.

### 8.2 `ask_admin_to_post_for_user` Interpretation

- `ask_admin_to_post_for_user.is_asking_admin_to_post=true` is a **signal** that may
  relate to the admin-approval workflow, but it is **not sufficient** to determine
  whether approval is required or has been granted.
- This field should be recorded for context but must not be used as a sole indicator
  of posting permission or approval status.

### 8.3 `if_viewer_can_post_with_approval`

- `if_viewer_can_post_with_approval=null` (observed in the HAR) does not prove the
  post was approved, nor does it prove the account has direct posting permission.
- This field must be checked alongside other indicators (`if_viewer_can_see_anonymous_post_toggle_button`,
  `group_anonymous_post_info`) to determine the actual posting capability.

### 8.4 Group Membership

- The HAR contains **no evidence** about whether the posting Account was a member
  or non-member of the target Group at the time of posting.
- Facebook's anonymous posting flow does not require the composer to be a member.
- **Do not infer** membership status from the HAR data.

### 8.5 `publishing_flow: FALLBACK`

- `publishing_flow: FALLBACK` is an internal Facebook routing indicator, not a
  success state. It does not guarantee publication was completed or that the post
  is visible.

### 8.6 GraphQL API Reliability

- The internal Facebook GraphQL endpoint (`/api/graphql/`) is **not an official API**.
  The `fb_dtsg`, `__hsi`, `__comet_req`, and `__spin_*` tokens are dynamic and
  session-specific. They cannot be reliably replayed without a valid browser session.
- The Worker must use browser automation to interact with Facebook's UI.

### 8.7 Photo Upload Response

- The photo upload response contains `for (;;);` anti-XSS padding prefix.
- The `uploadID` field is used to reference the uploaded photo in the subsequent
  story creation mutation. However, the Worker will use browser-native file
  upload rather than replaying this request.

---

## 9. Sensitive Data Handling

This analysis was performed with the following safeguards:
- All cookies, tokens, CSRF values, user IDs, session IDs, and page tokens were
  redacted as `[REDACTED]`.
- No request was replayed or sent to Facebook.
- No request or response body was saved to disk.
- Only structural metadata (field names, types, HTTP status, timing) was extracted.
- The HAR file remains unchanged in read-only mode.
