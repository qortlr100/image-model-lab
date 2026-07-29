from fastapi.routing import APIRoute
from image_model_lab_api.app import app, get_health, get_version


def test_health_endpoint() -> None:
    assert get_health().model_dump() == {
        "service": "api",
        "status": "ok",
        "version": "0.1.0",
    }


def test_version_endpoint() -> None:
    assert get_version().model_dump() == {
        "service": "api",
        "version": "0.1.0",
    }


def test_service_routes_are_registered() -> None:
    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}

    assert {"/health", "/version"} <= paths
