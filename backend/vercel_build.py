"""Vercel build step: put the built frontend in backend/frontend_dist for FastAPI to serve.

scripts/deploy-vercel.ps1 copies it in before uploading, so this step finds it and does nothing.
A deploy from Git has no copy (the folder is gitignored), so it is built here from ../frontend.
"""

import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent


def build_frontend(backend: Path = BACKEND) -> str:
    target = backend / "frontend_dist"
    frontend = backend.parent / "frontend"
    if (target / "index.html").is_file():
        return "frontend_dist already present (deploy script); frontend build skipped"
    if not (frontend / "package.json").is_file():
        raise SystemExit(
            "No ../frontend to build. In Vercel, turn on 'Include files outside the root "
            "directory in the Build Step' (Settings > Build and Deployment > Root Directory)."
        )
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is not available in the build image.")
    # Fixed commands in our own repository; nothing comes from user input.
    subprocess.run([npm, "ci", "--no-audit", "--no-fund"], cwd=frontend, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=frontend, check=True)  # noqa: S603
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(frontend / "dist", target)
    return f"frontend built and copied to {target}"


if __name__ == "__main__":
    sys.stdout.write(build_frontend() + "\n")
