def activate_neon_as_default(databases):
    """
    Neon PostgreSQL is the primary database.
    SQLite remains available for emergency rollback.
    """
    if "neon" not in databases:
        raise RuntimeError("Neon database chưa được cấu hình.")

    if "default" not in databases:
        raise RuntimeError("Default database không tồn tại.")

    # Preserve the original SQLite configuration.
    databases["legacy_sqlite"] = databases["default"].copy()

    # Switch Django's primary database to Neon.
    databases["default"] = databases["neon"].copy()

    return databases
