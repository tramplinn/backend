import logging
from logging.config import dictConfig


def configure_logging(*, debug: bool) -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {"format": "%(asctime)s %(levelname)-8s %(name)s: %(message)s"}
            },
            "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "default"}},
            "root": {"handlers": ["console"], "level": logging.DEBUG if debug else logging.INFO},
            "loggers": {
                "sqlalchemy.engine": {"level": logging.WARNING},
                "httpx": {"level": logging.WARNING},
                "botocore": {"level": logging.WARNING},
            },
        },
    )
