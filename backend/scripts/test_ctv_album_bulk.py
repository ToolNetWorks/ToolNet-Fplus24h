import uuid
from django.contrib.auth import get_user_model
from django.db import transaction
from rest_framework.test import (
    APIRequestFactory,
    force_authenticate,
)
from modules.albums.models import Album
from modules.pipelines.models import Pipeline
from modules.api.v1.albums.views import (
    AlbumCollectionAPIView,
)
from modules.api.v1.albums.bulk_views import (
    AlbumBulkStatusAPIView,
)
User = get_user_model()
factory = APIRequestFactory()
list_view = AlbumCollectionAPIView.as_view()
bulk_view = AlbumBulkStatusAPIView.as_view()
suffix = uuid.uuid4().hex[:10]
def make_pipeline(label):
    user = User.objects.create_user(
        username=f"albumtable_{label}_{suffix}",
        password=f"Test#{suffix}Aa1!",
    )
    pipeline = Pipeline.objects.create(
        name=f"Album Table {label} {suffix}",
        ctv=user,
        status=Pipeline.Status.ACTIVE,
    )
    return pipeline, user
def get_albums(pipeline, user, query=""):
    request = factory.get(
        f"/api/v1/pipelines/{pipeline.pk}/albums/"
        f"?page=1&page_size=25{query}"
    )
    force_authenticate(request, user=user)
    return list_view(
        request,
        pipeline_id=pipeline.pk,
    )
def bulk_status(pipeline, user, ids, enabled):
    request = factory.post(
        f"/api/v1/pipelines/{pipeline.pk}/"
        "albums/bulk-status/",
        {
            "album_ids": [str(pk) for pk in ids],
            "is_enabled": enabled,
        },
        format="json",
    )
    if user is not None:
        force_authenticate(request, user=user)
    return bulk_view(
        request,
        pipeline_id=pipeline.pk,
    )
with transaction.atomic():
    pipeline_a, ctv_a = make_pipeline("a")
    pipeline_b, ctv_b = make_pipeline("b")
    a1 = Album.objects.create(
        pipeline=pipeline_a,
        name="Campaign Alpha",
        is_enabled=True,
    )
    a2 = Album.objects.create(
        pipeline=pipeline_a,
        name="Campaign Beta",
        is_enabled=True,
    )
    foreign = Album.objects.create(
        pipeline=pipeline_b,
        name="Other Pipeline",
        is_enabled=True,
    )
    response = get_albums(pipeline_a, ctv_a)
    assert response.status_code == 200, response.data
    assert response.data["summary"]["total"] == 2
    assert response.data["summary"]["enabled"] == 2
    print("PIPELINE SUMMARY: PASS")
    response = get_albums(
        pipeline_a, ctv_a, "&search=Alpha"
    )
    assert response.status_code == 200
    assert response.data["pagination"]["total"] == 1
    print("ALBUM SEARCH: PASS")
    response = bulk_status(
        pipeline_a,
        ctv_a,
        [a1.pk, a2.pk],
        False,
    )
    assert response.status_code == 200, response.data
    assert response.data["data"]["updated_count"] == 2
    a1.refresh_from_db()
    a2.refresh_from_db()
    assert not a1.is_enabled
    assert not a2.is_enabled
    print("BULK DISABLE: PASS")
    response = get_albums(
        pipeline_a, ctv_a, "&enabled=false"
    )
    assert response.status_code == 200
    assert response.data["pagination"]["total"] == 2
    assert response.data["summary"]["total"] == 2
    print("ENABLED FILTER: PASS")
    response = bulk_status(
        pipeline_a,
        ctv_a,
        [a1.pk, a2.pk],
        True,
    )
    assert response.status_code == 200
    print("BULK ENABLE: PASS")
    response = bulk_status(
        pipeline_a,
        ctv_a,
        [a1.pk, foreign.pk],
        False,
    )
    assert response.status_code == 404
    a1.refresh_from_db()
    foreign.refresh_from_db()
    assert a1.is_enabled
    assert foreign.is_enabled
    print("CROSS-PIPELINE ALBUM: BLOCKED")
    print("ATOMIC UPDATE: PASS")
    response = bulk_status(
        pipeline_a,
        ctv_b,
        [a1.pk],
        False,
    )
    assert response.status_code == 404
    print("CROSS-PIPELINE CTV: BLOCKED")
    response = bulk_status(
        pipeline_a,
        ctv_a,
        [a1.pk, a1.pk],
        False,
    )
    assert response.status_code == 400
    print("DUPLICATE SELECTION: BLOCKED")
    response = bulk_status(
        pipeline_a,
        None,
        [a1.pk],
        False,
    )
    assert response.status_code in (401, 403)
    print("ANONYMOUS ACCESS: BLOCKED")
    transaction.set_rollback(True)
print("DATABASE CHANGES: ROLLED BACK")
print("CTV ALBUM API: PASSED")
