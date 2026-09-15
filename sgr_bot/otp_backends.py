"""OTP backends — compatibility wrapper. Use otp_delivery.get_otp."""
from .otp_delivery import get_otp

__all__ = ["get_otp"]
