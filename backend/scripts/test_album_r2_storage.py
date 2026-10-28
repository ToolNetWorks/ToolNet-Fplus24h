import hashlib
import io
import uuid
from PIL import Image
from modules.albums.services.r2_storage import (
    ImageValidationError,
    get_r2_client,
    upload_album_image,
)
class FakeR2Client:
    def __init__(self):
        self.last_upload = None
    def put_object(self, **kwargs):
        self.last_upload = kwargs
def make_test_image():
    output = io.BytesIO()
    image = Image.new(
        "RGB",
        (32, 32),
        (40, 110, 180),
    )
    image.save(output, format="PNG")
    output.seek(0)
    return output
pipeline_id = uuid.uuid4()
album_id = uuid.uuid4()
print("=== LOCAL STORAGE SERVICE TEST ===")
fake = FakeR2Client()
result = upload_album_image(
    pipeline_id=pipeline_id,
    album_id=album_id,
    fileobj=make_test_image(),
    client=fake,
    bucket="unit-test",
)
assert result.mime_type == "image/webp"
assert result.width == 32
assert result.height == 32
assert result.storage_key.startswith(
    f"pipeline-albums/{pipeline_id}/{album_id}/"
)
assert result.storage_key.endswith(".webp")
uploaded = fake.last_upload
assert uploaded is not None
assert uploaded["ContentType"] == "image/webp"
assert uploaded["Body"][:4] == b"RIFF"
assert uploaded["Body"][8:12] == b"WEBP"
assert hashlib.sha256(
    uploaded["Body"]
).hexdigest() == result.sha256
print("PNG TO WEBP: PASS")
print("PIPELINE/ALBUM PATH: PASS")
print("SHA256 CHECK: PASS")
try:
    upload_album_image(
        pipeline_id=pipeline_id,
        album_id=album_id,
        fileobj=io.BytesIO(b"INVALID IMAGE"),
        client=fake,
        bucket="unit-test",
    )
except ImageValidationError:
    print("INVALID IMAGE: BLOCKED")
else:
    raise AssertionError("Invalid image accepted")
try:
    upload_album_image(
        pipeline_id="../invalid",
        album_id=album_id,
        fileobj=make_test_image(),
        client=fake,
        bucket="unit-test",
    )
except ImageValidationError:
    print("INVALID PATH: BLOCKED")
else:
    raise AssertionError("Invalid path accepted")
print("\n=== REAL CLOUDFLARE R2 TEST ===")
client, bucket = get_r2_client()
print("BUCKET:", bucket)
stored = None
test_passed = False
try:
    stored = upload_album_image(
        pipeline_id=pipeline_id,
        album_id=album_id,
        fileobj=make_test_image(),
        client=client,
        bucket=bucket,
    )
    print("REAL R2 UPLOAD: PASS")
    metadata = client.head_object(
        Bucket=bucket,
        Key=stored.storage_key,
    )
    assert metadata["ContentType"] == "image/webp"
    assert metadata["ContentLength"] == stored.file_size
    print("R2 METADATA: PASS")
    response = client.get_object(
        Bucket=bucket,
        Key=stored.storage_key,
    )
    body = response["Body"].read()
    response["Body"].close()
    assert hashlib.sha256(body).hexdigest() == stored.sha256
    print("R2 DOWNLOAD: PASS")
    print("R2 SHA256: PASS")
    test_passed = True
finally:
    if stored is not None:
        # Delete ONLY the unique object created by this test.
        try:
            client.delete_object(
                Bucket=bucket,
                Key=stored.storage_key,
            )
            print("R2 TEST OBJECT CLEANUP: REQUESTED")
        except Exception:
            print("R2 TEST OBJECT CLEANUP: FAILED")
            print("TEST OBJECT KEY:", stored.storage_key)
            raise
assert test_passed
print("ALBUM R2 STORAGE TEST: PASSED")
