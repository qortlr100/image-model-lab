import pytest
from image_model_lab_domain import DigestError, Sha256Digest

DIGEST = "c9002e992258426720776d39ced66f985968a16488ef7e56716c7ff8b6c425aa"


def test_holds_lowercase_hex() -> None:
    digest = Sha256Digest(DIGEST)

    assert digest.hex == DIGEST
    assert str(digest) == DIGEST
    assert digest.prefixed == f"sha256:{DIGEST}"


@pytest.mark.parametrize(
    "value",
    [DIGEST, DIGEST.upper(), f"sha256:{DIGEST}", f"SHA256:{DIGEST.upper()}"],
)
def test_normalizes_every_accepted_spelling_to_one_value(value: str) -> None:
    """One stored digest has exactly one in-memory form, so equality holds."""

    assert Sha256Digest(value) == Sha256Digest(DIGEST)


def test_is_immutable() -> None:
    digest = Sha256Digest(DIGEST)

    with pytest.raises(AttributeError):
        digest.hex = "0" * 64  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        "",
        DIGEST[:-1],
        DIGEST + "a",
        DIGEST.replace("c", "g", 1),
        f" {DIGEST}",
        f"{DIGEST}\n",
        f"md5:{DIGEST}",
        f"sha256:sha256:{DIGEST}",
        "sha256:",
        "0x" + DIGEST,
        "d41d8cd98f00b204e9800998ecf8427e",
    ],
)
def test_rejects_anything_that_is_not_a_sha256_digest(value: str) -> None:
    with pytest.raises(DigestError):
        Sha256Digest(value)
