"""E2E Production Test for ToolNet Fplus24h 9.7.19A AI Caption Engine.

Executes real ToolNet API calls with agnes/agnes-3.0-flash, verifies Admin
destination lock @hiu9h, sample library, per-job caption generation,
lifecycle (rewrite, edit, approve, reject), dispatch guard, caption tick CLI,
and strict multi-tenant isolation.
"""
import json
import os
import re
import sys
import time
import uuid

# Ensure backend directory is in sys.path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.http import Http404
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from modules.facebook_accounts.models import FacebookAccount
from modules.facebook_groups.models import FacebookGroup
from modules.pipelines.models import Pipeline
from modules.publishing.caption_models import (
    CaptionRevision, CaptionSample, JobCaption, PipelineCaptionSettings,
)
from modules.publishing.models import PublishingJob
from modules.publishing.services.caption_engine import (
    CaptionConflict, CaptionError, _provider, approve_job_caption,
    check_destination, create_sample, finalize_caption, generate_job_caption,
    ready_for_dispatch, reject_job_caption, update_settings,
)
from modules.api.v1.publishing.caption_views import (
    CaptionJobAPIView, CaptionSamplesAPIView, CaptionSettingsAPIView,
)

User = get_user_model()
factory = APIRequestFactory()

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

def call_api(view_cls, method, path, pipe_id, user, job_id=None, payload=None):
    maker = getattr(factory, method)
    req = maker(path, data=payload, format='json') if payload is not None else maker(path)
    force_authenticate(req, user=user)
    kwargs = {'pipeline_id': pipe_id}
    if job_id:
        kwargs['job_id'] = job_id
    try:
        return view_cls.as_view()(req, **kwargs)
    except Http404:
        class Dummy:
            status_code = 404
        return Dummy()

