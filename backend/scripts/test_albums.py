from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from modules.albums.models import Album, AlbumImage
from modules.pipelines.models import Pipeline
pipeline = Pipeline.objects.first()
assert pipeline is not None, "Pipeline not found"
initial_albums = Album.objects.count()
initial_images = AlbumImage.objects.count()
with transaction.atomic():
    album = Album(
        pipeline=pipeline,
        name=" Album Test ",
        description="Ảnh thử nghiệm",
    )
    album.full_clean()
    album.save()
    assert album.name == "Album Test"
    assert album.pipeline_id == pipeline.pk
    print("CREATE ALBUM: PASS")
    print("PIPELINE OWNERSHIP: PASS")
    image = AlbumImage(
        album=album,
        original_filename="test-image.jpg",
        upload_status=AlbumImage.UploadStatus.PENDING,
    )
    image.full_clean()
    image.save()
    assert image.album_id == album.pk
    assert image.storage_key is None
    print("CREATE IMAGE RECORD: PASS")
    print("PENDING IMAGE WITHOUT FILE: PASS")
    image.upload_status = AlbumImage.UploadStatus.READY
    try:
        image.full_clean()
    except ValidationError:
        print("INVALID READY IMAGE: BLOCKED")
    else:
        raise AssertionError(
            "READY image without storage metadata was accepted"
        )
    try:
        album.delete()
    except ProtectedError:
        print("ALBUM WITH IMAGES: PROTECTED")
    else:
        raise AssertionError(
            "Album with images was deleted"
        )
    image.refresh_from_db()
    assert image.upload_status == "pending"
    transaction.set_rollback(True)
assert Album.objects.count() == initial_albums
assert AlbumImage.objects.count() == initial_images
print("DATABASE CHANGES: ROLLED BACK")
print("ALBUM MODELS TEST: PASSED")
