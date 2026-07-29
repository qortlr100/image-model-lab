import pytest
from image_model_lab_domain import ArtifactNamespace, ArtifactUri, ArtifactUriError
from image_model_lab_domain.artifacts import MAX_KEY_LENGTH, MAX_SEGMENT_LENGTH

DIGEST = "c9002e992258426720776d39ced66f985968a16488ef7e56716c7ff8b6c425aa"


@pytest.mark.parametrize(
    ("value", "namespace", "key"),
    [
        (
            f"nas://assets/original/c9/{DIGEST}",
            ArtifactNamespace.ASSETS,
            f"original/c9/{DIGEST}",
        ),
        (
            "nas://datasets/0f7c/snapshots/91ab/manifest.json",
            ArtifactNamespace.DATASETS,
            "0f7c/snapshots/91ab/manifest.json",
        ),
        (
            "nas://runs/training/91ab/attempts/2/train.log",
            ArtifactNamespace.RUNS,
            "training/91ab/attempts/2/train.log",
        ),
        ("nas://models/anima/v1.safetensors", ArtifactNamespace.MODELS, "anima/v1.safetensors"),
        ("nas://workflows/portrait/3.json", ArtifactNamespace.WORKFLOWS, "portrait/3.json"),
    ],
)
def test_parses_the_documented_layout(value: str, namespace: ArtifactNamespace, key: str) -> None:
    uri = ArtifactUri.parse(value)

    assert uri.namespace is namespace
    assert uri.key == key


def test_formats_back_to_the_parsed_value() -> None:
    value = f"nas://assets/original/c9/{DIGEST}"

    assert str(ArtifactUri.parse(value)) == value


def test_equal_uris_are_interchangeable() -> None:
    first = ArtifactUri.parse("nas://models/anima/v1.safetensors")
    second = ArtifactUri(namespace=ArtifactNamespace.MODELS, key="anima/v1.safetensors")

    assert first == second
    assert len({first, second}) == 1


def test_is_immutable() -> None:
    uri = ArtifactUri.parse("nas://models/anima/v1.safetensors")

    with pytest.raises(AttributeError):
        uri.key = "anima/v2.safetensors"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        "/mnt/nas/assets/original/c9",
        "/Volumes/nas/assets/original/c9",
        "C:/nas/assets/original/c9",
        "//nas-01/assets/original/c9",
        "file:///mnt/nas/assets/original/c9",
        "smb://nas-01/assets/original/c9",
        "nas:/mnt/assets/original/c9",
        "nas://",
        "nas://assets",
        "NAS://assets/original/c9",
        "nas:///mnt/nas/assets/original/c9",
        "nas://assets//mnt/nas/original/c9",
        "nas://assets/c:/original/c9",
        "nas://assets/original\\c9",
        "nas://assets/~/original/c9",
        "nas://assets/original/c9/",
        " nas://assets/original/c9",
    ],
)
def test_rejects_machine_paths_and_foreign_schemes(value: str) -> None:
    """A mount path or a host-specific address must not become a domain object."""

    with pytest.raises(ArtifactUriError):
        ArtifactUri.parse(value)


@pytest.mark.parametrize(
    "value",
    [
        "nas://assets/../../etc/passwd",
        "nas://assets/original/../../../etc/passwd",
        "nas://assets/original/./c9",
        "nas://assets/./original/c9",
        "nas://assets/..",
        "nas://assets/original/..%2f..%2fetc",
        "nas://assets/original/%2e%2e/c9",
        "nas://assets/original/%2f/c9",
    ],
)
def test_rejects_path_traversal(value: str) -> None:
    with pytest.raises(ArtifactUriError):
        ArtifactUri.parse(value)


@pytest.mark.parametrize(
    "value",
    [
        "nas://etc/passwd",
        "nas://Assets/original/c9",
        "nas://asset/original/c9",
        "nas://secrets/token",
        "nas://tmp/original/c9",
        "nas:///original/c9",
    ],
)
def test_rejects_unknown_namespaces(value: str) -> None:
    with pytest.raises(ArtifactUriError):
        ArtifactUri.parse(value)


@pytest.mark.parametrize(
    "key",
    [
        "Original/c9",
        "original/C9",
        "original/c 9",
        "original/c9?full=1",
        "original/c9#fragment",
        "original/.hidden",
        "original/-leading-dash",
        "original/c9\n",
        "original/\x00",
        "original/é",
        "original/c9:1",
    ],
)
def test_rejects_keys_outside_the_generated_identifier_grammar(key: str) -> None:
    with pytest.raises(ArtifactUriError):
        ArtifactUri(namespace=ArtifactNamespace.ASSETS, key=key)


@pytest.mark.parametrize(
    "key",
    [
        # One segment over the limit, then legal segments that together are
        # over the whole-key limit.
        "a" * (MAX_SEGMENT_LENGTH + 1),
        "/".join(["a" * MAX_SEGMENT_LENGTH] * (MAX_KEY_LENGTH // MAX_SEGMENT_LENGTH + 1)),
    ],
)
def test_rejects_oversized_keys(key: str) -> None:
    with pytest.raises(ArtifactUriError):
        ArtifactUri(namespace=ArtifactNamespace.ASSETS, key=key)


def test_direct_construction_validates_the_key() -> None:
    """Bypassing ``parse`` must not bypass the rules."""

    with pytest.raises(ArtifactUriError):
        ArtifactUri(namespace=ArtifactNamespace.ASSETS, key="../../etc/passwd")


def test_namespace_values_are_stable() -> None:
    assert [namespace.value for namespace in ArtifactNamespace] == [
        "assets",
        "datasets",
        "models",
        "runs",
        "workflows",
    ]
