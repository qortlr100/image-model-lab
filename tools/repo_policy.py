#!/usr/bin/env python3
"""Repository policy checks for tracked and staged files.

This repository stores code and small text manifests only. Images, model
weights, checkpoints, generated outputs and credentials belong on NAS or in a
secret manager, never in Git history.

Check every tracked file:

    python tools/repo_policy.py

Check only the staged changes, which is what the pre-commit hook installed by
``just install-hooks`` runs:

    python tools/repo_policy.py --mode staged

The module deliberately has no third-party dependency so the hook works before
``uv sync`` has run.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path, PurePosixPath

MAX_TRACKED_FILE_BYTES = 1024 * 1024

WEIGHT_SUFFIXES = frozenset(
    {".bin", ".ckpt", ".gguf", ".npy", ".npz", ".onnx", ".pt", ".pth", ".safetensors"}
)
IMAGE_SUFFIXES = frozenset(
    {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".psd", ".tif", ".tiff", ".webp"}
)
VIDEO_SUFFIXES = frozenset({".avi", ".mkv", ".mov", ".mp4", ".webm"})
CREDENTIAL_SUFFIXES = frozenset({".jks", ".key", ".p12", ".pem", ".pfx"})

DOCUMENTATION_ROOT = "docs"
"""Small illustrative assets are allowed here; the size rule still applies."""

ALLOW_SECRET_MARKER = "repo-policy: allow-secret"
"""A line carrying this marker is skipped by the secret rules."""

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private key block", re.compile(r"-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{34,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("provider API key", re.compile(r"\bsk-[A-Za-z0-9_-]{24,}\b")),
    (
        # The unquoted alternative is deliberately longer than the quoted one:
        # `password: postgres` in a dev compose file must stay clean while
        # `GITHUB_TOKEN=<long opaque value>` must not.
        "assigned credential",
        re.compile(
            # `GITHUB_TOKEN` is one word, so the keyword cannot be anchored
            # with \b on the left or an underscore-prefixed name never matches.
            r"(?i)(?:^|[^A-Za-z0-9])(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*"
            r"(?:[\"'][^\"'\s]{8,}[\"']|[A-Za-z0-9+/=_-]{16,}(?![A-Za-z0-9+/=_-]))"
        ),
    ),
)


@dataclass(frozen=True)
class RepositoryFile:
    """A repository-relative file with lazily read content."""

    path: PurePosixPath
    size: int
    read_bytes: Callable[[], bytes]


@dataclass(frozen=True)
class Finding:
    """A single policy violation."""

    path: PurePosixPath
    rule: str
    message: str
    line: int | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line is not None else str(self.path)
        return f"{location}: [{self.rule}] {self.message}"


def repository_root() -> Path:
    """Return the repository root of the checkout containing this file."""

    completed = subprocess.run(
        ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
    )
    return Path(completed.stdout.decode().strip())


def _git(repo_root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args], check=True, capture_output=True
    )
    return completed.stdout


def _split_null(raw: bytes) -> list[str]:
    return [entry.decode() for entry in raw.split(b"\0") if entry]


def tracked_files(repo_root: Path) -> list[RepositoryFile]:
    """List every file tracked at the current checkout, read from the worktree."""

    files: list[RepositoryFile] = []
    for name in _split_null(_git(repo_root, "ls-files", "-z")):
        absolute = repo_root / name
        if not absolute.is_file():
            continue
        files.append(
            RepositoryFile(
                path=PurePosixPath(name),
                size=absolute.stat().st_size,
                read_bytes=absolute.read_bytes,
            )
        )
    return files


def staged_files(repo_root: Path) -> list[RepositoryFile]:
    """List added or modified files in the index, read from the index."""

    files: list[RepositoryFile] = []
    changed = _split_null(
        _git(repo_root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    )
    for name in changed:
        blob = f":{name}"
        size = int(_git(repo_root, "cat-file", "-s", blob).decode().strip())
        files.append(
            RepositoryFile(
                path=PurePosixPath(name),
                size=size,
                read_bytes=partial(_git, repo_root, "cat-file", "blob", blob),
            )
        )
    return files


def _is_documentation_asset(path: PurePosixPath) -> bool:
    return path.parts[:1] == (DOCUMENTATION_ROOT,)


def _is_environment_file(path: PurePosixPath) -> bool:
    name = path.name
    if name == ".env.example":
        return False
    return name == ".env" or name.startswith(".env.")


def _check_path(file: RepositoryFile) -> list[Finding]:
    findings: list[Finding] = []
    suffix = file.path.suffix.lower()

    if suffix in WEIGHT_SUFFIXES:
        findings.append(
            Finding(
                file.path,
                "weight-artifact",
                f"model weights and checkpoints ({suffix}) belong on NAS, not in Git",
            )
        )
    elif suffix in VIDEO_SUFFIXES:
        findings.append(
            Finding(file.path, "media-artifact", f"video files ({suffix}) belong on NAS")
        )
    elif suffix in IMAGE_SUFFIXES and not _is_documentation_asset(file.path):
        findings.append(
            Finding(
                file.path,
                "media-artifact",
                f"image files ({suffix}) belong on NAS; only small {DOCUMENTATION_ROOT}/ "
                "assets may be committed",
            )
        )

    if suffix in CREDENTIAL_SUFFIXES:
        findings.append(
            Finding(
                file.path, "credential-file", f"key material ({suffix}) must never be committed"
            )
        )
    if _is_environment_file(file.path):
        findings.append(
            Finding(
                file.path,
                "credential-file",
                "environment files may hold secrets; commit .env.example instead",
            )
        )
    return findings


def _check_size(file: RepositoryFile, max_bytes: int) -> list[Finding]:
    if file.size <= max_bytes:
        return []
    return [
        Finding(
            file.path,
            "file-size",
            f"{file.size} bytes exceeds the {max_bytes} byte limit for tracked files",
        )
    ]


def _decode(content: bytes) -> str | None:
    if b"\0" in content:
        return None
    try:
        return content.decode()
    except UnicodeDecodeError:
        return None


def _check_secrets(file: RepositoryFile) -> list[Finding]:
    text = _decode(file.read_bytes())
    if text is None:
        return []

    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if ALLOW_SECRET_MARKER in line:
            continue
        for label, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                findings.append(
                    Finding(
                        file.path,
                        "secret",
                        f"looks like a committed {label}; move it to the deployment secret store",
                        line=number,
                    )
                )
    return findings


def check_file(file: RepositoryFile, *, max_bytes: int = MAX_TRACKED_FILE_BYTES) -> list[Finding]:
    """Return every policy violation for a single file."""

    findings = _check_path(file)
    findings.extend(_check_size(file, max_bytes))
    if file.size <= max_bytes:
        findings.extend(_check_secrets(file))
    return findings


def check_files(
    files: Iterable[RepositoryFile], *, max_bytes: int = MAX_TRACKED_FILE_BYTES
) -> list[Finding]:
    """Return every policy violation across the given files."""

    findings: list[Finding] = []
    for file in files:
        findings.extend(check_file(file, max_bytes=max_bytes))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check repository content policy.")
    parser.add_argument(
        "--mode",
        choices=("tracked", "staged"),
        default="tracked",
        help="check every tracked file (default) or only the staged changes",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_TRACKED_FILE_BYTES,
        help=f"maximum size of a tracked file in bytes (default {MAX_TRACKED_FILE_BYTES})",
    )
    args = parser.parse_args(argv)
    mode: str = args.mode
    max_bytes: int = args.max_bytes

    repo_root = repository_root()
    files = staged_files(repo_root) if mode == "staged" else tracked_files(repo_root)
    findings = check_files(files, max_bytes=max_bytes)

    if findings:
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        print(
            f"\n{len(findings)} repository policy violation(s) in {mode} files. "
            f"Add an intentional exception to {Path(__file__).name} only with a reason.",
            file=sys.stderr,
        )
        return 1

    print(f"repository policy: {len(files)} {mode} file(s) checked, no violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
