class BookingException(Exception):
    """Base exception for booking domain errors."""
    pass


class StudentAlreadyHasActiveBookingException(BookingException):
    """Raised when a student attempts to book while already holding an active allocation."""
    pass


class NoSeatsAvailableException(BookingException):
    """Raised when all 150 study seats are occupied or unavailable."""
    pass


class ConcurrentBookingContentionException(BookingException):
    """Raised under extreme concurrent traffic when a candidate seat lock could not be obtained."""
    pass


class InvalidBookingStateException(BookingException):
    """Raised when a booking transition is invalid for its current state."""
    pass
