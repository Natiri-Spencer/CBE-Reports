"""Keep invalid JSON numbers from breaking FastAPI's 422 response encoder."""
import math

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


async def request_validation_error(_request, exception):
    return JSONResponse(status_code=422, content={"detail": json_safe(jsonable_encoder(exception.errors()))})
