import ast
import os
import re
import secrets
from pathlib import Path

from dotenv import dotenv_values

project_root = Path(
    "/root/toolnet-group-publisher"
)
env_path = project_root / ".env"
settings_path = project_root / "backend/config/settings.py"
marker = "# TOOLNET_SECURE_SECRET_KEY"

if not env_path.is_file():
    raise SystemExit("ERROR: Không tìm thấy .env")

content = settings_path.read_text()

if marker in content:
    print("SECRET_KEY CONFIG: ALREADY INSTALLED")
    raise SystemExit(0)

# Kiểm tra cấu trúc settings trước khi chỉnh sửa.
tree = ast.parse(content)
assignments = [
    node for node in tree.body
    if isinstance(node, ast.Assign)
    and any(
        isinstance(target, ast.Name)
        and target.id == "SECRET_KEY"
        for target in node.targets
    )
]

if len(assignments) != 1:
    raise SystemExit(
        "ERROR: Không xác định được SECRET_KEY gốc."
    )

assignment = assignments[0]

if assignment.lineno != assignment.end_lineno:
    raise SystemExit(
        "ERROR: SECRET_KEY nhiều dòng, cần kiểm tra thủ công."
    )

# Kiểm tra cấu hình môi trường.
env_content = env_path.read_text()
existing_keys = re.findall(
    r"(?m)^\s*DJANGO_SECRET_KEY\s*=",
    env_content,
)

if len(existing_keys) > 1:
    raise SystemExit("ERROR: DJANGO_SECRET_KEY bị khai báo trùng.")

existing_key = dotenv_values(env_path).get(
    "DJANGO_SECRET_KEY"
)

if existing_key:
    if len(existing_key) < 50 or existing_key.startswith(
        "django-insecure-"
    ):
        raise SystemExit(
            "ERROR: DJANGO_SECRET_KEY hiện tại không an toàn."
        )
    print("ENV SECRET_KEY: EXISTING SECURE KEY")
else:
    new_key = secrets.token_urlsafe(64)

    with env_path.open("a") as env:
        if env_content and not env_content.endswith("\n"):
            env.write("\n")
        env.write(f"DJANGO_SECRET_KEY={new_key}\n")

    print("ENV SECRET_KEY: GENERATED")

os.chmod(env_path, 0o600)

# Backup cấu hình.
backup = settings_path.with_name(
    "settings.py.bak-secret-key"
)
backup.write_text(content)
os.chmod(backup, 0o600)

# Loại bỏ giá trị key hardcode cũ.
lines = content.splitlines(keepends=True)
lines[assignment.lineno - 1] = 'SECRET_KEY = ""\n'
content = "".join(lines)

content += '''
# TOOLNET_SECURE_SECRET_KEY
import os as _toolnet_os
from dotenv import load_dotenv as _toolnet_load_dotenv
_toolnet_load_dotenv(BASE_DIR.parent / ".env")
SECRET_KEY = _toolnet_os.environ.get(
    "DJANGO_SECRET_KEY", ""
)
if (
    len(SECRET_KEY) < 50
    or SECRET_KEY.startswith("django-insecure-")
):
    raise RuntimeError(
        "DJANGO_SECRET_KEY missing or insecure"
    )
'''

settings_path.write_text(content)

print("HARDCODED KEY: REMOVED")
print("DJANGO SETTINGS: UPDATED")
print("SECRET_KEY SECURITY: CONFIGURED")
