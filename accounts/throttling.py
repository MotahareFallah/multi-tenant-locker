import logging

from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger(__name__)


class IPRateThrottle(SimpleRateThrottle):
    """Per-client-IP rate limit.

    The client IP comes from DRF's get_ident, which honours NUM_PROXIES. With 0
    it is REMOTE_ADDR and X-Forwarded-For is ignored, so a forged header cannot
    create a fresh bucket for every request.

    If the cache backend fails the request is allowed and the failure is logged:
    the per-phone limits live in the database and still apply, and a cache outage
    should not lock everybody out.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }

    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.exception("IP throttle backend failed; allowing the request")
            return True


class OTPRequestThrottle(IPRateThrottle):
    scope = "otp_request"


class OTPVerifyThrottle(IPRateThrottle):
    scope = "otp_verify"
