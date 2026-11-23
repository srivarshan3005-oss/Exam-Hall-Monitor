"""Build the release tree manifests and ZIP.   python scripts/make_release.py <source_dir> <output_zip>
Excludes secrets, databases, caches, virtual environments, node_modules, logs, backups, uploaded PDFs and outbox files."""
import hashlib, os, sys, zipfile
from pathlib import Path

EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".venv", "venv", "node_modules", ".git", ".gradle", "build"}
EXCLUDE_UNDER = ("backend/uploads/", "backend/backups/", "backend/outbox/", "backend/logs/", "backend/storage/")
KEEP = {".gitkeep"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".db", ".sqlite3", ".db-wal", ".db-shm", ".pid", ".log")
EXCLUDE_NAMES = {".env", ".env.production", "RELEASE_MANIFEST_SHA256.txt", "FILE_MANIFEST.txt"}


def files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if set(rel.split("/")[:-1]) & EXCLUDE_DIRS or p.name in EXCLUDE_NAMES:
            continue
        if p.name.endswith(EXCLUDE_SUFFIX) and p.name not in KEEP and not rel.startswith("backend/tests/fixtures/"):
            continue
        if any(rel.startswith(x) for x in EXCLUDE_UNDER) and p.name not in KEEP:
            continue
        yield rel, p


def main(src: str, out: str) -> None:
    root = Path(src).resolve()
    top = Path(out).stem
    items = list(files(root))
    sha = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  ./{rel}" for rel, p in items]
    sizes = [f"{p.stat().st_size:>10}  ./{rel}" for rel, p in items]
    (root / "RELEASE_MANIFEST_SHA256.txt").write_text("\n".join(sha) + "\n", encoding="utf-8")
    (root / "FILE_MANIFEST.txt").write_text("\n".join(sizes) + "\n", encoding="utf-8")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel, p in items:
            z.write(p, f"{top}/{rel}")
        for name in ("RELEASE_MANIFEST_SHA256.txt", "FILE_MANIFEST.txt"):
            z.write(root / name, f"{top}/{name}")
    print(f"{len(items) + 2} files -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
