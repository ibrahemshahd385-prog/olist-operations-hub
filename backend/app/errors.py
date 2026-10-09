"""Errors raised by the business logic.

Services never know about HTTP. They raise these errors, and main.py turns
them into the right HTTP response (404, 409, 422) in one place.
"""


class NotFoundError(Exception):
    """The requested record does not exist (-> HTTP 404)."""


class BusinessRuleError(Exception):
    """The request is valid, but a business rule forbids it (-> HTTP 409).
    Example: shipping an order that has no invoice yet."""


class ValidationFailed(Exception):
    """The submitted data is wrong (-> HTTP 422). Carries a list of messages
    so the screen can show every problem at once, not one at a time."""

    def __init__(self, errors: list):
        super().__init__("; ".join(errors))
        self.errors = errors
