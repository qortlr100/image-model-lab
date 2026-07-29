from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest
import repo_policy


def make_file(
    name: str, content: bytes = b"", *, size: int | None = None
) -> repo_policy.RepositoryFile:
    return repo_policy.RepositoryFile(
        path=PurePosixPath(name),
        size=len(content) if size is None else size,
        read_bytes=lambda: content,
    )


def rules(findings: list[repo_policy.Finding]) -> set[str]:
    return {finding.rule for finding in findings}


@pytest.mark.parametrize(
    "name",
    [
        "models/anima.safetensors",
        "checkpoints/epoch-1.ckpt",
        "packages/python/domain/weights.pt",
        "quantized.gguf",
    ],
)
def test_model_weights_are_rejected_anywhere(name: str) -> None:
    assert rules(repo_policy.check_file(make_file(name))) == {"weight-artifact"}


def test_dataset_image_is_rejected() -> None:
    assert rules(repo_policy.check_file(make_file("datasets/inbox/001.png"))) == {"media-artifact"}


def test_small_documentation_image_is_allowed() -> None:
    assert repo_policy.check_file(make_file("docs/adr/flow.png", b"tiny")) == []


def test_oversized_documentation_image_is_rejected() -> None:
    file = make_file("docs/adr/flow.png", size=repo_policy.MAX_TRACKED_FILE_BYTES + 1)
    assert rules(repo_policy.check_file(file)) == {"file-size"}


def test_video_is_rejected_even_under_docs() -> None:
    assert rules(repo_policy.check_file(make_file("docs/demo.mp4"))) == {"media-artifact"}


def test_file_over_the_size_limit_is_rejected() -> None:
    file = make_file("packages/typescript/api-client/src/index.ts", size=2 * 1024 * 1024)
    findings = repo_policy.check_file(file)
    assert rules(findings) == {"file-size"}
    assert "2097152 bytes" in findings[0].message


def test_size_limit_is_inclusive() -> None:
    file = make_file("notes.txt", size=repo_policy.MAX_TRACKED_FILE_BYTES)
    assert repo_policy.check_file(file) == []


def test_key_material_is_rejected() -> None:
    assert rules(repo_policy.check_file(make_file("ops/dev/server.pem"))) == {"credential-file"}


def test_environment_file_is_rejected_but_the_example_is_allowed() -> None:
    assert rules(repo_policy.check_file(make_file("ops/dev/.env.local"))) == {"credential-file"}
    assert repo_policy.check_file(make_file("ops/dev/.env.example", b"API_TOKEN=")) == []


@pytest.mark.parametrize(
    "line",
    [
        'api_key = "sk-abcdefghijklmnopqrstuvwxyz0123"',  # repo-policy: allow-secret
        "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",  # repo-policy: allow-secret
        "-----BEGIN OPENSSH PRIVATE KEY-----",  # repo-policy: allow-secret
        "hf_abcdefghijklmnopqrstuvwxyz0123456789",  # repo-policy: allow-secret
        'password: "hunter2hunter2"',  # repo-policy: allow-secret
    ],
)
def test_secret_like_lines_are_reported(line: str) -> None:
    findings = repo_policy.check_file(make_file("services/api/config.py", line.encode()))
    assert rules(findings) == {"secret"}
    assert findings[0].line == 1


def test_secret_finding_reports_the_line_number() -> None:
    content = (
        b"first\nsecond\nAWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE\n"  # repo-policy: allow-secret
    )
    findings = repo_policy.check_file(make_file("services/api/config.py", content))
    assert [finding.line for finding in findings] == [3]


def test_marked_line_is_not_reported() -> None:
    content = b"AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE  # repo-policy: allow-secret\n"
    assert repo_policy.check_file(make_file("services/api/config.py", content)) == []


def test_ordinary_source_is_not_flagged() -> None:
    content = b"def token_count(text: str) -> int:\n    return len(text.split())\n"
    assert repo_policy.check_file(make_file("packages/python/domain/src/tokens.py", content)) == []


def test_binary_content_is_not_scanned_for_secrets() -> None:
    content = b"\x00\x01AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"  # repo-policy: allow-secret
    assert repo_policy.check_file(make_file("apps/web/public/favicon.ico", content)) == []


def test_finding_renders_path_and_line() -> None:
    finding = repo_policy.Finding(PurePosixPath("a/b.py"), "secret", "boom", line=7)
    assert finding.render() == "a/b.py:7: [secret] boom"
    assert repo_policy.Finding(PurePosixPath("a/b.pt"), "weight-artifact", "boom").render() == (
        "a/b.pt: [weight-artifact] boom"
    )


def test_check_files_collects_every_violation() -> None:
    findings = repo_policy.check_files(
        [make_file("a/model.safetensors"), make_file("b/notes.md", b"fine"), make_file("c/key.pem")]
    )
    assert rules(findings) == {"weight-artifact", "credential-file"}


def test_this_repository_passes_its_own_policy() -> None:
    repo_root = repo_policy.repository_root()
    files = repo_policy.tracked_files(repo_root)
    assert files, "expected tracked files in the checkout"
    assert repo_policy.check_files(files) == []


def test_main_reports_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert repo_policy.main([]) == 0
    assert "no violations" in capsys.readouterr().out


def git(repo_root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo_root), *args], check=True, capture_output=True)


def test_tracked_files_skips_paths_missing_from_the_worktree(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet", ".")
    (tmp_path / "kept.txt").write_text("kept\n")
    (tmp_path / "removed.txt").write_text("removed\n")
    git(tmp_path, "add", "kept.txt", "removed.txt")
    (tmp_path / "removed.txt").unlink()

    names = {str(file.path) for file in repo_policy.tracked_files(tmp_path)}
    assert names == {"kept.txt"}


def test_staged_files_reads_content_from_the_index(tmp_path: Path) -> None:
    git(tmp_path, "init", "--quiet", ".")
    (tmp_path / "staged.txt").write_text("indexed\n")
    git(tmp_path, "add", "staged.txt")
    (tmp_path / "staged.txt").write_text("worktree only\n")
    (tmp_path / "unstaged.txt").write_text("unstaged\n")

    files = repo_policy.staged_files(tmp_path)
    assert [str(file.path) for file in files] == ["staged.txt"]
    assert files[0].read_bytes() == b"indexed\n"
    assert files[0].size == len(b"indexed\n")
