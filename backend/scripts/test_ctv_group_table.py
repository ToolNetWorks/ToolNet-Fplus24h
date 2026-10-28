import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.pipelines.models import Pipeline
from modules.facebook_groups.models import FacebookGroup
from modules.api.v1.facebook_groups.views import (
    FacebookGroupCollectionAPIView,
)
from modules.api.v1.facebook_groups.bulk_views import (
    FacebookGroupBulkStatusAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
list_view = FacebookGroupCollectionAPIView.as_view()
bulk_view = FacebookGroupBulkStatusAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
def make_pipeline(label):
    user = User.objects.create_user(
        username=f"grptable_{label}_{suffix}",
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Group Table {label} {suffix}",
        ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return pipeline, user
def create_group(pipeline, name, key, enabled=True):
    return FacebookGroup.objects.create(
        pipeline=pipeline,
        name=name,
        group_url=f"https://www.facebook.com/groups/{key}/",
        is_enabled=enabled,
    )
def list_request(pipeline, user, query=""):
    request = factory.get(
        f"/api/v1/pipelines/{pipeline.pk}/facebook-groups/"
        f"?page=1&page_size=25{query}"
    )
    force_authenticate(request, user=user)
    return list_view(request, pipeline_id=pipeline.pk)
def bulk_request(pipeline, user, ids, enabled):
    request = factory.post(
        f"/api/v1/pipelines/{pipeline.pk}/"
        "facebook-groups/bulk-status/",
        {
            "group_ids": [str(value) for value in ids],
            "is_enabled": enabled,
        },
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return bulk_view(request, pipeline_id=pipeline.pk)
with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    group_a1 = create_group(
        pipeline_a, "Group A1", f"groupa1{suffix}"
    )
    group_a2 = create_group(
        pipeline_a, "Group A2", f"groupa2{suffix}"
    )
    group_b = create_group(
        pipeline_b, "Group B", f"groupb{suffix}"
    )
    group_a2.verification_status = "verified"
    group_a2.save()
    response = list_request(pipeline_a, ctv_a)
    assert response.status_code == 200, response.data
    assert response.data["summary"]["total"] == 2
    assert response.data["summary"]["enabled"] == 2
    assert response.data["summary"]["verified"] == 1
    print("PIPELINE GROUP SUMMARY: PASS")
    response = list_request(
        pipeline_a,
        ctv_a,
        "&verification_status=verified",
    )
    assert response.status_code == 200, response.data
    assert response.data["pagination"]["total"] == 1
    assert response.data["data"][0]["id"] == str(group_a2.pk)
    print("VERIFICATION FILTER: PASS")
    response = bulk_request(
        pipeline_a, ctv_a,
        [group_a1.pk, group_a2.pk],
        False,
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["updated_count"] == 2
    group_a1.refresh_from_db()
    group_a2.refresh_from_db()
    assert not group_a1.is_enabled
    assert not group_a2.is_enabled
    print("BULK DISABLE: PASS")
    response = bulk_request(
        pipeline_a, ctv_a,
        [group_a1.pk, group_a2.pk],
        True,
    )
    assert response.status_code == 200, response.data
    print("BULK ENABLE: PASS")
    # Foreign Group included: none may change.
    response = bulk_request(
        pipeline_a, ctv_a,
        [group_a1.pk, group_b.pk],
        False,
    )
    assert response.status_code == 404, response.data
    group_a1.refresh_from_db()
    assert group_a1.is_enabled
    print("CROSS-PIPELINE BULK: BLOCKED")
    print("ALL-OR-NOTHING UPDATE: PASS")
    response = bulk_request(
        pipeline_a, ctv_b,
        [group_a1.pk],
        False,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE CTV: BLOCKED")
    response = bulk_request(
        pipeline_a, ctv_a,
        [group_a1.pk, group_a1.pk],
        False,
    )
    assert response.status_code == 400
    print("DUPLICATE SELECTION: BLOCKED")
    response = bulk_request(
        pipeline_a, None,
        [group_a1.pk],
        False,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS ACCESS: BLOCKED")
    transaction.set_rollback(True)
print("DATABASE CHANGES: ROLLED BACK")
print("CTV GROUP TABLE API: PASSED")
