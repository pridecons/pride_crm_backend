# utils/migrations.py
import os
import re
from alembic import command
from alembic.config import Config

ALEMBIC_INI = os.getenv("ALEMBIC_INI", "alembic.ini")

def _is_empty_migration(path: str) -> bool:
    # very simple heuristic: if the file contains only "pass" (no op.create/op.alter/etc)
    try:
        with open(path, "r", encoding="utf-8") as f:
            s = f.read()
        return not re.search(r"\bop\.(create_|drop_|add_|alter_|execute|bulk_)", s)
    except Exception:
        return False

def run_migrations(dev_autogenerate: bool = False) -> None:
    cfg = Config(ALEMBIC_INI)

    if dev_autogenerate:
        # Create a new revision if there are diffs
        script = command.revision(cfg, message="auto", autogenerate=True)
        # script is an object with .path (in newer Alembic) or a string path in older versions
        path = getattr(script, "path", script)
        if _is_empty_migration(path):
            # delete empty revisions to avoid noise
            try:
                os.remove(path)
            except Exception:
                pass

    # Apply latest migrations
    command.upgrade(cfg, "head")
