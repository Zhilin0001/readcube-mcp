class ReadCubeError(Exception):
    """Safe to expose to an agent; never includes raw responses or request URLs."""


class UnverifiedEndpointError(ReadCubeError, NotImplementedError):
    pass


class AuthorizationError(ReadCubeError):
    pass


class AuthenticationError(ReadCubeError):
    pass


class ProtocolError(ReadCubeError):
    pass


class PaginationError(ProtocolError):
    pass


class APIError(ReadCubeError):
    def __init__(self, operation: str, status: int):
        self.operation = operation
        self.status = status
        super().__init__(f"{operation}: HTTP {status}; inspect local sanitized evidence")


class TransportError(ReadCubeError):
    pass


class UploadPendingError(ReadCubeError):
    pass
