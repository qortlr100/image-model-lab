from typing import Literal

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from image_model_lab_api import __version__

SERVICE_NAME = "api"


class ServiceStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    status: Literal["ok"]
    version: str


class ServiceVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: str
    version: str


app = FastAPI(
    title="Image Model Lab API",
    version=__version__,
    description="Control-plane API service skeleton.",
)


@app.get("/health", response_model=ServiceStatus, tags=["service"])
def get_health() -> ServiceStatus:
    return ServiceStatus(service=SERVICE_NAME, status="ok", version=__version__)


@app.get("/version", response_model=ServiceVersion, tags=["service"])
def get_version() -> ServiceVersion:
    return ServiceVersion(service=SERVICE_NAME, version=__version__)
