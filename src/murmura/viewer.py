"""Sends compiled shows to a running 3D show viewer for preview.

Viewers that support live preview announce themselves on the local network
via SSDP with the ``urn:collmot-com:service:skyc-validator:1`` service type
and accept ``.skyc`` uploads at ``<location>/api/v1/load``.
"""

from __future__ import annotations

import json
import socket
from urllib.error import URLError
from urllib.request import Request, urlopen

from .i18n import t

__all__ = ("ViewerNotFoundError", "discover_viewer", "send_to_viewer")

SERVICE_TYPE = "urn:collmot-com:service:skyc-validator:1"


class ViewerNotFoundError(RuntimeError):
    pass


def discover_viewer(timeout: float = 1.5) -> str | None:
    """Returns the base URL of a viewer found via SSDP, or ``None``."""
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST:239.255.255.250:1900\r\n"
        f"ST:{SERVICE_TYPE}\r\n"
        "MX:1\r\n"
        'MAN:"ssdp:discover"\r\n'
        "\r\n"
    ).encode("ascii")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.settimeout(timeout)
    try:
        for target in (("239.255.255.250", 1900), ("127.0.0.1", 1900)):
            try:
                sock.sendto(message, target)
            except OSError:
                continue
        for _ in range(10):
            try:
                data, _ = sock.recvfrom(65507)
            except TimeoutError:
                return None
            if not data.startswith(b"HTTP/1.1 200 OK"):
                continue
            for line in data.split(b"\r\n"):
                key, _, value = line.partition(b":")
                if key.strip().upper() == b"LOCATION":
                    return value.decode("ascii", "replace").strip().rstrip("/")
    finally:
        sock.close()
    return None


def send_to_viewer(show_data: bytes, *, title: str | None = None, url: str | None = None) -> str:
    """Uploads a ``.skyc`` file to the viewer; returns the viewer URL used."""
    base = url or discover_viewer()
    if not base:
        raise ViewerNotFoundError(t("no show viewer found on this machine; is it running?"))
    headers = {"Content-Type": "application/skybrush-compiled"}
    if title:
        headers["X-Skybrush-Viewer-Title"] = title[:512]
    request = Request(f"{base}/api/v1/load", data=show_data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except URLError as ex:
        raise ViewerNotFoundError(
            t("could not reach the viewer at {url}: {reason}", url=base, reason=ex.reason)
        ) from ex
    if not (isinstance(result, dict) and result.get("result")):
        raise RuntimeError(t("viewer rejected the show: {result}", result=repr(result)))
    return base
