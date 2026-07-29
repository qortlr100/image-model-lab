from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from image_model_lab_domain import (
    ARTIFACT_TRANSITIONS,
    Artifact,
    ArtifactError,
    ArtifactNamespace,
    ArtifactReference,
    ArtifactState,
    ArtifactUri,
    MediaType,
    Sha256Digest,
)

REFERENCE = ArtifactReference(
    uri=ArtifactUri(namespace=ArtifactNamespace.ASSETS, key="original/c9/c9002e99"),
    digest=Sha256Digest("c9002e992258426720776d39ced66f985968a16488ef7e56716c7ff8b6c425aa"),
    size_bytes=20480,
    media_type=MediaType("image/png"),
)

_CHANGES: dict[str, tuple[ArtifactState, Callable[[Artifact], Artifact]]] = {
    "mark_available": (ArtifactState.AVAILABLE, lambda artifact: artifact.mark_available()),
    "mark_missing": (ArtifactState.MISSING, lambda artifact: artifact.mark_missing()),
    "quarantine": (ArtifactState.QUARANTINED, lambda artifact: artifact.quarantine()),
}

LEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in ArtifactState
    if target in ARTIFACT_TRANSITIONS[state]
]
ILLEGAL = [
    (state, name)
    for name, (target, _) in _CHANGES.items()
    for state in ArtifactState
    if target not in ARTIFACT_TRANSITIONS[state]
]


def artifact_in(state: ArtifactState) -> Artifact:
    return Artifact(id=uuid4(), reference=REFERENCE, state=state)


def test_a_new_artifact_is_pending_and_not_readable() -> None:
    artifact = Artifact(id=uuid4(), reference=REFERENCE)

    assert artifact.state is ArtifactState.PENDING
    assert not artifact.is_readable


def test_the_transition_table_covers_every_state() -> None:
    assert set(ARTIFACT_TRANSITIONS) == set(ArtifactState)


def test_the_transition_table_cannot_be_widened_at_runtime() -> None:
    """A lifecycle a caller can edit in place is not an invariant."""

    with pytest.raises(TypeError):
        ARTIFACT_TRANSITIONS[ArtifactState.QUARANTINED] = frozenset(  # type: ignore[index]
            {ArtifactState.AVAILABLE}
        )


def test_every_allowed_transition_has_a_method() -> None:
    """No entry in the table is unreachable through the artifact's API."""

    declared = {
        (state, target) for state, targets in ARTIFACT_TRANSITIONS.items() for target in targets
    }
    covered = {(state, _CHANGES[name][0]) for state, name in LEGAL}

    assert covered == declared


@pytest.mark.parametrize(("state", "name"), LEGAL)
def test_allowed_transition_keeps_identity_and_reference(state: ArtifactState, name: str) -> None:
    artifact = artifact_in(state)
    target, change = _CHANGES[name]

    moved = change(artifact)

    assert moved.state is target
    assert moved.id == artifact.id
    assert moved.reference == artifact.reference
    assert artifact.state is state


@pytest.mark.parametrize(("state", "name"), ILLEGAL)
def test_rejects_every_transition_outside_the_table(state: ArtifactState, name: str) -> None:
    artifact = artifact_in(state)
    _, change = _CHANGES[name]

    with pytest.raises(ArtifactError):
        change(artifact)


def test_publish_makes_verified_bytes_readable() -> None:
    published = Artifact(id=uuid4(), reference=REFERENCE).mark_available()

    assert published.state is ArtifactState.AVAILABLE
    assert published.is_readable


def test_a_repaired_artifact_becomes_readable_again() -> None:
    artifact = artifact_in(ArtifactState.AVAILABLE).mark_missing()

    assert not artifact.is_readable
    assert artifact.mark_available().is_readable


def test_quarantine_is_final_because_the_bytes_contradict_the_digest() -> None:
    quarantined = artifact_in(ArtifactState.AVAILABLE).quarantine()

    assert ARTIFACT_TRANSITIONS[ArtifactState.QUARANTINED] == frozenset()
    with pytest.raises(ArtifactError):
        quarantined.mark_available()


def test_is_immutable() -> None:
    artifact = artifact_in(ArtifactState.PENDING)

    with pytest.raises(AttributeError):
        artifact.state = ArtifactState.AVAILABLE  # type: ignore[misc]


def test_accepts_the_plain_string_spelling_of_a_state() -> None:
    artifact = Artifact(id=uuid4(), reference=REFERENCE, state="available")  # type: ignore[arg-type]

    assert artifact.state is ArtifactState.AVAILABLE


@pytest.mark.parametrize("state", ["", "deleted", "AVAILABLE", None, 1])
def test_rejects_a_value_that_is_not_a_state(state: object) -> None:
    with pytest.raises(ArtifactError):
        Artifact(id=uuid4(), reference=REFERENCE, state=state)  # type: ignore[arg-type]


@pytest.mark.parametrize("artifact_id", ["not-a-uuid", str(UUID(int=1)), 1, None])
def test_rejects_an_identifier_that_is_not_a_uuid(artifact_id: object) -> None:
    with pytest.raises(ArtifactError):
        Artifact(id=artifact_id, reference=REFERENCE)  # type: ignore[arg-type]


@pytest.mark.parametrize("reference", ["nas://assets/original/c9/c9002e99", None])
def test_rejects_a_reference_that_is_not_an_artifact_reference(reference: object) -> None:
    with pytest.raises(ArtifactError):
        Artifact(id=uuid4(), reference=reference)  # type: ignore[arg-type]
