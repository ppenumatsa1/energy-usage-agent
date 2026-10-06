class EnergyError(Exception):
    status = 400
    code = "invalid_argument"
    title = "Invalid argument"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidRange(EnergyError):
    code = "invalid_range"
    title = "Invalid date range"


class InvalidArgument(EnergyError):
    code = "invalid_argument"
    title = "Invalid argument"


class NoData(EnergyError):
    status = 404
    code = "no_data"
    title = "No data"


class NotOnboarded(EnergyError):
    status = 403
    code = "not_onboarded"
    title = "Not onboarded"
