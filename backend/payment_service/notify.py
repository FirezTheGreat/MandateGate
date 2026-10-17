"""Tell the gate about every payment attempt (paid or refused), so it reaches the live feed.

Best effort, display only: a notification failure never affects the payment, and the gate
never decides anything from these. Each report is signed (HMAC over the canonical body, with a
key derived from PASS_KEY for this purpose only) and time-stamped, so an agent cannot inject fake
payments into the feed, and no report signature could ever pass for a pass signature.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import httpx

from app.crypto import PAYMENT_EVENT_KEY, derive_key, sign
from app.models import PaymentEventReport

SIGNATURE_HEADER = "X-MandateGate-Signature"
log = logging.getLogger("mandategate.payment.notify")
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="payment-notify")

Notifier = Callable[[PaymentEventReport], None]


def make_notifier(http: httpx.Client, key: str, *, background: bool = True) -> Notifier:
    key = derive_key(key, PAYMENT_EVENT_KEY)

    def deliver(report: PaymentEventReport) -> None:
        body = report.model_dump(mode="json")
        try:
            r = http.post("/internal/payment-event", json=body, headers={SIGNATURE_HEADER: sign(key, body)})
            if r.status_code >= 400:
                log.warning("gate refused payment event: %s %s", r.status_code, r.text[:200])
        except httpx.HTTPError as e:
            log.warning("could not notify the gate (%s)", type(e).__name__)

    def notify(report: PaymentEventReport) -> None:
        if background:
            _pool.submit(deliver, report)  # never adds latency to the payment response
        else:
            deliver(report)

    return notify
