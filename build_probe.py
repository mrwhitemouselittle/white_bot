import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Target:
    goos: str
    goarch: str
    output: str


TARGETS = [
    Target("windows", "amd64", "kkprobe-windows-amd64.exe"),
    Target("windows", "arm64", "kkprobe-windows-arm64.exe"),
    Target("linux", "amd64", "kkprobe-linux-amd64"),
    Target("linux", "arm64", "kkprobe-linux-arm64"),
    Target("darwin", "amd64", "kkprobe-darwin-amd64"),
    Target("darwin", "arm64", "kkprobe-darwin-arm64"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build kkprobe binaries for all supported platforms.")
    parser.add_argument("--clean", action="store_true", help="Remove probe/kkprobe/bin before building.")
    parser.add_argument("--skip-current-check", action="store_true", help="Skip checking whether go is installed.")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    probe_dir = repo_root / "probe" / "kkprobe"
    output_dir = probe_dir / "bin"

    if not probe_dir.exists():
        print(f"probe directory not found: {probe_dir}", file=sys.stderr)
        return 1

    if not args.skip_current_check and shutil.which("go") is None:
        print("go command not found. Install Go first, then rerun this script.", file=sys.stderr)
        return 1

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    for target in TARGETS:
        output_path = output_dir / target.output
        print(f"building {target.goos}/{target.goarch} -> {output_path}")
        env = os.environ.copy()
        env["GOOS"] = target.goos
        env["GOARCH"] = target.goarch
        env["CGO_ENABLED"] = "0"

        result = subprocess.run(
            ["go", "build", "-trimpath", "-ldflags", "-s -w", "-o", str(output_path), "."],
            cwd=probe_dir,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            print(result.stdout, file=sys.stderr)
            print(f"build failed for {target.goos}/{target.goarch}", file=sys.stderr)
            return result.returncode

    print(f"done. binaries are in: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
