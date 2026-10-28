import os
from pathlib import Path
import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
)
from dotenv import dotenv_values
env_path = Path(
    "/root/toolnet-group-publisher/.env"
)
if not env_path.is_file():
    raise SystemExit("ERROR: .env not found")
values = {
    **dotenv_values(env_path),
    **os.environ,
}
def get_config(*names):
    for name in names:
        value = values.get(name)
        if value:
            return name, str(value).strip()
    return None, None
print("=== R2 ENV VARIABLE NAMES ===")
for name in sorted(values):
    if (
        "R2" in name.upper()
        or name.startswith("AWS_")
        or name.startswith("S3_")
    ):
        print(f"{name}: SET" if values[name] else f"{name}: EMPTY")
account_name, account_id = get_config(
    "R2_ACCOUNT_ID",
    "CLOUDFLARE_ACCOUNT_ID",
    "CF_ACCOUNT_ID",
)
endpoint_name, endpoint = get_config(
    "R2_ENDPOINT_URL",
    "R2_ENDPOINT",
    "CLOUDFLARE_R2_ENDPOINT",
    "S3_ENDPOINT_URL",
    "S3_ENDPOINT",
)
access_name, access_key = get_config(
    "R2_ACCESS_KEY_ID",
    "R2_ACCESS_KEY",
    "CLOUDFLARE_R2_ACCESS_KEY_ID",
    "AWS_ACCESS_KEY_ID",
    "S3_ACCESS_KEY_ID",
)
secret_name, secret_key = get_config(
    "R2_SECRET_ACCESS_KEY",
    "R2_SECRET_KEY",
    "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "S3_SECRET_ACCESS_KEY",
)
bucket_name, bucket = get_config(
    "R2_BUCKET_NAME",
    "R2_BUCKET",
    "CLOUDFLARE_R2_BUCKET",
    "S3_BUCKET_NAME",
    "S3_BUCKET",
)
if not endpoint and account_id:
    endpoint = (
        f"https://{account_id}.r2.cloudflarestorage.com"
    )
required = {
    "endpoint/account_id": endpoint,
    "access_key": access_key,
    "secret_key": secret_key,
    "bucket": bucket,
}
missing = [
    name for name, value in required.items()
    if not value
]
if missing:
    print("CONFIG: INCOMPLETE")
    print("MISSING:", ", ".join(missing))
    raise SystemExit(1)
print("\n=== R2 CONNECTION ===")
print("CONFIG: COMPLETE")
print("BUCKET:", bucket)
print("ACCESS KEY: HIDDEN")
print("SECRET KEY: HIDDEN")
client = boto3.client(
    "s3",
    endpoint_url=endpoint,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    region_name="auto",
    config=Config(
        signature_version="s3v4",
        s3={
            "addressing_style": "path",
        },
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 2},
    ),
)
try:
    response = client.list_objects_v2(
        Bucket=bucket,
        MaxKeys=1,
        Prefix="pipeline-albums/",
    )
    print("R2 CONNECTION: PASS")
    print("BUCKET ACCESS: PASS")
    print("LIST OBJECTS: PASS")
    print("HTTP:", response["ResponseMetadata"]["HTTPStatusCode"])
    print("TEST MODE: READ ONLY")
except ClientError as exc:
    error = exc.response.get("Error", {})
    print("R2 CONNECTION: FAILED")
    print("ERROR CODE:", error.get("Code", "Unknown"))
    raise SystemExit(1)
except BotoCoreError as exc:
    print("R2 CONNECTION: FAILED")
    print("ERROR TYPE:", type(exc).__name__)
    raise SystemExit(1)
except Exception as exc:
    print("R2 CONNECTION: FAILED")
    print("ERROR TYPE:", type(exc).__name__)
    raise SystemExit(1)
