from pathlib import Path

import pytest

import vercel_build


def _repo(tmp_path: Path) -> Path:
    backend = tmp_path / "backend"
    backend.mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    return backend


def test_a_copy_from_the_deploy_script_is_kept(tmp_path: Path) -> None:
    backend = _repo(tmp_path)
    (backend / "frontend_dist").mkdir()
    (backend / "frontend_dist" / "index.html").write_text("script copy", encoding="utf-8")

    assert "skipped" in vercel_build.build_frontend(backend)
    assert (backend / "frontend_dist" / "index.html").read_text(encoding="utf-8") == "script copy"


def test_a_git_deploy_builds_the_frontend_and_copies_it_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = _repo(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        commands.append(command[1:])
        if command[1:] == ["run", "build"]:
            (cwd / "dist").mkdir()
            (cwd / "dist" / "index.html").write_text("built", encoding="utf-8")

    monkeypatch.setattr(vercel_build.shutil, "which", lambda _: "npm")
    monkeypatch.setattr(vercel_build.subprocess, "run", fake_run)

    vercel_build.build_frontend(backend)

    assert commands == [["ci", "--no-audit", "--no-fund"], ["run", "build"]]
    assert (backend / "frontend_dist" / "index.html").read_text(encoding="utf-8") == "built"


def test_without_the_frontend_folder_the_build_fails_with_the_fix(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()

    with pytest.raises(SystemExit, match="Include files outside the root"):
        vercel_build.build_frontend(backend)
