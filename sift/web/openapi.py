from __future__ import annotations

import json
import sys
from typing import Any

from fastapi import FastAPI

from sift.web import api

TITLE = "Sift"


def document() -> dict[str, Any]:
    app = FastAPI(title=TITLE)
    app.include_router(api.router)
    return app.openapi()


def main() -> None:
    sys.stdout.write(json.dumps(document(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
