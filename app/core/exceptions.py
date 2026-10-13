class BNError(Exception):
    pass

class PermissionDenied(BNError):
    pass

class NotFound(BNError):
    pass

class ValidationFailure(BNError):
    pass

class InsufficientFunds(BNError):
    pass

class CooldownActive(BNError):
    def __init__(self, seconds: int) -> None:
        self.seconds = seconds
        super().__init__(f"Cooldown active for {seconds} seconds")
