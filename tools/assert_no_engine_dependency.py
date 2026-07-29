#!/usr/bin/env python3
"""Assert that a control-plane image has no training engine dependency.

Run inside a built service image, not on the host:

    docker run --rm -i image-model-lab-api:ci python - < tools/assert_no_engine_dependency.py

The API and Worker images coordinate work; they never load a model. Keeping
PyTorch and the engine stack out of their dependency graph is what stops those
images from silently growing into GPU images.
"""

from __future__ import annotations

import importlib.util
import sys

BLOCKED_MODULES = (
    "accelerate",
    "bitsandbytes",
    "diffusers",
    "torch",
    "transformers",
    "xformers",
)


def installed_modules(names: tuple[str, ...]) -> list[str]:
    return [name for name in names if importlib.util.find_spec(name) is not None]


def main(names: tuple[str, ...] = BLOCKED_MODULES) -> int:
    found = installed_modules(names)
    if found:
        print(
            f"engine dependency must not be installed in this image: {', '.join(found)}",
            file=sys.stderr,
        )
        return 1
    print(f"no engine dependency found ({len(names)} modules checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
