#!/usr/bin/env python3
"""Generated contract drift check.

The API OpenAPI document is the source for the generated TypeScript client, and
durable JSON manifests are versioned schemas. Every generated file must be
committed and must be byte-identical to a fresh regeneration, so a reviewer
never has to guess whether a checked-in artifact is current.

The generators arrive with M1-04. Until then ``GENERATED_CONTRACTS`` is empty
and this check reports that there is nothing to verify; the runner below is
already the mechanism CI will use once the first entry is registered.

    python tools/contract_drift.py
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class GeneratedContract:
    """A generator command and the files it is expected to produce."""

    name: str
    command: tuple[str, ...]
    outputs: tuple[PurePosixPath, ...]


GENERATED_CONTRACTS: tuple[GeneratedContract, ...] = ()
"""Registry of generated contracts. M1-04 adds the OpenAPI and client entries."""


def repository_root() -> Path:
    completed = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
    )
    return Path(completed.stdout.decode().strip())


def _snapshot(
    repo_root: Path, outputs: tuple[PurePosixPath, ...]
) -> dict[PurePosixPath, bytes | None]:
    snapshot: dict[PurePosixPath, bytes | None] = {}
    for output in outputs:
        absolute = repo_root / output
        snapshot[output] = absolute.read_bytes() if absolute.is_file() else None
    return snapshot


def check_contract(repo_root: Path, contract: GeneratedContract) -> list[str]:
    """Regenerate a contract and return one message per drifted or missing output."""

    before = _snapshot(repo_root, contract.outputs)
    completed = subprocess.run(
        list(contract.command), cwd=repo_root, check=False, capture_output=True
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip()
        return [
            f"{contract.name}: generator failed with exit code {completed.returncode}\n{detail}"
        ]

    after = _snapshot(repo_root, contract.outputs)
    messages: list[str] = []
    for output in contract.outputs:
        if after[output] is None:
            messages.append(f"{contract.name}: {output} was not produced by the generator")
        elif before[output] is None:
            messages.append(f"{contract.name}: {output} is generated but not committed")
        elif before[output] != after[output]:
            messages.append(f"{contract.name}: {output} differs from a fresh generation")
    return messages


def main(contracts: tuple[GeneratedContract, ...] = GENERATED_CONTRACTS) -> int:
    if not contracts:
        print("contract drift: no generated contracts registered yet")
        return 0

    repo_root = repository_root()
    messages: list[str] = []
    for contract in contracts:
        messages.extend(check_contract(repo_root, contract))

    if messages:
        for message in messages:
            print(message, file=sys.stderr)
        print(
            "\nRegenerate the contracts and commit the result.",
            file=sys.stderr,
        )
        return 1

    print(f"contract drift: {len(contracts)} contract(s) match a fresh generation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
