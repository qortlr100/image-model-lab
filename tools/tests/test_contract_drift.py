from __future__ import annotations

import sys
from pathlib import Path, PurePosixPath

import contract_drift
import pytest


def writer(target: str, content: str) -> tuple[str, ...]:
    """A generator command that writes ``content`` to ``target``."""

    script = f"import pathlib; pathlib.Path({target!r}).write_text({content!r})"
    return (sys.executable, "-c", script)


def test_matching_output_reports_no_drift(tmp_path: Path) -> None:
    (tmp_path / "openapi.json").write_text("{}")
    contract = contract_drift.GeneratedContract(
        name="openapi",
        command=writer("openapi.json", "{}"),
        outputs=(PurePosixPath("openapi.json"),),
    )
    assert contract_drift.check_contract(tmp_path, contract) == []


def test_stale_committed_output_is_reported(tmp_path: Path) -> None:
    (tmp_path / "openapi.json").write_text("{}")
    contract = contract_drift.GeneratedContract(
        name="openapi",
        command=writer("openapi.json", '{"paths": {}}'),
        outputs=(PurePosixPath("openapi.json"),),
    )
    (message,) = contract_drift.check_contract(tmp_path, contract)
    assert "differs from a fresh generation" in message


def test_uncommitted_output_is_reported(tmp_path: Path) -> None:
    contract = contract_drift.GeneratedContract(
        name="openapi",
        command=writer("openapi.json", "{}"),
        outputs=(PurePosixPath("openapi.json"),),
    )
    (message,) = contract_drift.check_contract(tmp_path, contract)
    assert "generated but not committed" in message


def test_missing_output_is_reported(tmp_path: Path) -> None:
    contract = contract_drift.GeneratedContract(
        name="client",
        command=(sys.executable, "-c", "pass"),
        outputs=(PurePosixPath("client.ts"),),
    )
    (message,) = contract_drift.check_contract(tmp_path, contract)
    assert "was not produced by the generator" in message


def test_failing_generator_is_reported(tmp_path: Path) -> None:
    contract = contract_drift.GeneratedContract(
        name="client",
        command=(sys.executable, "-c", "import sys; sys.exit('generator exploded')"),
        outputs=(PurePosixPath("client.ts"),),
    )
    (message,) = contract_drift.check_contract(tmp_path, contract)
    assert "generator failed with exit code 1" in message
    assert "generator exploded" in message


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
