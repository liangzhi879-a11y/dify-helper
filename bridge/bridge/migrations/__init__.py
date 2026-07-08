"""SQLite 迁移文件目录。

每次 schema 变更添加一个 v<N>_<description>.sql，启动时自动按版本号顺序应用。
"""

from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent


def list_migration_files() -> list[tuple[int, Path]]:
    """列出所有迁移文件，按版本号升序。

    Returns: [(version_int, file_path), ...]
    """
    files: list[tuple[int, Path]] = []
    for sql_file in sorted(_MIGRATIONS_DIR.glob("v*.sql")):
        # 文件名格式: v1_initial.sql → version=1
        try:
            version = int(sql_file.name.split("_", 1)[0][1:])
        except (ValueError, IndexError):
            continue
        files.append((version, sql_file))
    return files