# Báo Cáo Cấu Hình AI Caption Engine - Chế Độ Tự Động Duyệt

## Tổng Quan
Đã cấu hình AI Caption Engine theo chế độ tự động duyệt (auto-approve) cho ToolNet Group Publisher.

## Các Thay Đổi Đã Thực Hiện

### 1. Kiểm Tra Logic Hiện Tại
✅ **Logic auto_approve trong `caption_engine.py` (dòng 313-326):**
- Khi `auto_approve=True`: Caption được tạo ở trạng thái `APPROVED` thay vì `DRAFT`
- Caption được ghi trực tiếp vào `PublishingJob.caption`
- Thiết lập `approved_by = actor` và `approved_at = timezone.now()`
- Ghi revision với action `'auto_approved'`

### 2. Validation An Toàn
✅ **Các kiểm tra được đảm bảo:**
- Caption phải hợp lệ (độ dài, format)
- Không trùng với caption khác trong Pipeline
- Chỉ chứa đúng một trang đích đã khóa
- Không chứa handle ngoại lai
- Job phải ở trạng thái `QUEUED`, chưa có `attempt_count`
- Cấu hình Pipeline không thay đổi trong quá trình tạo

### 3. Xử Lý Lỗi
✅ **Khi AI lỗi hoặc Job thay đổi:**
- Caption state được set thành `FAILED`
- Job giữ ở trạng thái chờ, không tự động duyệt
- Raise `CaptionConflict` exception
- Generation token được xóa để cho phép thử lại

### 4. E2E Test - Auto Approve Workflow
✅ **File mới:** `backend/scripts/e2e_auto_approve_caption.py`

**Các test case:**
1. ✅ Khởi tạo Pipeline test với auto_generate=true, auto_approve=true
2. ✅ Tạo kho caption mẫu
3. ✅ AI tạo caption Job 1 và tự động duyệt (APPROVED)
4. ✅ Caption được ghi vào PublishingJob.caption
5. ✅ ready_for_dispatch trả về true cho Job đã auto-approve
6. ✅ AI tạo caption Job 2 với nội dung khác Job 1
7. ✅ CTV có thể sửa caption khi Job chưa được Worker nhận
8. ✅ Caption Tick CLI ở chế độ preview an toàn (không đăng Facebook)
9. ✅ Caption Tick với --generate tự động duyệt Job mới
10. ✅ Job sai state không được tự động duyệt (raise CaptionConflict)
11. ✅ Job với destination cũ không được dispatch sau khi đổi settings

**Kết quả:** ALL PASS (12/12 test cases)

### 5. Scheduler & Caption Tick
✅ **Đảm bảo không đăng Facebook thật:**
- `scheduler_tick.py` dòng 19: "creates QUEUED Jobs only, NEVER posts to Facebook"
- `scheduler.py`: Scheduler chỉ tạo Jobs với state=QUEUED
- `publishing_caption_tick.py` dòng 12: "Never posts Facebook"
- Test E2E xác nhận: `facebook_posting: False`

### 6. Khả Năng CTV Sửa Caption
✅ **CTV vẫn có thể:**
- Sửa caption khi Job ở state `QUEUED`
- Approve lại với nội dung mới
- Reject caption và tạo lại
- **Không được sửa khi:**
  - Job đã `CLAIMED` (Worker đã nhận)
  - Job có `manual_handoff` (đã bàn giao)
  - Job.attempt_count > 0

### 7. Kiến Trúc 1 Pipeline = 1 CTV
✅ **Đảm bảo tenant isolation:**
- Pipeline model: OneToOne với CTV (ctv field)
- Tất cả operations đều kiểm tra Pipeline ownership
- Cross-tenant access trả về 404
- Test E2E xác nhận cách ly dữ liệu hoàn toàn

## Kết Quả Kiểm Thử

### E2E Production Test
```
================================================================================
TOOLNET FPLUS24H — E2E PRODUCTION TEST: AI CAPTION ENGINE 9.7.19A
================================================================================
[PASS] 1. Kiểm tra nạp cấu hình AI trên Django
[PASS] 2. Gọi trực tiếp API model agnes/agnes-3.0-flash (9.19s)
[PASS] 3. Admin khóa trang đích @hiu9h & Chặn CTV sửa
[PASS] 4. Thêm và quản lý kho caption mẫu
[PASS] 5. AI tạo caption riêng biệt cho từng Job (19.18s)
[PASS] 6. Kiểm tra bảo vệ trang đích duy nhất @hiu9h
[PASS] 7. Vòng đời Caption: Sửa, Duyệt, Từ chối và Tạo lại (2.31s)
[PASS] 8. Dispatch Guard & Scheduler Caption Tick
[PASS] 9. Kiểm tra cách ly dữ liệu giữa các Pipeline
================================================================================
>>> TẤT CẢ CÁC BÀI KIỂM THỬ ĐÃ ĐẠT (ALL PASS) <<<
```

