from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shorts_automation.pipeline import run_pipeline  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="영상만 생성하고 업로드는 하지 않습니다.")
    parser.add_argument("--force", action="store_true", help="오늘 이미 실행한 경우에도 강제로 재실행합니다.")
    args = parser.parse_args()
    result = run_pipeline(PROJECT_ROOT, dry_run=args.dry_run, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("skipped"):
        print(f"[SKIPPED] {result.get('reason', '')}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
