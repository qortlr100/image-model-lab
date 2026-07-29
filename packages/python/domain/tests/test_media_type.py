import pytest
from image_model_lab_domain import MediaType, MediaTypeError


@pytest.mark.parametrize(
    "value",
    [
        "image/png",
        "image/jpeg",
        "image/webp",
        "application/json",
        "application/octet-stream",
        "application/vnd.comfyui.workflow+json",
        "text/plain",
    ],
)
def test_accepts_artifact_media_types(value: str) -> None:
    assert MediaType(value).value == value


def test_splits_type_and_subtype() -> None:
    media_type = MediaType("application/vnd.comfyui.workflow+json")

    assert media_type.type == "application"
    assert media_type.subtype == "vnd.comfyui.workflow+json"
    assert str(media_type) == "application/vnd.comfyui.workflow+json"


def test_normalizes_case() -> None:
    assert MediaType("Image/PNG") == MediaType("image/png")


def test_is_immutable() -> None:
    media_type = MediaType("image/png")

    with pytest.raises(AttributeError):
        media_type.value = "image/jpeg"  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "image",
        "image/",
        "/png",
        "image//png",
        "image/png/extra",
        "image png",
        " image/png",
        "image/png ",
        "image/png\n",
        "image/*",
        "*/*",
        "text/plain; charset=utf-8",
        "이미지/png",
    ],
)
def test_rejects_wildcards_parameters_and_malformed_values(value: str) -> None:
    with pytest.raises(MediaTypeError):
        MediaType(value)
