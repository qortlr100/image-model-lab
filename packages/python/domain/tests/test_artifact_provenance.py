from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from image_model_lab_domain import ArtifactProvenance, ArtifactProvenanceError, ProvenanceKind
from image_model_lab_domain.artifacts.provenance import MAX_SOURCE_LABEL_LENGTH

RECORDED_AT = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)
LABEL = "inbox import, scanned negatives batch 12"


def test_an_ingested_artifact_names_its_outside_source() -> None:
    provenance = ArtifactProvenance(
        kind=ProvenanceKind.INGESTED, recorded_at=RECORDED_AT, source_label=LABEL
    )

    assert provenance.kind is ProvenanceKind.INGESTED
    assert provenance.source_label == LABEL
    assert provenance.source_id is None


@pytest.mark.parametrize("kind", [ProvenanceKind.DERIVED, ProvenanceKind.RUN_OUTPUT])
def test_an_in_system_origin_is_named_by_id(kind: ProvenanceKind) -> None:
    source_id = uuid4()

    provenance = ArtifactProvenance(kind=kind, recorded_at=RECORDED_AT, source_id=source_id)

    assert provenance.source_id == source_id
    assert provenance.source_label is None


def test_an_ingested_artifact_without_a_source_label_cannot_exist() -> None:
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(kind=ProvenanceKind.INGESTED, recorded_at=RECORDED_AT)


@pytest.mark.parametrize("kind", [ProvenanceKind.DERIVED, ProvenanceKind.RUN_OUTPUT])
def test_an_in_system_origin_without_a_source_id_cannot_exist(kind: ProvenanceKind) -> None:
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(kind=kind, recorded_at=RECORDED_AT)


def test_rejects_claiming_both_an_in_system_parent_and_an_outside_source() -> None:
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(
            kind=ProvenanceKind.INGESTED,
            recorded_at=RECORDED_AT,
            source_id=uuid4(),
            source_label=LABEL,
        )
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(
            kind=ProvenanceKind.DERIVED,
            recorded_at=RECORDED_AT,
            source_id=uuid4(),
            source_label=LABEL,
        )


@pytest.mark.parametrize(
    "label",
    [
        "/mnt/nas/inbox/scan-012.tif",
        "//nas-01/inbox/scan-012.tif",
        "\\\\nas-01\\inbox\\scan-012.tif",
        "C:\\Users\\me\\inbox\\scan-012.tif",
        "d:/photos/inbox/scan-012.tif",
        "copied from /mnt/nas/inbox/scan-012.tif",
        "source C:\\Users\\me\\scan-012.tif",
        "imported from file:///mnt/nas/inbox",
        "scanned batch 12, staged under /srv/import",
        "source=/mnt/nas/inbox/scan-012.tif",
        "(/srv/import/scan-012.tif)",
        "batch 12,/srv/import",
        'staged at "/srv/import"',
        "source:/mnt/nas/inbox/scan-012.tif",
        "path:/srv/import/scan-012.tif",
        "from https://example.org/x, staged at /srv/import",
    ],
)
def test_rejects_a_machine_path_anywhere_in_the_source_label(label: str) -> None:
    """Where one machine kept a file is not what the source was, and a path
    buried in a sentence leaks the same mount root as a bare one."""

    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(
            kind=ProvenanceKind.INGESTED, recorded_at=RECORDED_AT, source_label=label
        )


@pytest.mark.parametrize(
    "label",
    [
        "https://example.org/gallery/42",
        "https://example.org:8080/gallery/42",
        "https://example.org/?next=/gallery/42",
        "https://example.org/#/gallery/42",
        "downloaded from https://example.org/#/gallery/42 on request",
        "commissioned artwork, delivery 2026/07",
        "scanned negatives batch 12",
        "photographer handoff (roll 4, frame 12)",
    ],
)
def test_accepts_a_label_that_describes_a_real_external_source(label: str) -> None:
    provenance = ArtifactProvenance(
        kind=ProvenanceKind.INGESTED, recorded_at=RECORDED_AT, source_label=label
    )

    assert provenance.source_label == label


@pytest.mark.parametrize(
    "label", ["", " ", f" {LABEL}", f"{LABEL}\n", "s" * (MAX_SOURCE_LABEL_LENGTH + 1), 1]
)
def test_rejects_a_source_label_that_describes_nothing(label: object) -> None:
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(
            kind=ProvenanceKind.INGESTED,
            recorded_at=RECORDED_AT,
            source_label=label,  # type: ignore[arg-type]
        )


def test_normalizes_the_recording_instant_to_utc() -> None:
    elsewhere = RECORDED_AT.astimezone(timezone(timedelta(hours=9)))

    provenance = ArtifactProvenance(
        kind=ProvenanceKind.INGESTED, recorded_at=elsewhere, source_label=LABEL
    )

    assert provenance.recorded_at == RECORDED_AT
    assert provenance.recorded_at.tzinfo is UTC


@pytest.mark.parametrize("recorded_at", [RECORDED_AT.replace(tzinfo=None), "2026-07-29T09:00:00Z"])
def test_rejects_a_recording_time_that_is_not_an_instant(recorded_at: object) -> None:
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(
            kind=ProvenanceKind.INGESTED,
            recorded_at=recorded_at,  # type: ignore[arg-type]
            source_label=LABEL,
        )


@pytest.mark.parametrize("kind", ["", "copied", "INGESTED", None])
def test_rejects_an_origin_that_is_not_a_known_kind(kind: object) -> None:
    with pytest.raises(ArtifactProvenanceError):
        ArtifactProvenance(
            kind=kind,  # type: ignore[arg-type]
            recorded_at=RECORDED_AT,
            source_label=LABEL,
        )


def test_is_immutable() -> None:
    provenance = ArtifactProvenance(
        kind=ProvenanceKind.INGESTED, recorded_at=RECORDED_AT, source_label=LABEL
    )

    with pytest.raises(AttributeError):
        provenance.source_label = "something else"  # type: ignore[misc]
