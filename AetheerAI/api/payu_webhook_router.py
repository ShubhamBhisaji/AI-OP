"""PayU hosted-checkout callback intake routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from integrations.errors import ConfigurationError
from integrations.payu_client import PayUClient


logger = logging.getLogger("aetheer.api.payu_webhook")

router = APIRouter(prefix="/api/payu", tags=["Integrations"])


def _text(value: Any) -> str:
    return str(value or "").strip()


def _required(payload: dict[str, str], field: str) -> str:
    value = _text(payload.get(field))
    if not value:
        raise HTTPException(status_code=400, detail=f"{field} is required")
    return value


def _parse_amount(raw_value: str) -> float:
    try:
        return float(raw_value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="amount must be numeric") from exc


async def _read_form_payload(request: Request) -> dict[str, str]:
    try:
        form_data = await request.form()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Callback payload must be form-encoded") from exc

    return {str(key): _text(value) for key, value in form_data.items()}


def _verify_callback_payload(payload: dict[str, str]) -> None:
    amount = _parse_amount(_required(payload, "amount"))

    try:
        client = PayUClient()
        is_valid = client.verify_payment_response_hash(
            status=_required(payload, "status"),
            txnid=_required(payload, "txnid"),
            amount=amount,
            product_info=_required(payload, "productinfo"),
            first_name=_required(payload, "firstname"),
            email=_required(payload, "email"),
            received_hash=_required(payload, "hash"),
            udf1=_text(payload.get("udf1")),
            udf2=_text(payload.get("udf2")),
            udf3=_text(payload.get("udf3")),
            udf4=_text(payload.get("udf4")),
            udf5=_text(payload.get("udf5")),
            additional_charges=_text(
                payload.get("additionalCharges") or payload.get("additional_charges")
            ),
        )
    except ConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid callback payload: {exc}") from exc

    if not is_valid:
        raise HTTPException(status_code=401, detail="Invalid PayU hash")


def _callback_response(*, callback: str, payload: dict[str, str]) -> JSONResponse:
    _verify_callback_payload(payload)

    payment_status = _text(payload.get("status")).lower()
    txnid = _text(payload.get("txnid"))

    logger.info(
        "PayU callback verified (callback=%s payment_status=%s txnid=%s)",
        callback,
        payment_status,
        txnid,
    )

    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "verified": True,
            "gateway": "payu",
            "callback": callback,
            "payment_status": payment_status,
            "transaction_id": txnid,
        },
    )


@router.get("/success", response_class=PlainTextResponse)
def payu_success_hint() -> PlainTextResponse:
    return PlainTextResponse(content="PayU success callback endpoint is live", status_code=200)


@router.get("/failure", response_class=PlainTextResponse)
def payu_failure_hint() -> PlainTextResponse:
    return PlainTextResponse(content="PayU failure callback endpoint is live", status_code=200)


@router.post("/success", response_class=JSONResponse)
async def receive_payu_success(request: Request) -> JSONResponse:
    payload = await _read_form_payload(request)
    return _callback_response(callback="success", payload=payload)


@router.post("/failure", response_class=JSONResponse)
async def receive_payu_failure(request: Request) -> JSONResponse:
    payload = await _read_form_payload(request)
    return _callback_response(callback="failure", payload=payload)
