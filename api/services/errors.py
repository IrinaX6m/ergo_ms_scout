class ScoutError(Exception):
    def __init__(self, code: str, message: str, *, path: str | None = None):
        self.code = code
        self.path = path
        super().__init__(message)


class FetchError(ScoutError):
    def __init__(self, code: str, message: str, *, retryable: bool):
        self.retryable = retryable
        super().__init__(code, message)
