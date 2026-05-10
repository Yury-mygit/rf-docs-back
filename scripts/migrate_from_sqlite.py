"""Перенос таблиц workspaces + docs + doc_revisions из SQLite ln_dev → postgres docs_dev.

Запуск:
    docker run --rm -v ln_dev_db:/sqlite:ro -v $(pwd)/scripts:/app/scripts:ro \\
        --network shared -e PG_DSN=postgresql://... \\
        docs_dev-app:latest python -m scripts.migrate_from_sqlite
"""

import asyncio
import os
import sqlite3
import sys
import uuid

import asyncpg


def to_uuid(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        return uuid.UUID(bytes=v)
    return uuid.UUID(v)


WS_FIELDS = ["id", "title", "position", "created_at", "updated_at", "deleted_at"]
DOC_FIELDS_NO_PARENT = [
    "id", "workspace_id", "title", "body_md", "kind", "slug",
    "position", "created_at", "updated_at", "deleted_at",
]
REV_FIELDS = ["id", "doc_id", "title", "body_md", "author", "created_at"]


async def migrate(sqlite_path: str):
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    pg = await asyncpg.connect(dsn=os.environ["PG_DSN"])
    try:
        # workspaces
        rows = src.execute("SELECT * FROM workspaces").fetchall()
        nw = 0
        for r in rows:
            placeholders = ", ".join(f"${i + 1}" for i in range(len(WS_FIELDS)))
            cols = ", ".join(WS_FIELDS)
            await pg.execute(
                f"INSERT INTO workspaces ({cols}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING",
                to_uuid(r["id"]), r["title"], r["position"],
                r["created_at"], r["updated_at"], r["deleted_at"],
            )
            nw += 1

        # docs — двухпроходом из-за parent_id (дерево внутри таблицы)
        rows = src.execute("SELECT * FROM docs").fetchall()
        cols = ", ".join(DOC_FIELDS_NO_PARENT)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(DOC_FIELDS_NO_PARENT)))
        nd = 0
        for r in rows:
            await pg.execute(
                f"INSERT INTO docs ({cols}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING",
                to_uuid(r["id"]), to_uuid(r["workspace_id"]), r["title"],
                r["body_md"], r["kind"], r["slug"],
                r["position"], r["created_at"], r["updated_at"], r["deleted_at"],
            )
            nd += 1

        np_ = 0
        for r in rows:
            if r["parent_id"] is None:
                continue
            await pg.execute(
                "UPDATE docs SET parent_id = $1 WHERE id = $2",
                to_uuid(r["parent_id"]), to_uuid(r["id"]),
            )
            np_ += 1

        # doc_revisions
        rows = src.execute("SELECT * FROM doc_revisions").fetchall()
        cols = ", ".join(REV_FIELDS)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(REV_FIELDS)))
        nr = 0
        for r in rows:
            await pg.execute(
                f"INSERT INTO doc_revisions ({cols}) VALUES ({placeholders}) ON CONFLICT (id) DO NOTHING",
                to_uuid(r["id"]), to_uuid(r["doc_id"]), r["title"], r["body_md"],
                r["author"], r["created_at"],
            )
            nr += 1

        print(f"migrated: workspaces={nw} docs={nd} parent_links={np_} revisions={nr}")
    finally:
        await pg.close()
        src.close()


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "/sqlite/livenotes.db"
    asyncio.run(migrate(path))
