import os
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query


ACTIVE_VERCEL_DOMAIN = os.getenv("ACTIVE_VERCEL_DOMAIN", "my-xhttp-relay-two.vercel.app")


app = FastAPI(
    title="Vercel XHTTP Config API",
    version="1.0.0",
    description="Phase 2 backend that generates VLESS links for clients.",
)


def validate_uuid(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid UUID format") from exc
    return str(parsed)


def build_vless_link(user_uuid: str, vercel_domain: str) -> str:
    return (
        f"vless://{user_uuid}@{vercel_domain}:443"
        f"?encryption=none"
        f"&security=tls"
        f"&sni={vercel_domain}"
        f"&alpn=h2,http/1.1"
        f"&fp=chrome"
        f"&type=xhttp"
        f"&host={vercel_domain}"
        f"&path=/"
        f"&mode=auto"
        f"#Vercel-Connection"
    )


@app.get("/api/v1/get-config")
def get_config(uuid: str = Query(..., description="Client UUID")):
    normalized_uuid = validate_uuid(uuid)
    full_vless_link = build_vless_link(normalized_uuid, ACTIVE_VERCEL_DOMAIN)

    return {
        "status": "success",
        "vercel_domain": ACTIVE_VERCEL_DOMAIN,
        "full_vless_link": full_vless_link,
    }


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
