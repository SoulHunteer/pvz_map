class MonitoringError(Exception):
    """Base exception for monitoring domain errors."""


class InvalidMapLinkError(MonitoringError):
    pass


class BrowserTimeoutError(MonitoringError):
    pass


class EmptyScreenshotError(MonitoringError):
    pass


class MapLoadError(MonitoringError):
    pass


class ImageDetectionError(MonitoringError):
    pass


class ZoneMatchingError(MonitoringError):
    pass


class TariffLimitError(MonitoringError):
    pass


class AccessDeniedError(MonitoringError):
    pass


class NotFoundError(MonitoringError):
    pass


class ValidationError(MonitoringError):
    pass
