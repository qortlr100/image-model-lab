import pytest
from image_model_lab_domain import (
    ArtifactNamespace,
    ArtifactReference,
    ArtifactReferenceError,
    ArtifactUri,
    ArtifactUriError,
    DigestError,
    MediaType,
    MediaTypeError,
    Sha256Digest,
)
from image_model_lab_domain.artifacts import SCHEMA_VERSION, SUPPORTED_SCHEMA_VERSIONS

DIGEST = "c9002e992258426720776d39ced66f985968a16488ef7e56716c7ff8b6c425aa"
PAYLOAD: dict[str, object] = {
    "schema_version": 1,
    "logical_uri": f"nas://assets/original/c9/{DIGEST}",
    "sha256": DIGEST,
    "size_bytes": 20480,
    "media_type": "image/png",
}


def reference() -> ArtifactReference:
    return ArtifactReference(
        uri=ArtifactUri(namespace=ArtifactNamespace.ASSETS, key=f"original/c9/{DIGEST}"),
        digest=Sha256Digest(DIGEST),
        size_bytes=20480,
        media_type=MediaType("image/png"),
    )


def test_serializes_to_the_versioned_shape() -> None:
    assert reference().to_json_dict() == PAYLOAD


def test_round_trips_through_json() -> None:
    assert ArtifactReference.from_json_dict(PAYLOAD).to_json_dict() == PAYLOAD
    assert ArtifactReference.from_json_dict(reference().to_json_dict()) == reference()


def test_writes_the_current_schema_version() -> None:
    assert SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS
    assert reference().to_json_dict()["schema_version"] == SCHEMA_VERSION


def test_is_immutable() -> None:
    with pytest.raises(AttributeError):
        reference().size_bytes = 1  # type: ignore[misc]


def test_accepts_an_empty_artifact() -> None:
    assert ArtifactReference.from_json_dict({**PAYLOAD, "size_bytes": 0}).size_bytes == 0


@pytest.mark.parametrize("size_bytes", [-1, -20480])
def test_rejects_a_negative_size(size_bytes: int) -> None:
    with pytest.raises(ArtifactReferenceError):
        ArtifactReference(
            uri=ArtifactUri.parse(f"nas://assets/original/c9/{DIGEST}"),
            digest=Sha256Digest(DIGEST),
            size_bytes=size_bytes,
            media_type=MediaType("image/png"),
        )


@pytest.mark.parametrize("field", sorted(PAYLOAD))
def test_rejects_a_missing_field(field: str) -> None:
    payload = {key: value for key, value in PAYLOAD.items() if key != field}

    with pytest.raises(ArtifactReferenceError):
        ArtifactReference.from_json_dict(payload)


def test_rejects_unknown_fields() -> None:
    """A stray key in a durable manifest is a typo or a newer writer."""

    with pytest.raises(ArtifactReferenceError):
        ArtifactReference.from_json_dict({**PAYLOAD, "mount_path": "/mnt/nas/assets"})


@pytest.mark.parametrize("version", [0, 2, 99])
def test_rejects_an_unsupported_schema_version(version: int) -> None:
    with pytest.raises(ArtifactReferenceError):
        ArtifactReference.from_json_dict({**PAYLOAD, "schema_version": version})


@pytest.mark.parametrize("version", ["1", 1.5, True, None])
def test_rejects_a_non_integer_schema_version(version: object) -> None:
    """``True == 1``, so a bool must not sneak through the version check."""

    with pytest.raises(ArtifactReferenceError):
        ArtifactReference.from_json_dict({**PAYLOAD, "schema_version": version})


@pytest.mark.parametrize("size_bytes", ["20480", 20480.5, True, None, [20480]])
def test_rejects_a_non_integer_size(size_bytes: object) -> None:
    with pytest.raises(ArtifactReferenceError):
        ArtifactReference.from_json_dict({**PAYLOAD, "size_bytes": size_bytes})


def test_reads_integral_floats_and_writes_them_back_as_integers() -> None:
    """JSON Schema judges a number by its value, so ``20480.0`` is an integer.

    A payload the published schema accepts has to stay readable, and what is
    written back is the canonical integer.
    """

    loaded = ArtifactReference.from_json_dict(
        {**PAYLOAD, "schema_version": 1.0, "size_bytes": 20480.0}
    )

    assert loaded.size_bytes == 20480
    assert type(loaded.size_bytes) is int
    assert loaded.to_json_dict() == PAYLOAD


@pytest.mark.parametrize("size_bytes", [20480.0, 1.5, True])
def test_direct_construction_rejects_a_non_integer_size(size_bytes: object) -> None:
    """A float never reaches storage: to_json_dict would break the contract."""

    with pytest.raises(ArtifactReferenceError):
        ArtifactReference(
            uri=ArtifactUri.parse(f"nas://assets/original/c9/{DIGEST}"),
            digest=Sha256Digest(DIGEST),
            size_bytes=size_bytes,  # type: ignore[arg-type]
            media_type=MediaType("image/png"),
        )


@pytest.mark.parametrize("field", ["logical_uri", "sha256", "media_type"])
def test_rejects_a_non_string_field(field: str) -> None:
    with pytest.raises(ArtifactReferenceError):
        ArtifactReference.from_json_dict({**PAYLOAD, field: 7})


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("logical_uri", "/mnt/nas/assets/original/c9", ArtifactUriError),
        ("logical_uri", "nas://assets/../../etc/passwd", ArtifactUriError),
        ("logical_uri", "nas://etc/passwd", ArtifactUriError),
        ("sha256", "not-a-digest", DigestError),
        ("media_type", "image/*", MediaTypeError),
    ],
)
def test_rejects_invalid_component_values(field: str, value: str, error: type[Exception]) -> None:
    with pytest.raises(error):
        ArtifactReference.from_json_dict({**PAYLOAD, field: value})
