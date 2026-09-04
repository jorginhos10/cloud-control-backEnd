import hashlib
import os

import httpx

# https://docs.wompi.co/en/docs/colombia/widget-checkout-web/#step-3-generate-an-integrity-signature
def integrity_signature(reference: str, amount_in_cents: int, currency: str = "COP") -> str:
    secret = os.environ["WOMPI_INTEGRITY_SECRET"]
    concatenated = f"{reference}{amount_in_cents}{currency}{secret}"
    return hashlib.sha256(concatenated.encode("utf-8")).hexdigest()


# https://docs.wompi.co/en/docs/colombia/eventos/#step-by-step-verify-the-authenticity-of-an-event
def verify_event_checksum(event: dict) -> bool:
    secret = os.environ["WOMPI_EVENTS_SECRET"]
    signature = event.get("signature") or {}
    properties: list[str] = signature.get("properties", [])
    checksum: str = signature.get("checksum", "")
    timestamp = event.get("timestamp", "")

    data = event.get("data", {})
    concatenated = ""
    for prop in properties:
        node = data
        for part in prop.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        concatenated += str(node)

    concatenated += str(timestamp) + secret
    computed = hashlib.sha256(concatenated.encode("utf-8")).hexdigest()
    return computed == checksum


def get_transaction(transaction_id: str) -> dict | None:
    api_url = os.environ["WOMPI_API_URL"]
    try:
        resp = httpx.get(f"{api_url}/transactions/{transaction_id}", timeout=10)
    except httpx.RequestError:
        return None
    if resp.status_code != 200:
        return None
    return resp.json().get("data")


STATUS_MAP = {
    "APPROVED": "pagado",
    "DECLINED": "fallido",
    "VOIDED": "fallido",
    "ERROR": "fallido",
    "PENDING": "pendiente_pago",
}
