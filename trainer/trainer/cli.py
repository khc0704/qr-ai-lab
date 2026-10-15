"""`python -m trainer run` is the container entrypoint; the other commands help ops / CI."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trainer")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="run the job described by JOB_ID / JOB_TOKEN / BACKEND_URL")
    sub.add_parser("families", help="print registered model family ids")
    sub.add_parser("check", help="check which families are importable in this environment")
    args = parser.parse_args(argv)
    if args.cmd == "run":
        from trainer.runtime import run

        return run()
    from trainer.models import registry

    if args.cmd == "families":
        print("\n".join(registry.ids()))
        return 0
    ok = True
    for fid in registry.ids():
        missing = registry.missing_packages(fid)
        try:
            registry._load(fid, 0)
        except Exception as e:  # import error inside the family module
            missing.append(str(e))
        if missing:
            ok = False
            print(f"missing  {fid}: {', '.join(missing)}")
        else:
            print(f"ok       {fid}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
