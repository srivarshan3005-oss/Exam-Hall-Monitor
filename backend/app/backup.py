"""Backward-compatible module entry point for the Phase 8.2 verified backup service."""
import json
from .data_management import create_backup


def main():
    try:
        print(json.dumps(create_backup(), indent=2))
    except Exception as exc:
        raise SystemExit(f"Backup failed: {exc}") from exc


if __name__ == "__main__":
    main()
