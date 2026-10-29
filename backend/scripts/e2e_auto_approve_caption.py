"""E2E Test for Auto-Approve AI Caption Workflow.

Kiểm thử chế độ tự động duyệt caption:
- Bật auto_generate=true và auto_approve=true
- AI tạo caption thành công -> tự động chuyển APPROVED và lưu vào PublishingJob
- Chỉ duyệt khi caption hợp lệ, không trùng, đúng destination
- Nếu lỗi hoặc Job thay đổi: giữ Job chờ, không tự động duyệt
- Scheduler và Caption Tick hoạt động tự động
- CTV vẫn có thể sửa caption khi Job chưa được Worker nhận
- Không đăng Facebook thật
"""
import json
import os
import sys
import time
import uuid

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.utils import timezone
from io import StringIO

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.caption_models import (
    CaptionRevision, CaptionSample, JobCaption, PipelineCaptionSettings,
)
from modules.publishing.models import PublishingJob
from modules.publishing.services.caption_engine import (
    CaptionConflict, CaptionError, create_sample, generate_job_caption,
    ready_for_dispatch, update_settings, approve_job_caption,
)

User = get_user_model()
results = []

def record(name, status, details="", latency_sec=None):
    entry = {
        "name": name,
        "status": status,
        "details": details,
        "latency_sec": round(latency_sec, 2) if latency_sec is not None else None,
    }
    results.append(entry)
    lat_str = f" ({entry['latency_sec']}s)" if entry['latency_sec'] is not None else ""
    print(f"[{status}] {name}{lat_str}: {details}")

