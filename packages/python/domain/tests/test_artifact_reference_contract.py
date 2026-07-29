"""The published schema, the committed fixture and the domain code must agree.

The schema in ``contracts/`` is what a future reader of a stored manifest has;
the domain code is what writes one. Checking both against the same fixture is
what keeps them from drifting apart.
"""

import json
from pathlib import Path
from typing import Any, Protocol, cast

import pytest
from image_model_lab_domain import ArtifactReference, ArtifactUri, MediaType, Sha256Digest
from jsonschema import Draft202012Validator

# packages/python/domain/tests/<this file> -> repository root
CONTRACTS = Path(__file__).resolve().parents[4] / "contracts"
SCHEMA_PATH = CONTRACTS / "schemas" / "artifact-reference-v1.schema.json"
EXAMPLE_PATH = CONTRACTS / "examples" / "artifact-reference-v1.example.json"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class SchemaValidator(Protocol):
    """The part of a jsonschema validator these tests use.

    ``jsonschema`` annotates these two methods loosely, which a strict type
    checker reports as partially unknown. Naming the shape here keeps the
    checker strict everywhere else in the module.
    """

    def validate(self, instance: object) -> None: ...

    def is_valid(self, instance: object) -> bool: ...


@pytest.fixture(scope="module")
def validator() -> SchemaValidator:
    schema = load(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    return cast(SchemaValidator, Draft202012Validator(schema))


def test_the_committed_fixture_passes_the_versioned_schema(
    validator: SchemaValidator,
) -> None:
    validator.validate(load(EXAMPLE_PATH))


def test_the_fixture_round_trips_through_the_domain_object() -> None:
    example = load(EXAMPLE_PATH)

    assert ArtifactReference.from_json_dict(example).to_json_dict() == example


def test_serialized_references_pass_the_versioned_schema(
    validator: SchemaValidator,
) -> None:
    references = [
        ArtifactReference(
            uri=ArtifactUri.parse(uri),
            digest=Sha256Digest("a" * 64),
            size_bytes=size_bytes,
            media_type=MediaType(media_type),
        )
        for uri, size_bytes, media_type in [
            ("nas://assets/original/aa/" + "a" * 64, 0, "image/png"),
            ("nas://datasets/0f7c/snapshots/91ab/manifest.json", 4096, "application/json"),
            ("nas://runs/training/91ab/attempts/2/train.log", 1048576, "text/plain"),
            ("nas://models/anima/v1.safetensors", 9663676416, "application/octet-stream"),
            (
                "nas://workflows/portrait/3.json",
                8192,
                "application/vnd.comfyui.workflow+json",
            ),
        ]
    ]

    for reference in references:
        validator.validate(reference.to_json_dict())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema_version": 2},
        {"schema_version": "1"},
        {"logical_uri": "/mnt/nas/assets/original/c9"},
        {"logical_uri": "nas://assets/../../etc/passwd"},
        {"logical_uri": "nas://etc/passwd"},
        {"logical_uri": "nas://assets/Original/c9"},
        {"sha256": "not-a-digest"},
        {"size_bytes": -1},
        {"size_bytes": 1.5},
        {"media_type": "image/*"},
        {"media_type": "text/plain; charset=utf-8"},
        {"mount_path": "/mnt/nas/assets"},
    ],
)
def test_the_schema_rejects_what_the_domain_rejects(
    validator: SchemaValidator, payload: dict[str, Any]
) -> None:
    """Every value the domain refuses must also fail the published schema."""

    example = load(EXAMPLE_PATH)
    candidate = {**example, **payload} if payload else {}

    assert not validator.is_valid(candidate)
    with pytest.raises(ValueError):
        ArtifactReference.from_json_dict(candidate)


def test_a_tolerated_digest_spelling_is_written_back_canonically(
    validator: SchemaValidator,
) -> None:
    """The reader tolerates more spellings than the schema publishes.

    ``Sha256Digest`` accepts an uppercase or ``sha256:`` prefixed digest so an
    older or hand-written payload still loads, but the schema publishes only
    the canonical lowercase hex, and that is what is written back.
    """

    example = load(EXAMPLE_PATH)
    tolerated: dict[str, Any] = {**example, "sha256": "SHA256:" + str(example["sha256"]).upper()}
    assert not validator.is_valid(tolerated)

    written = ArtifactReference.from_json_dict(tolerated).to_json_dict()

    validator.validate(written)
    assert written == example
