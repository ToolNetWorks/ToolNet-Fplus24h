import hashlib
import io
import os
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import boto3
from botocore.config import Config
from dotenv import dotenv_values
from PIL import Image, ImageOps, UnidentifiedImageError
MAX_INPUT_BYTES = 10 * 1024 * 1024
MAX_OUTPUT_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 20_000_000
ENV_FILE = Path(__file__).resolve().parents[4] / ".env"
class ImageValidationError(ValueError):
    pass
class R2StorageError(RuntimeError):
    pass
@dataclass(frozen=True)
class StoredImage:
    storage_key: str
    mime_type: str
    file_size: int
    width: int
    height: int
    sha256: str
def read_r2_config():
    try:
        from modules.system_config.models import StorageConfig
        db_cfg = StorageConfig.objects.filter(is_active=True).first()
        if db_cfg and db_cfg.bucket_name and db_cfg.access_key_id:
            secret = db_cfg.get_secret_key()
            if secret:
                endpoint = db_cfg.endpoint_url
                if not endpoint and db_cfg.account_id:
                    endpoint = f"https://{db_cfg.account_id}.r2.cloudflarestorage.com"
                if endpoint and endpoint.startswith("https://"):
                    return {
                        "bucket": db_cfg.bucket_name,
                        "endpoint": endpoint,
                        "access_key": db_cfg.get_access_key(),
                        "secret_key": secret,
                    }
    except Exception:
        pass

    values = {
        **dotenv_values(ENV_FILE),
        **os.environ,
    }
    def first(*keys):
        for key in keys:
            value = values.get(key)
            if value:
                return str(value).strip()
        return None
    bucket = first(
        "R2_BUCKET",
        "R2_BUCKET_NAME",
        "CLOUDFLARE_R2_BUCKET",
        "S3_BUCKET",
        "S3_BUCKET_NAME",
    )
    access_key = first(
        "R2_ACCESS_KEY_ID",
        "R2_ACCESS_KEY",
        "CLOUDFLARE_R2_ACCESS_KEY_ID",
        "AWS_ACCESS_KEY_ID",
        "S3_ACCESS_KEY_ID",
    )
    secret_key = first(
        "R2_SECRET_ACCESS_KEY",
        "R2_SECRET_KEY",
        "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "S3_SECRET_ACCESS_KEY",
    )
    endpoint = first(
        "R2_ENDPOINT_URL",
        "R2_ENDPOINT",
        "CLOUDFLARE_R2_ENDPOINT",
        "S3_ENDPOINT_URL",
        "S3_ENDPOINT",
    )
    account_id = first(
        "R2_ACCOUNT_ID",
        "CLOUDFLARE_ACCOUNT_ID",
        "CF_ACCOUNT_ID",
    )
    if not endpoint and account_id:
        endpoint = (
            f"https://{account_id}.r2.cloudflarestorage.com"
        )
    if not all((bucket, access_key, secret_key, endpoint)):
        raise R2StorageError(
            "Thiếu cấu hình R2 trong .env."
        )
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise R2StorageError(
            "R2 endpoint phải là HTTPS hợp lệ."
        )
    return {
        "bucket": bucket,
        "endpoint": endpoint,
        "access_key": access_key,
        "secret_key": secret_key,
    }
def get_r2_client():
    config = read_r2_config()
    client = boto3.client(
        "s3",
        endpoint_url=config["endpoint"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name="auto",
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            connect_timeout=5,
            read_timeout=30,
            retries={"max_attempts": 2},
        ),
    )
    return client, config["bucket"]
def validate_and_convert_image(fileobj):
    if not hasattr(fileobj, "read"):
        raise ImageValidationError(
            "Dữ liệu upload không phải file."
        )
    raw = fileobj.read(MAX_INPUT_BYTES + 1)
    if not isinstance(raw, bytes):
        raise ImageValidationError(
            "Dữ liệu ảnh không hợp lệ."
        )
    if not raw:
        raise ImageValidationError("File ảnh rỗng.")
    if len(raw) > MAX_INPUT_BYTES:
        raise ImageValidationError(
            "Ảnh vượt quá giới hạn 10 MB."
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter(
                "error",
                Image.DecompressionBombWarning,
            )
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {
                    "JPEG",
                    "PNG",
                    "WEBP",
                }:
                    raise ImageValidationError(
                        "Chỉ hỗ trợ JPEG, PNG và WebP."
                    )
                width, height = source.size
                if (
                    width <= 0
                    or height <= 0
                    or width * height > MAX_PIXELS
                ):
                    raise ImageValidationError(
                        "Kích thước ảnh vượt giới hạn 20 MP."
                    )
                source.load()
                corrected = ImageOps.exif_transpose(source)
                if corrected.mode in ("RGBA", "LA"):
                    image = corrected.convert("RGBA")
                elif (
                    corrected.mode == "P"
                    and "transparency" in corrected.info
                ):
                    image = corrected.convert("RGBA")
                else:
                    image = corrected.convert("RGB")
                output = io.BytesIO()
                image.save(
                    output,
                    format="WEBP",
                    quality=85,
                    method=4,
                )
                optimized = output.getvalue()
                if len(optimized) > MAX_OUTPUT_BYTES:
                    raise ImageValidationError(
                        "Ảnh sau xử lý vượt quá 15 MB."
                    )
                return (
                    optimized,
                    image.width,
                    image.height,
                )
    except ImageValidationError:
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ImageValidationError(
            "Không thể đọc hoặc xử lý ảnh."
        ) from exc
def build_storage_key(*, pipeline_id, album_id):
    try:
        pipeline_uuid = uuid.UUID(str(pipeline_id))
        album_uuid = uuid.UUID(str(album_id))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ImageValidationError(
            "Pipeline ID hoặc Album ID không hợp lệ."
        ) from exc
    image_id = uuid.uuid4()
    return (
        f"pipeline-albums/{pipeline_uuid}/"
        f"{album_uuid}/{image_id}.webp"
    )
def upload_album_image(
    *,
    pipeline_id,
    album_id,
    fileobj,
    client=None,
    bucket=None,
    storage_key=None,
):
    # Validate identifiers before accessing the file or R2.
    generated_key = build_storage_key(
        pipeline_id=pipeline_id,
        album_id=album_id,
    )
    if storage_key is None:
        storage_key = generated_key
    else:
        prefix = generated_key.rsplit("/", 1)[0] + "/"
        if (
            not storage_key.startswith(prefix)
            or not storage_key.endswith(".webp")
        ):
            raise ImageValidationError(
                "Storage key không hợp lệ."
            )
        try:
            uuid.UUID(storage_key[len(prefix):-5])
        except (ValueError, TypeError) as exc:
            raise ImageValidationError(
                "Image UUID không hợp lệ."
            ) from exc
    optimized, width, height = (
        validate_and_convert_image(fileobj)
    )
    digest = hashlib.sha256(
        optimized
    ).hexdigest()
    if client is None or bucket is None:
        client, bucket = get_r2_client()
    try:
        client.put_object(
            Bucket=bucket,
            Key=storage_key,
            Body=optimized,
            ContentType="image/webp",
            CacheControl="private, max-age=0",
            Metadata={
                "sha256": digest,
            },
        )
    except Exception as exc:
        raise R2StorageError(
            "Không thể upload ảnh lên Cloudflare R2."
        ) from exc
    return StoredImage(
        storage_key=storage_key,
        mime_type="image/webp",
        file_size=len(optimized),
        width=width,
        height=height,
        sha256=digest,
    )