### E2E Auto-Approve Test
```
================================================================================
E2E TEST: AUTO-APPROVE AI CAPTION WORKFLOW
================================================================================
[PASS] 0. Khởi tạo môi trường test
[PASS] 1. Bật auto_generate=true và auto_approve=true
[PASS] 2. Tạo kho caption mẫu
[PASS] 3. Tạo PublishingJob test
[PASS] 4. AI tạo caption Job 1 và tự động duyệt (3.33s)
[PASS] 5. Kiểm tra ready_for_dispatch Job 1
[PASS] 6. AI tạo caption Job 2 và tự động duyệt (8.09s)
[PASS] 7. CTV có thể sửa caption Job chưa được Worker nhận
[PASS] 8. Caption Tick CLI ở chế độ preview an toàn
[PASS] 9. Caption Tick với --generate tự động duyệt Job mới
[PASS] 10. Kiểm tra an toàn: Job sai state không được tự động duyệt
[PASS] 11. Job với destination cũ không được dispatch sau khi đổi settings
================================================================================
>>> TẤT CẢ KIỂM THỬ AUTO-APPROVE ĐẠT (ALL PASS) <<<
```

## Cách Sử Dụng

### 1. Bật Auto-Approve cho Pipeline (Admin Only)
```python
from modules.publishing.services.caption_engine import update_settings

update_settings(
    pipeline_id=pipeline.pk,
    actor=admin_user,
    destination='@your_destination',
    enabled=True,
    auto_generate=True,
    auto_approve=True,  # Bật tự động duyệt
    writing_guidance='Viết caption ngắn gọn, tích cực, tự nhiên.'
)
```

### 2. Chạy Caption Tick
```bash
# Preview mode (không tạo caption)
python manage.py publishing_caption_tick --pipeline-id <UUID>

# Generate mode (tạo và tự động duyệt)
python manage.py publishing_caption_tick --pipeline-id <UUID> --generate
```

### 3. Chạy Scheduler (Không Đăng Facebook)
```bash
# Preview mode
python manage.py scheduler_tick

# Enqueue mode (tạo Jobs QUEUED)
python manage.py scheduler_tick --enqueue
```

## Cấu Hình Production

### Biến Môi Trường Cần Thiết
```bash
TOOLNET_CAPTION_API_URL=https://api.toolnet.tech/v1
TOOLNET_CAPTION_API_KEY=sk-xxx...
TOOLNET_CAPTION_MODEL=agnes/agnes-3.0-flash
TOOLNET_CAPTION_TIMEOUT=120
```

### Systemd Services (Tùy Chọn)
Có thể cấu hình systemd timer để chạy caption tick định kỳ:
```
[Service]
ExecStart=/path/to/venv/bin/python manage.py publishing_caption_tick --pipeline-id <UUID> --generate
```

## Lưu Ý Quan Trọng

1. **An Toàn:** Scheduler và Caption Tick không bao giờ đăng lên Facebook thật
2. **Pipeline Isolation:** Mỗi Pipeline có 1 CTV riêng, không chéo tenant
3. **Auto-Approve Constraint:** `auto_approve=True` chỉ hoạt động khi `auto_generate=True`
4. **Destination Lock:** Admin phải lock destination trước khi bật auto-approve
5. **Không Đổi Destination:** Không thể đổi destination khi còn Job chưa hoàn tất
6. **CTV Edit:** CTV vẫn có thể sửa caption nếu Job chưa được Worker nhận

## Files Đã Thay Đổi

1. ✅ Kiểm tra logic: `backend/modules/publishing/services/caption_engine.py` (không sửa, đã đúng)
2. ✅ Kiểm tra model: `backend/modules/publishing/caption_models.py` (không sửa, đã đúng)
3. ✅ Kiểm tra tick: `backend/modules/publishing/management/commands/publishing_caption_tick.py` (không sửa, đã đúng)
4. ✅ Test mới: `backend/scripts/e2e_auto_approve_caption.py` (mới)
5. ✅ Báo cáo: `AUTO_APPROVE_REPORT.md` (mới)

## Kết Luận

✅ AI Caption Engine đã được cấu hình và kiểm thử đầy đủ theo chế độ tự động duyệt.

✅ Tất cả test cases đã PASS, không phá vỡ logic hiện tại.

✅ Scheduler và Caption Tick hoạt động an toàn, không đăng Facebook thật.

✅ CTV vẫn có thể sửa caption khi cần thiết.

✅ Kiến trúc 1 Pipeline = 1 CTV được duy trì.

---
**Ngày:** 29/10/2026  
**Người thực hiện:** AI Assistant  
**Trạng thái:** READY FOR DEPLOYMENT
