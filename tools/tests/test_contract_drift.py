from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

import contract_drift
import pytest


def git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo_root), *args], check=True, capture_output=True)


def repo(tmp_path: Path) -> Path:
    """A git repository, since the drift baseline comes from the commit."""

    git(tmp_path, "init", "--quiet", ".")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    return tmp_path


def commit(repo_root: Path, name: str, content: str) -> None:
    (repo_root / name).write_text(content)
    git(repo_root, "add", name)
    git(repo_root, "commit", "--quiet", "-m", f"add {name}")


def writer(target: str, content: str) -> tuple[str, ...]:
    """A generator command that writes ``content`` to ``target``."""

    script = f"import pathlib; pathlib.Path({target!r}).write_text({content!r})"
    return (sys.executable, "-c", script)


def openapi(command: tuple[str, ...]) -> contract_drift.GeneratedContract:
    return contract_drift.GeneratedContract(
        name="openapi",
        command=command,
        outputs=(PurePosixPath("openapi.json"),),
    )


def test_matching_output_reports_no_drift(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    commit(repo_root, "openapi.json", "{}")
    assert contract_drift.check_contract(repo_root, openapi(writer("openapi.json", "{}"))) == []


def test_stale_committed_output_is_reported(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    commit(repo_root, "openapi.json", "{}")
    contract = openapi(writer("openapi.json", '{"paths": {}}'))
    (message,) = contract_drift.check_contract(repo_root, contract)
    assert "differs from a fresh generation" in message


def test_untracked_output_is_reported_even_when_it_matches(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    commit(repo_root, "README.md", "seed\n")
    (repo_root / "openapi.json").write_text("{}")

    (message,) = contract_drift.check_contract(repo_root, openapi(writer("openapi.json", "{}")))
    assert "generated but not committed" in message


def test_unstaged_regeneration_does_not_hide_a_stale_commit(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    commit(repo_root, "openapi.json", "{}")
    (repo_root / "openapi.json").write_text('{"paths": {}}')

    contract = openapi(writer("openapi.json", '{"paths": {}}'))
    (message,) = contract_drift.check_contract(repo_root, contract)
    assert "differs from a fresh generation" in message


def test_missing_output_is_reported(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    contract = contract_drift.GeneratedContract(
        name="client",
        command=(sys.executable, "-c", "pass"),
        outputs=(PurePosixPath("client.ts"),),
    )
    (message,) = contract_drift.check_contract(repo_root, contract)
    assert "was not produced by the generator" in message


def test_failing_generator_is_reported(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    contract = contract_drift.GeneratedContract(
        name="client",
        command=(sys.executable, "-c", "import sys; sys.exit('generator exploded')"),
        outputs=(PurePosixPath("client.ts"),),
    )
    (message,) = contract_drift.check_contract(repo_root, contract)
    assert "generator failed with exit code 1" in message
    assert "generator exploded" in message


def test_committed_bytes_reads_the_commit_not_the_worktree(tmp_path: Path) -> None:
    repo_root = repo(tmp_path)
    commit(repo_root, "openapi.json", "{}")
    (repo_root / "openapi.json").write_text("worktree only")

    assert contract_drift.committed_bytes(repo_root, PurePosixPath("openapi.json")) == b"{}"
    assert contract_drift.committed_bytes(repo_root, PurePosixPath("absent.json")) is None


def test_main_succeeds_with_an_empty_registry(capsys: pytest.CaptureFixture[str]) -> None:
    assert contract_drift.main(()) == 0
    assert "no generated contracts registered yet" in capsys.readouterr().out


def test_main_checks_the_registered_contracts() -> None:
    contract = contract_drift.GeneratedContract(
        name="client",
        command=(sys.executable, "-c", "pass"),
        outputs=(PurePosixPath("does-not-exist.ts"),),
    )
    assert contract_drift.main((contract,)) == 1
