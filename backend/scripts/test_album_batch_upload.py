import io
from unittest.mock import patch
from django.db import transaction
from PIL import Image
from modules.albums.models import Album, AlbumImage
from modules.albums.services.batch_upload import (
    upload_album_batch,
)
from modules.albums.services.r2_storage import R2StorageError
from modules.pipelines.models import Pipeline
class FakeR2:
    def __init__(self, fail_at=None):
        self.objects = {}
        self.count = 0
        self.fail_at = fail_at
    def put_object(self, **kwargs):
        self.count += 1
        if self.count == self.fail_at:
            raise RuntimeError("Simulated R2 error")
        self.objects[kwargs["Key"]] = kwargs["Body"]
    def delete_object(self, **kwargs):
        self.objects.pop(kwargs["Key"], None)
def make_image(name):
    buffer = io.BytesIO()
    Image.new(
        "RGB",
        (32, 32),
        (20, 100, 180),
    ).save(buffer, format="PNG")
    buffer.seek(0)
    buffer.name = name
    buffer.size = len(buffer.getvalue())
    return buffer
pipeline = Pipeline.objects.first()
assert pipeline is not None, "Pipeline not found"
initial_count = AlbumImage.objects.count()
with transaction.atomic():
    pipeline.status = Pipeline.Status.ACTIVE
    pipeline.save(update_fields=["status"])
    album = Album.objects.create(
        pipeline=pipeline,
        name="Batch Upload Test",
    )
    fake = FakeR2()
    with patch(
        "modules.albums.services.batch_upload.get_r2_client",
        return_value=(fake, "test-bucket"),
    ):
        records = upload_album_batch(
            pipeline_id=pipeline.pk,
            album_id=album.pk,
            files=[
                make_image("one.png"),
                make_image("two.png"),
            ],
        )
    assert len(records) == 2
    assert len(fake.objects) == 2
    assert all(
        record.upload_status == "ready"
        for record in records
    )
    assert all(
        record.mime_type == "image/webp"
        for record in records
    )
    print("MULTI IMAGE UPLOAD: PASS")
    print("WEBP CONVERSION: PASS")
    print("NEON METADATA: PASS")
    failed_r2 = FakeR2(fail_at=2)
    before = AlbumImage.objects.filter(
        album=album
    ).count()
    with patch(
        "modules.albums.services.batch_upload.get_r2_client",
        return_value=(failed_r2, "test-bucket"),
    ):
        try:
            upload_album_batch(
                pipeline_id=pipeline.pk,
                album_id=album.pk,
                files=[
                    make_image("three.png"),
                    make_image("four.png"),
                ],
            )
        except R2StorageError:
            print("R2 FAILURE: DETECTED")
        else:
            raise AssertionError(
                "Expected R2 failure"
            )
    after = AlbumImage.objects.filter(
        album=album
    ).count()
    assert before == after
    assert len(failed_r2.objects) == 0
    print("DATABASE ROLLBACK: PASS")
    print("R2 CLEANUP: PASS")
    transaction.set_rollback(True)
assert AlbumImage.objects.count() == initial_count
print("TEST DATA: ROLLED BACK")
print("ALBUM BATCH UPLOAD: PASSED")
