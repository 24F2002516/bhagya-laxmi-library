class PaymentException(Exception):
    """Base exception for payment domain errors."""
    pass


class InvalidPaymentStateException(PaymentException):
    """Raised when an action is attempted on a payment with an invalid status."""
    pass


class DuplicateUTRNumberException(PaymentException):
    """Raised when an attempt is made to reuse an existing non-null UTR number."""
    pass
