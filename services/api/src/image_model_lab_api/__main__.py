import os

import uvicorn


def main() -> None:
    host = os.environ.get("IMAGE_MODEL_LAB_API_HOST", "127.0.0.1")
    port = int(os.environ.get("IMAGE_MODEL_LAB_API_PORT", "8000"))
    uvicorn.run("image_model_lab_api.app:app", host=host, port=port)


if __name__ == "__main__":
    main()
