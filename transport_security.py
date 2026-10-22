"""HTTPS policy; proxy headers must already be validated by Uvicorn."""
from ipaddress import ip_address
import os
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware


def allowed_hosts():
    configured = os.getenv("ALLOWED_HOSTS", "").strip()
    if configured:
        return [value.strip() for value in configured.split(",") if value.strip()]
    hosts = ["localhost", "127.0.0.1", "[::1]", "*.trycloudflare.com"]
    public_host = urlsplit(os.getenv("FIXED_PUBLIC_URL", "")).hostname
    if public_host:
        hosts.append(public_host)
    return hosts


class RequireHTTPS:
    def __init__(self, app):
        self.app = app
        # Docker forwards host-loopback connections through its bridge gateway.
        # Keep this separate from proxy-header trust: public requests still need HTTPS.
        self.local_http_peers = {
            ip_address(value.strip())
            for value in os.getenv("LOCAL_HTTP_PEERS", "").split(",") if value.strip()
        }

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["scheme"] != "https":
            request = Request(scope)
            try:
                peer = ip_address(request.client.host)
                loopback = peer.is_loopback or peer in self.local_http_peers
            except (ValueError, AttributeError):
                loopback = False
            local = (
                loopback
                and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
                and "x-forwarded-for" not in request.headers
                and "cf-connecting-ip" not in request.headers
                and "x-forwarded-proto" not in request.headers
            )
            if not local:
                url = request.url.replace(scheme="https", netloc=request.headers["host"].removesuffix(":80"))
                await RedirectResponse(str(url), status_code=308)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def install_transport_security(app):
    app.add_middleware(RequireHTTPS)
    # This runs outside RequireHTTPS, preventing redirects to untrusted Hosts.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(), www_redirect=False)