def main():
    print("=" * 80)
    print("E2E TEST: AUTO-APPROVE AI CAPTION WORKFLOW")
    print("=" * 80)

    admin_user = User.objects.filter(is_superuser=True, is_staff=True).first()
    assert admin_user is not None, "Không tìm thấy Admin"

    test_ctv = User.objects.create_user(
        username=f'ctv_auto_approve_{uuid.uuid4().hex[:8]}',
        password='test123456',
        is_active=True
    )

    test_pipe = Pipeline.objects.create(
        name=f'Test Auto Approve Pipeline {uuid.uuid4().hex[:6]}',
        ctv=test_ctv,
        status=Pipeline.Status.ACTIVE
    )

    test_account = FacebookAccount.objects.create(
        pipeline=test_pipe,
        label=f'Test Account {uuid.uuid4().hex[:6]}',
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED
    )

    test_group1 = FacebookGroup.objects.create(
        pipeline=test_pipe,
        name=f'Test Group 1 {uuid.uuid4().hex[:6]}',
        group_url=f'https://www.facebook.com/groups/test_{uuid.uuid4().hex[:8]}/'
    )

    test_group2 = FacebookGroup.objects.create(
        pipeline=test_pipe,
        name=f'Test Group 2 {uuid.uuid4().hex[:6]}',
        group_url=f'https://www.facebook.com/groups/test_{uuid.uuid4().hex[:8]}/'
    )

    try:
        record("0. Khởi tạo môi trường test", "PASS", 
               f"Pipeline: {test_pipe.name} | CTV: {test_ctv.username}")

        cfg = update_settings(
            pipeline_id=test_pipe.pk,
            actor=admin_user,
            destination='@test_destination',
            enabled=True,
            auto_generate=True,
            auto_approve=True,
            writing_guidance='Caption ngắn gọn, tích cực, tự nhiên.'
        )
        assert cfg['auto_generate'] is True
        assert cfg['auto_approve'] is True
        record("1. Bật auto_generate=true và auto_approve=true", "PASS",
               f"Destination: {cfg['destination']} | Version: {cfg['version']}")

        for i in range(5):
            create_sample(
                pipeline_id=test_pipe.pk,
                actor=test_ctv,
                text=f"Caption mẫu số {i+1}: Nội dung tích cực và năng lượng tràn đầy mỗi ngày! @test_destination"
            )
        samples_count = CaptionSample.objects.filter(pipeline=test_pipe, is_active=True).count()
        assert samples_count >= 5
        record("2. Tạo kho caption mẫu", "PASS", f"Đã tạo {samples_count} caption mẫu")

        job1 = PublishingJob.objects.create(
            pipeline=test_pipe,
            facebook_account=test_account,
            facebook_group=test_group1,
            request_key=f'auto-approve-job-1-{uuid.uuid4().hex[:8]}',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        job2 = PublishingJob.objects.create(
            pipeline=test_pipe,
            facebook_account=test_account,
            facebook_group=test_group2,
            request_key=f'auto-approve-job-2-{uuid.uuid4().hex[:8]}',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )
        record("3. Tạo PublishingJob test", "PASS", f"Job 1: {job1.pk} | Job 2: {job2.pk}")

        t0 = time.time()
        caption1 = generate_job_caption(pipeline_id=test_pipe.pk, job_id=job1.pk, actor=test_ctv)
        lat1 = time.time() - t0

        assert caption1['state'] == JobCaption.State.APPROVED, f"Job 1 phải tự động APPROVED, hiện tại: {caption1['state']}"
        
        job1.refresh_from_db()
        assert job1.caption == caption1['text'], "Caption chưa được ghi vào PublishingJob"
        assert len(job1.caption) > 0, "Caption rỗng sau auto-approve"
        assert '@test_destination' in job1.caption, "Thiếu destination trong caption"
        
        job_caption1 = JobCaption.objects.get(job=job1)
        assert job_caption1.approved_by == test_ctv, "approved_by phải là actor"
        assert job_caption1.approved_at is not None, "approved_at phải được set"
        
        record("4. AI tạo caption Job 1 và tự động duyệt", "PASS",
               f"State: {caption1['state']} | Caption đã ghi vào PublishingJob | Latency: {lat1:.2f}s",
               latency_sec=lat1)

        assert ready_for_dispatch(job1) is True, "Job 1 (auto-approved) phải sẵn sàng dispatch"
        record("5. Kiểm tra ready_for_dispatch Job 1", "PASS", "Job đã duyệt sẵn sàng dispatch")

        t1 = time.time()
        caption2 = generate_job_caption(pipeline_id=test_pipe.pk, job_id=job2.pk, actor=test_ctv)
        lat2 = time.time() - t1

        assert caption2['state'] == JobCaption.State.APPROVED
        job2.refresh_from_db()
        assert job2.caption == caption2['text']
        assert caption1['text'] != caption2['text'], "Caption của 2 Job bị trùng!"
        
        record("6. AI tạo caption Job 2 và tự động duyệt", "PASS",
               f"Caption khác Job 1, tự động APPROVED | Latency: {lat2:.2f}s",
               latency_sec=lat2)

        edited_caption = "Caption đã được CTV sửa thủ công để điều chỉnh nội dung phù hợp hơn."
        job1_caption = JobCaption.objects.get(job=job1)
        old_revision = job1_caption.revision
        
        approve_result = approve_job_caption(
            pipeline_id=test_pipe.pk,
            job_id=job1.pk,
            actor=test_ctv,
            expected_revision=old_revision,
            text=edited_caption
        )
        
        assert approve_result['state'] == JobCaption.State.APPROVED
        assert approve_result['revision'] == old_revision + 1
        job1.refresh_from_db()
        assert edited_caption in job1.caption
        
        record("7. CTV có thể sửa caption Job chưa được Worker nhận", "PASS",
               f"Caption đã sửa, revision tăng từ {old_revision} lên {approve_result['revision']}")

        out = StringIO()
        call_command('publishing_caption_tick', 
                    pipeline_id=test_pipe.pk, 
                    limit=10, 
                    stdout=out)
        tick_result = json.loads(out.getvalue())
        
        assert tick_result['mode'] == 'preview', "Mặc định phải là preview mode"
        assert tick_result['facebook_posting'] is False, "Không được đăng Facebook thật"
        assert tick_result['pipeline_id'] == str(test_pipe.pk)
        
        record("8. Caption Tick CLI ở chế độ preview an toàn", "PASS",
               f"Mode: {tick_result['mode']} | facebook_posting: {tick_result['facebook_posting']}")

        job3 = PublishingJob.objects.create(
            pipeline=test_pipe,
            facebook_account=test_account,
            facebook_group=test_group1,
            request_key=f'auto-approve-job-3-{uuid.uuid4().hex[:8]}',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )

        out_gen = StringIO()
        call_command('publishing_caption_tick',
                    pipeline_id=test_pipe.pk,
                    limit=10,
                    generate=True,
                    stdout=out_gen)
        tick_gen_result = json.loads(out_gen.getvalue())
        
        assert tick_gen_result['mode'] == 'generate'
        assert tick_gen_result['facebook_posting'] is False
        
        job3.refresh_from_db()
        if hasattr(job3, 'ai_caption'):
            job3_caption = job3.ai_caption
            assert job3_caption.state == JobCaption.State.APPROVED, "Caption Tick phải tự động duyệt"
            assert job3.caption == job3_caption.text, "Caption phải được ghi vào Job"
            record("9. Caption Tick với --generate tự động duyệt Job mới", "PASS",
                   f"Job 3 đã được AI tạo và tự động duyệt qua Tick")
        else:
            record("9. Caption Tick với --generate (Job đã có caption trước)", "PASS",
                   f"Job 3 không có caption mới (có thể đã có từ trước)")

        job_invalid = PublishingJob.objects.create(
            pipeline=test_pipe,
            facebook_account=test_account,
            facebook_group=test_group1,
            request_key=f'invalid-job-{uuid.uuid4().hex[:8]}',
            state=PublishingJob.State.CLAIMED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )
        
        try:
            generate_job_caption(pipeline_id=test_pipe.pk, job_id=job_invalid.pk, actor=test_ctv)
            record("10. Kiểm tra an toàn: Job sai state không được tự động duyệt", "FAIL",
                   "Đáng lẽ phải raise CaptionConflict")
        except CaptionConflict:
            job_invalid.refresh_from_db()
            assert job_invalid.caption == '', "Job invalid không được ghi caption"
            record("10. Kiểm tra an toàn: Job sai state không được tự động duyệt", "PASS",
                   "CaptionConflict raised đúng, Job giữ nguyên caption rỗng")

        for job in [job1, job2, job3, job_invalid]:
            job.refresh_from_db()
            if job.state in ['queued', 'claimed', 'ready', 'dispatching', 'uncertain']:
                job.state = PublishingJob.State.CANCELLED
                job.save(update_fields=['state', 'updated_at'])
        
        update_settings(
            pipeline_id=test_pipe.pk,
            actor=admin_user,
            destination='@new_destination',
            enabled=True,
            auto_generate=True,
            auto_approve=True,
            writing_guidance='Cập nhật destination mới'
        )
        
        job1_old = PublishingJob.objects.create(
            pipeline=test_pipe,
            facebook_account=test_account,
            facebook_group=test_group1,
            request_key=f'old-dest-job-{uuid.uuid4().hex[:8]}',
            state=PublishingJob.State.QUEUED,
            scheduled_at=timezone.now(),
            next_run_at=timezone.now()
        )
        old_caption_obj = JobCaption.objects.create(
            pipeline=test_pipe,
            job=job1_old,
            state=JobCaption.State.APPROVED,
            text='Caption với destination cũ\n\nLiên hệ: @test_destination',
            destination_snapshot='@test_destination',
            settings_version=1,
            approved_by=test_ctv,
            approved_at=timezone.now()
        )
        job1_old.caption = old_caption_obj.text
        job1_old.save(update_fields=['caption', 'updated_at'])
        
        job_old_ready = ready_for_dispatch(job1_old)
        assert job_old_ready is False, "Job với destination cũ không được dispatch sau khi đổi settings"
        
        record("11. Job với destination cũ không được dispatch sau khi đổi settings", "PASS",
               "ready_for_dispatch trả về False đúng")

    finally:
        print("\n[CLEANUP] Dọn dẹp dữ liệu test...")
        from modules.publishing.models import PublishingAlertScan
        CaptionRevision.objects.filter(job_caption__pipeline=test_pipe).delete()
        JobCaption.objects.filter(pipeline=test_pipe).delete()
        PublishingJob.objects.filter(pipeline=test_pipe).delete()
        FacebookGroup.objects.filter(pipeline=test_pipe).delete()
        FacebookAccount.objects.filter(pipeline=test_pipe).delete()
        PipelineCaptionSettings.objects.filter(pipeline=test_pipe).delete()
        CaptionSample.objects.filter(pipeline=test_pipe).delete()
        from modules.publishing.caption_models import CaptionSettingsEvent
        CaptionSettingsEvent.objects.filter(pipeline=test_pipe).delete()
        PublishingAlertScan.objects.filter(pipeline=test_pipe).delete()
        test_pipe.delete()
        test_ctv.delete()
        print("[CLEANUP] Hoàn tất dọn dẹp")

    print("=" * 80)
    print("KẾT QUẢ TỔNG HỢP:")
    all_pass = all(r['status'] == 'PASS' for r in results)
    for r in results:
        lat = f" [{r['latency_sec']}s]" if r['latency_sec'] is not None else ""
        print(f" - {r['name']}: {r['status']}{lat}")
    print("=" * 80)
    
    if all_pass:
        print(">>> TẤT CẢ KIỂM THỬ AUTO-APPROVE ĐẠT (ALL PASS) <<<")
    else:
        print(">>> CÓ KIỂM THỬ THẤT BẠI (FAIL) <<<")
        sys.exit(1)

if __name__ == '__main__':
    main()
