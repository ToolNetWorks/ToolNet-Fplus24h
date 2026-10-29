import json

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST
from modules.pipelines.models import Pipeline


def json_error(message, status=400):
    return JsonResponse(
        {"success": False, "message": message},
        status=status,
    )


@require_GET
@never_cache
@ensure_csrf_cookie
def csrf_token(request):
    return JsonResponse({
        "success": True,
        "csrfToken": get_token(request),
    })


@require_POST
@never_cache
@csrf_protect
def unified_login(request):
    if request.content_type != "application/json":
        return json_error("Yêu cầu JSON.", 415)

    if len(request.body) > 4096:
        return json_error("Dữ liệu quá lớn.", 413)

    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return json_error("JSON không hợp lệ.")

    if not isinstance(data, dict):
        return json_error("Dữ liệu không hợp lệ.")

    username = data.get("username")
    password = data.get("password")

    if not isinstance(username, str) or not isinstance(password, str):
        return json_error("Thiếu thông tin đăng nhập.")

    username = username.strip()
    if not username or not password:
        return json_error("Thiếu tài khoản hoặc mật khẩu.")

    user = authenticate(
        request,
        username=username,
        password=password,
    )

    if user is None:
        return json_error("Thông tin đăng nhập không hợp lệ.", 401)

    if not user.is_active:
        return json_error("Tài khoản đã bị vô hiệu hóa.", 403)

    # 1. Admin must have BOTH is_staff=True and is_superuser=True
    if user.is_superuser and user.is_staff:
        role = "admin"
        redirect_to = "/"
        pipeline_id = None
    elif user.is_staff or user.is_superuser:
        # Invalid role combination: staff-only or superuser-only
        return json_error("Tài khoản không được cấp quyền.", 403)
    else:
        # 2. CTV: Must have an ACTIVE Pipeline belonging to them
        pipeline = Pipeline.objects.filter(
            ctv_id=user.pk,
        ).only("id", "status").first()

        if pipeline is None:
            return json_error("Tài khoản chưa được gắn Pipeline.", 403)

        if pipeline.status != Pipeline.Status.ACTIVE:
            return json_error("Pipeline đang bị khóa.", 403)

        role = "ctv"
        redirect_to = "/workspace/"
        pipeline_id = str(pipeline.pk)

    login(request, user)

    return JsonResponse({
        "success": True,
        "user": {
            "id": user.pk,
            "username": user.username,
            "role": role,
            "redirect_to": redirect_to,
            "pipeline_id": pipeline_id,
        },
    })


# Backward compatibility alias
admin_login = unified_login


@require_GET
@never_cache
def admin_me(request):
    user = request.user

    if not user.is_authenticated or not user.is_active:
        return json_error("Chưa đăng nhập.", 401)

    if not (user.is_superuser and user.is_staff):
        return json_error("Không có quyền quản trị.", 403)

    return JsonResponse({
        "success": True,
        "user": {
            "id": user.pk,
            "username": user.username,
            "role": "admin",
            "redirect_to": "/",
            "pipeline_id": None,
        },
    })


@require_POST
@never_cache
@csrf_protect
def admin_logout(request):
    logout(request)

    return JsonResponse({
        "success": True,
        "message": "Đăng xuất thành công.",
    })
