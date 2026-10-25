"""Run from Task Scheduler daily. Each successful backup includes a restore test."""
import argparse
import logging
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.backups import backup, restore_file

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        if args.restore:
            if not args.destination:
                parser.error("--destination is required for restore")
            restore_file(args.restore, args.destination)
            print("Restore completed and verified")
        else:
            backup()
            print("Encrypted backup completed; restore, integrity and foreign keys verified")
    except Exception:
        logging.error("backup_operation_failed")
        raise SystemExit(1) from None
