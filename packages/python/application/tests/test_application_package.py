"""The application package states ports and carries no framework with them."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Protocol, get_type_hints

import pytest
from image_model_lab_application import (
    PACKAGE_NAME,
    ApplicationError,
    ArtifactRepository,
    DatasetSnapshotRepository,
    ExecutionJobRepository,
    RepositoryError,
    RunAttemptRepository,
)
from image_model_lab_domain import DomainError

APPLICATION_ROOT = Path(__file__).resolve().parent.parent / "src" / "image_model_lab_application"

PORTS = (
    ArtifactRepository,
    ExecutionJobRepository,
    RunAttemptRepository,
    DatasetSnapshotRepository,
)

ALLOWED_IMPORTS = frozenset(
    {
        "image_model_lab_application",
        "image_model_lab_domain",
        "__future__",
        "typing",
        "uuid",
    }
)
"""What a package of ports may import.

An adapter satisfies a protocol without importing it, so nothing here needs a
driver, a framework or an I/O module. The day one appears, the dependency has
started pointing outward.
"""


def test_package_name_is_stable() -> None:
    assert PACKAGE_NAME == "image-model-lab-application"


@pytest.mark.parametrize("port", PORTS, ids=lambda port: port.__name__)
def test_a_port_is_a_protocol(port: type) -> None:
    """A base class would make the adapter import the port and invert the arrow."""

    assert Protocol in port.__bases__


@pytest.mark.parametrize("port", PORTS, ids=lambda port: port.__name__)
def test_a_port_is_annotated(port: type) -> None:
    for name, method in vars(port).items():
        if name.startswith("_") or not callable(method):
            continue
        hints = get_type_hints(method)
        assert "return" in hints, f"{port.__name__}.{name} has no return annotation"


def test_a_repository_error_is_not_a_domain_error() -> None:
    """A refused write is not a broken rule, and a caller handles them apart."""

    assert issubclass(RepositoryError, ApplicationError)
    assert not issubclass(RepositoryError, DomainError)
    assert not issubclass(ApplicationError, DomainError)


@pytest.mark.parametrize(
    "source",
    sorted(APPLICATION_ROOT.rglob("*.py")),
    ids=lambda path: path.name,
)
def test_a_module_imports_only_the_domain_and_the_standard_library(source: Path) -> None:
    roots: set[str] = set()
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])

    forbidden = sorted(roots - ALLOWED_IMPORTS)
    assert not forbidden, (
        f"{source.name} imports {', '.join(forbidden)}; use cases and their ports depend on the "
        "domain, and infrastructure depends on them"
    )