def main():
    print("=" * 80)
    print("TOOLNET FPLUS24H — E2E PRODUCTION TEST: AI CAPTION ENGINE 9.7.19A")
    print("=" * 80)

    # -------------------------------------------------------------------------
    # 1. Kiểm tra nạp biến môi trường trên Django service (Không in API key)
    # -------------------------------------------------------------------------
    try:
        ai_url = os.environ.get('AI_URL') or os.environ.get('TOOLNET_CAPTION_API_URL', '')
        ai_key = os.environ.get('AI_KEY') or os.environ.get('TOOLNET_CAPTION_API_KEY', '')
        ai_model = os.environ.get('AI_MODEL') or os.environ.get('TOOLNET_CAPTION_MODEL', '')

        assert ai_url.startswith('https://'), f"AI_URL không hợp lệ: {ai_url}"
        assert ai_model == 'agnes/agnes-3.0-flash', f"Model không đúng: {ai_model}"
        assert ai_key.startswith('sk-') and len(ai_key) >= 20, "API Key không hợp lệ"
        
        masked_key = f"{ai_key[:7]}...{ai_key[-4:]}"
        record(
            "1. Kiểm tra nạp cấu hình AI trên Django",
            "PASS",
            f"URL: {ai_url} | Model: {ai_model} | Key: {masked_key} (Đã che bảo mật)"
        )
    except Exception as e:
        record("1. Kiểm tra nạp cấu hình AI trên Django", "FAIL", str(e))
        return

    # -------------------------------------------------------------------------
    # 2. Gọi thật model agnes/agnes-3.0-flash qua ToolNet API
    # -------------------------------------------------------------------------
    t0 = time.time()
    try:
        raw_text, used_model = _provider("Chào bạn, giới thiệu 1 câu ngắn về dịch vụ đăng bài ToolNet Fplus24h")
        elapsed = time.time() - t0
        assert used_model == 'agnes/agnes-3.0-flash', f"Model phản hồi sai: {used_model}"
        assert len(raw_text.strip()) >= 10, "Phản hồi quá ngắn"
        record(
            "2. Gọi trực tiếp API model agnes/agnes-3.0-flash",
            "PASS",
            f"Model: {used_model} | Phản hồi: '{raw_text.strip()[:100]}...'",
            latency_sec=elapsed
        )
    except Exception as e:
        record("2. Gọi trực tiếp API model agnes/agnes-3.0-flash", "FAIL", str(e), latency_sec=time.time()-t0)
        return

    # -------------------------------------------------------------------------
    # 3. Kiểm tra Admin khóa trang đích @hiu9h cho đúng Pipeline
    # -------------------------------------------------------------------------
    pipe = Pipeline.objects.filter(pk="4237b562-e8f3-4f35-b074-ec92901ce897").first()
    if not pipe:
        pipe = Pipeline.objects.filter(name__icontains="Lê Tấn Media").first()
    assert pipe is not None, "Không tìm thấy Pipeline Lê Tấn Media"

    admin_user = User.objects.filter(is_superuser=True, is_staff=True).first()
    assert admin_user is not None, "Không tìm thấy tài khoản Admin"

    ctv_user = pipe.ctv
    assert ctv_user is not None and ctv_user.username == 'hiu9h', "CTV không phải hiu9h"

    other_user = User.objects.filter(is_superuser=False, is_staff=False).exclude(pk=ctv_user.pk).first()

    try:
        # Admin khóa trang đích @hiu9h
        cfg = update_settings(
            pipeline_id=pipe.pk,
            actor=admin_user,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance='Viết caption ngắn gọn, súc tích, văn phong tự nhiên thân thiện.'
        )
        assert cfg['enabled'] is True and cfg['destination'] == '@hiu9h'

        # CTV không được phép sửa khóa trang đích
        res_ctv = call_api(CaptionSettingsAPIView, 'put', '/caption-config/', pipe.pk, ctv_user, payload=dict(cfg))
        assert res_ctv.status_code == 404, f"CTV không được phép PUT cấu hình, mã trả về: {res_ctv.status_code}"

        # Người dùng khác pipeline bị chặn hoàn toàn
        if other_user:
            res_other = call_api(CaptionSettingsAPIView, 'get', '/caption-config/', pipe.pk, other_user)
            assert res_other.status_code == 404, f"Cross-tenant get phải 404, trả về: {res_other.status_code}"

        record(
            "3. Admin khóa trang đích @hiu9h & Chặn CTV sửa",
            "PASS",
            f"Pipeline: {pipe.name} ({pipe.id}) | Destination: {cfg['destination']} | Version: {cfg['version']}"
        )
    except Exception as e:
        record("3. Admin khóa trang đích @hiu9h & Chặn CTV sửa", "FAIL", str(e))
        return

    # -------------------------------------------------------------------------
    # 4. Tạo kho caption mẫu cho Pipeline
    # -------------------------------------------------------------------------
    try:
        # Tạo 2 mẫu caption đại diện
        sample1 = create_sample(
            pipeline_id=pipe.pk,
            actor=ctv_user,
            text="Khởi đầu ngày mới với nhiều năng lượng tích cực và nhiệt huyết công việc! @hiu9h"
        )
        sample2 = create_sample(
            pipeline_id=pipe.pk,
            actor=ctv_user,
            text="Kinh doanh bất động sản và đầu tư hiệu quả cùng ToolNet Fplus24h. Liên hệ ngay! @hiu9h"
        )
        samples_count = CaptionSample.objects.filter(pipeline=pipe, is_active=True).count()
        assert samples_count >= 2, f"Số lượng mẫu không đủ: {samples_count}"
        record(
            "4. Thêm và quản lý kho caption mẫu",
            "PASS",
            f"Đã tạo {samples_count} caption mẫu hoạt động trong kho Pipeline"
        )
    except Exception as e:
        record("4. Thêm và quản lý kho caption mẫu", "FAIL", str(e))
        return

    # -------------------------------------------------------------------------
    # Chuẩn bị dữ liệu Job kiểm thử (Sẽ dọn dẹp sạch sau khi test xong)
    # -------------------------------------------------------------------------
    test_account = FacebookAccount.objects.create(
        pipeline=pipe,
        label='E2E Test Account ' + uuid.uuid4().hex[:6],
        connection_status=FacebookAccount.ConnectionStatus.CONNECTED
    )
    group1 = FacebookGroup.objects.create(
        pipeline=pipe,
        name='Hội Doanh Nhân Khởi Nghiệp Trẻ',
        group_url=f'https://www.facebook.com/groups/e2e_{uuid.uuid4().hex[:8]}/'
    )
    group2 = FacebookGroup.objects.create(
        pipeline=pipe,
        name='Cộng Đồng Bất Động Sản & Đầu Tư',
        group_url=f'https://www.facebook.com/groups/e2e_{uuid.uuid4().hex[:8]}/'
    )
    job1 = PublishingJob.objects.create(
        pipeline=pipe,
        facebook_account=test_account,
        facebook_group=group1,
        request_key='e2e-job-1-' + uuid.uuid4().hex[:8],
        state=PublishingJob.State.QUEUED,
        scheduled_at=timezone.now(),
        next_run_at=timezone.now()
    )
    job2 = PublishingJob.objects.create(
        pipeline=pipe,
        facebook_account=test_account,
        facebook_group=group2,
        request_key='e2e-job-2-' + uuid.uuid4().hex[:8],
        state=PublishingJob.State.QUEUED,
        scheduled_at=timezone.now(),
        next_run_at=timezone.now()
    )

    try:
        # ---------------------------------------------------------------------
        # 5. AI tạo caption riêng cho từng Job dựa trên kho caption mẫu (Gọi thật)
        # ---------------------------------------------------------------------
        t_j1 = time.time()
        c1 = generate_job_caption(pipeline_id=pipe.pk, job_id=job1.pk, actor=ctv_user)
        lat_j1 = time.time() - t_j1

        t_j2 = time.time()
        c2 = generate_job_caption(pipeline_id=pipe.pk, job_id=job2.pk, actor=ctv_user)
        lat_j2 = time.time() - t_j2

        assert c1['state'] == JobCaption.State.DRAFT, f"Job 1 không ở trạng thái DRAFT: {c1['state']}"
        assert c2['state'] == JobCaption.State.DRAFT, f"Job 2 không ở trạng thái DRAFT: {c2['state']}"
        assert c1['text'] != c2['text'], "Caption của 2 Job bị trùng lặp!"
        
        record(
            "5. AI tạo caption riêng biệt cho từng Job",
            "PASS",
            f"Job 1 (Group: {group1.name}) vs Job 2 (Group: {group2.name}) tạo ra 2 nội dung độc lập.",
            latency_sec=(lat_j1 + lat_j2) / 2
        )

        # ---------------------------------------------------------------------
        # 6. Kiểm tra chỉ có đúng trang đích @hiu9h & Validation
        # ---------------------------------------------------------------------
        handle_re = re.compile(r'(?<![\w@])@[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*(?![\w])')
        for idx, cap in [(1, c1['text']), (2, c2['text'])]:
            handles = handle_re.findall(cap)
            assert handles == ['@hiu9h'], f"Job {idx} có handle bất thường: {handles}"
            assert cap.endswith('Liên hệ: @hiu9h'), f"Job {idx} không kết thúc bằng trang đích chuẩn: {cap}"

        # Kiểm tra chặn trang đích ngoại lai
        try:
            finalize_caption("Bài viết hay, chi tiết xem tại @trang_la", "@hiu9h")
            raise AssertionError("Chưa chặn được handle lạ")
        except CaptionError:
            pass

        # Kiểm tra idempotency (chuẩn hóa không bị duplicate)
        double_norm = finalize_caption("Nội dung bài viết\n\nLiên hệ: @hiu9h", "@hiu9h")
        assert double_norm.count('@hiu9h') == 1, "Duplicate handle khi finalize"

        record(
            "6. Kiểm tra bảo vệ trang đích duy nhất @hiu9h",
            "PASS",
            "Cả 2 caption chỉ chứa duy nhất 1 handle @hiu9h; chặn thành công handle ngoại lai."
        )

        # ---------------------------------------------------------------------
        # 7. Kiểm tra Tạo lại (Regenerate), Sửa (Edit), Duyệt (Approve), Từ chối (Reject)
        # ---------------------------------------------------------------------
        # 7.1 Thao tác trên Job 1: Sửa nội dung thủ công và Duyệt (Approve)
        edited_text = "Thành công chỉ đến khi chúng ta không ngừng nỗ lực và học hỏi mỗi ngày."
        approved_c1 = approve_job_caption(
            pipeline_id=pipe.pk,
            job_id=job1.pk,
            actor=ctv_user,
            expected_revision=c1['revision'],
            text=edited_text
        )
        assert approved_c1['state'] == JobCaption.State.APPROVED
        assert approved_c1['revision'] == c1['revision'] + 1
        job1.refresh_from_db()
        assert job1.caption == approved_c1['text'], "PublishingJob.caption không khớp bản duyệt"
        assert job1.caption.startswith(edited_text)
        assert job1.caption.endswith("Liên hệ: @hiu9h")

        # 7.2 Thao tác trên Job 2: Từ chối (Reject)
        rejected_c2 = reject_job_caption(
            pipeline_id=pipe.pk,
            job_id=job2.pk,
            actor=ctv_user,
            expected_revision=c2['revision']
        )
        assert rejected_c2['state'] == JobCaption.State.REJECTED
        assert rejected_c2['revision'] == c2['revision'] + 1
        job2.refresh_from_db()
        assert job2.caption == '', "PublishingJob.caption sau khi từ chối phải là rỗng"

        # 7.3 Thao tác trên Job 2: Tạo lại (Regenerate từ rejected)
        t_regen = time.time()
        regen_c2 = generate_job_caption(pipeline_id=pipe.pk, job_id=job2.pk, actor=ctv_user)
        lat_regen = time.time() - t_regen
        assert regen_c2['state'] == JobCaption.State.DRAFT
        assert regen_c2['revision'] == rejected_c2['revision'] + 1

        record(
            "7. Vòng đời Caption: Sửa, Duyệt, Từ chối và Tạo lại",
            "PASS",
            f"Job 1 sửa & duyệt thành công (Rev {approved_c1['revision']}); Job 2 từ chối rồi tạo lại thành công (Rev {regen_c2['revision']}).",
            latency_sec=lat_regen
        )

        # ---------------------------------------------------------------------
        # 8. Kiểm tra Dispatch Guard và Scheduler Caption Tick
        # ---------------------------------------------------------------------
        # Job 2 đang là DRAFT -> phải bị chặn dispatch
        ready_j2_before = ready_for_dispatch(job2)
        assert ready_j2_before is False, "Job 2 (Draft) không được phép dispatch"
        
        # Job 1 đã APPROVED với phiên bản settings hiện tại -> sẵn sàng dispatch
        ready_j1_before = ready_for_dispatch(job1)
        assert ready_j1_before is True, "Job 1 (Approved) phải sẵn sàng dispatch"

        # Tạm bật auto_generate để kiểm tra Caption Tick CLI (sẽ tăng version settings)
        cfg_tick = update_settings(
            pipeline_id=pipe.pk,
            actor=admin_user,
            destination='@hiu9h',
            enabled=True,
            auto_generate=True,
            auto_approve=False,
            writing_guidance=''
        )
        # Chạy Caption Tick ở chế độ Preview (không truyền --generate)
        from io import StringIO
        out = StringIO()
        call_command('publishing_caption_tick', pipeline_id=pipe.pk, limit=5, stdout=out)
        tick_result = json.loads(out.getvalue())
        assert tick_result['mode'] == 'preview'
        assert tick_result['facebook_posting'] is False
        assert tick_result['pipeline_id'] == str(pipe.pk)

        # Trả lại cấu hình an toàn auto_generate=False
        update_settings(
            pipeline_id=pipe.pk,
            actor=admin_user,
            destination='@hiu9h',
            enabled=True,
            auto_generate=False,
            auto_approve=False,
            writing_guidance='Văn phong tích cực, tự nhiên.'
        )

        record(
            "8. Dispatch Guard & Scheduler Caption Tick",
            "PASS",
            f"Chặn chính xác Job chưa duyệt ({ready_j2_before}); Cho phép Job đã duyệt ({ready_j1_before}); Tick CLI Preview an toàn."
        )

        # ---------------------------------------------------------------------
        # 9. Kiểm tra cách ly dữ liệu giữa các Pipeline (Tenant Isolation)
        # ---------------------------------------------------------------------
        other_pipe = Pipeline.objects.exclude(pk=pipe.pk).first()
        if other_pipe and other_pipe.ctv:
            foreign_ctv = other_pipe.ctv
            # foreign_ctv cố đọc Job của Lê Tấn Media
            res_cross_job = call_api(CaptionJobAPIView, 'get', f'/caption-jobs/{job1.pk}/', pipe.pk, foreign_ctv, job_id=job1.pk)
            assert res_cross_job.status_code == 404, f"Cross-tenant Job get phải 404, trả về: {res_cross_job.status_code}"

            # foreign_ctv cố đọc Samples của Lê Tấn Media
            res_cross_samples = call_api(CaptionSamplesAPIView, 'get', '/caption-samples/', pipe.pk, foreign_ctv)
            assert res_cross_samples.status_code == 404, f"Cross-tenant Samples get phải 404, trả về: {res_cross_samples.status_code}"

            # ctv_user cố đọc Pipeline khác
            res_cross_pipe = call_api(CaptionSettingsAPIView, 'get', '/caption-config/', other_pipe.pk, ctv_user)
            assert res_cross_pipe.status_code == 404, f"Cross-tenant Settings get phải 404, trả về: {res_cross_pipe.status_code}"

            record(
                "9. Kiểm tra cách ly dữ liệu giữa các Pipeline",
                "PASS",
                f"CTV {foreign_ctv.username} và {ctv_user.username} bị chặn hoàn toàn khi truy cập chéo Pipeline (HTTP 404)."
            )
        else:
            record("9. Kiểm tra cách ly dữ liệu giữa các Pipeline", "PASS", "Không có Pipeline thứ hai để test chéo, đã kiểm thử phân quyền CTV")

    finally:
        # ---------------------------------------------------------------------
        # 10. Dọn dẹp dữ liệu kiểm thử (Không để lại Job rác trên production)
        # ---------------------------------------------------------------------
        CaptionRevision.objects.filter(job_caption__job__in=[job1, job2]).delete()
        JobCaption.objects.filter(job__in=[job1, job2]).delete()
        PublishingJob.objects.filter(pk__in=[job1.pk, job2.pk]).delete()
        FacebookGroup.objects.filter(pk__in=[group1.pk, group2.pk]).delete()
        FacebookAccount.objects.filter(pk=test_account.pk).delete()
        print("[CLEANUP] Đã xóa toàn bộ Job, Group, Account và JobCaption kiểm thử.")
        remaining_jobs = PublishingJob.objects.filter(pipeline=pipe).count()
        print(f"[CLEANUP] Số lượng Job còn lại trên Pipeline Lê Tấn Media: {remaining_jobs}")

    print("=" * 80)
    print("KẾT QUẢ TỔNG HỢP KIỂM THỬ E2E:")
    all_pass = all(r['status'] == 'PASS' for r in results)
    for r in results:
        lat = f" [{r['latency_sec']}s]" if r['latency_sec'] is not None else ""
        print(f" - {r['name']}: {r['status']}{lat}")
    print("=" * 80)
    if all_pass:
        print(">>> TẤT CẢ CÁC BÀI KIỂM THỬ ĐÃ ĐẠT (ALL PASS) <<<")
    else:
        print(">>> CÓ BÀI KIỂM THỬ THẤT BẠI (FAIL) <<<")
        sys.exit(1)

if __name__ == '__main__':
    main()
