"""The domain package imports nothing that ties it to a machine.

Domain rules are the part of the system that has to be readable and testable
without a database, a filesystem, a network or a model. That property is easy
to state and easy to lose: one convenient ``import sqlalchemy`` for a type, or
one ``pathlib`` for a helper, and the rules can no longer be checked without
the thing they were supposed to be independent of.

So the check is an allowlist rather than a list of banned names. A blocklist
only refuses what someone already thought of, and the point is that nothing
new arrives quietly. Adding a name below is a deliberate decision about what
the domain is allowed to depend on -- it should be rare, and it should be
argued for in review rather than added to make an import work.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAIN_ROOT = Path(__file__).resolve().parent.parent / "src" / "image_model_lab_domain"

ALLOWED_IMPORTS = frozenset(
    {
        # The package itself.
        "image_model_lab_domain",
        # Language and typing machinery.
        "__future__",
        "typing",
        "enum",
        "types",
        # Pure data structures and value handling.
        "collections",
        "dataclasses",
        "datetime",
        "re",
        "urllib",
        "uuid",
    }
)
"""Top-level modules the domain may import.

Every entry is pure computation over values. Absent by design: anything that
reads the world (``os``, ``pathlib``, ``socket``, ``subprocess``), anything
that serializes to a wire format (``json``, ``pickle``), and every third-party
package -- a framework, a driver and a model library alike.
"""


def source_files() -> list[Path]:
    return sorted(DOMAIN_ROOT.rglob("*.py"))


def imported_roots(source: Path) -> set[str]:
    """Top-level module names imported anywhere in ``source``.

    The file is parsed rather than imported, so an import guarded by
    ``TYPE_CHECKING`` or hidden inside a function is seen too. A dependency
    that only exists for type checking is still a dependency of the package.
    """

    roots: set[str] = set()
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_the_package_has_source_files_to_check() -> None:
    """A check that silently found nothing to check is not a check."""

    assert source_files(), f"no domain sources under {DOMAIN_ROOT}"


@pytest.mark.parametrize("source", source_files(), ids=lambda path: path.name)
def test_a_domain_module_imports_only_allowed_modules(source: Path) -> None:
    forbidden = sorted(imported_roots(source) - ALLOWED_IMPORTS)

    assert not forbidden, (
        f"{source.relative_to(DOMAIN_ROOT)} imports {', '.join(forbidden)}. The domain package "
        "holds rules that must be checkable without a framework, a database, a filesystem or a "
        "model; persistence belongs in image-model-lab-persistence and I/O at a service edge."
    )


def test_sqlalchemy_and_alembic_are_not_allowed() -> None:
    """The allowlist is the mechanism, so name the case it exists for.

    M1-03 put SQLAlchemy and Alembic in the workspace, which is the moment
    this became something that could actually happen by accident.
    """

    assert "sqlalchemy" not in ALLOWED_IMPORTS
    assert "alembic" not in ALLOWED_IMPORTS
