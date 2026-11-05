"""Поднимает локальный PostgreSQL (из пакета pgserver) и пишет DATABASE_URL в .env."""
import pathlib

import pgserver

root = pathlib.Path(__file__).resolve().parent
srv = pgserver.get_server(str(root / ".pgdata"), cleanup_mode=None)
try:
    srv.psql("CREATE DATABASE timebalance;")
except Exception:
    pass
uri = srv.get_uri(database="timebalance")

env_path = root / ".env"
if not env_path.exists():
    env_path.write_text((root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
lines = env_path.read_text(encoding="utf-8").splitlines()
out, found = [], False
for line in lines:
    if line.startswith("DATABASE_URL="):
        out.append("DATABASE_URL=" + uri)
        found = True
    else:
        out.append(line)
if not found:
    out.append("DATABASE_URL=" + uri)
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("READY " + uri)
