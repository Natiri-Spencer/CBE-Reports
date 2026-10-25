"""Privacy-preserving server logging and bounded in-memory PDF delivery."""
import logging
from fastapi.responses import JSONResponse, StreamingResponse

logging.getLogger("uvicorn.access").disabled = True

class PrivateErrors:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False
        async def private_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                message["headers"] += [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
            await send(message)
        try:
            await self.app(scope, receive, private_send)
        except Exception:
            # Never attach exception text, SQL parameters, URLs or request bodies.
            logging.getLogger("school.security").error("request_failed")
            if not started:
                await JSONResponse({"detail": "Internal server error"}, status_code=500)(scope, receive, private_send)
            else:
                await send({"type": "http.response.body", "body": b"", "more_body": False})

def stream_pdf(buffer, filename):
    buffer.seek(0)
    def chunks():
        try:
            while chunk := buffer.read(64 * 1024):
                yield chunk
        finally:
            buffer.close()
    return StreamingResponse(chunks(), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
