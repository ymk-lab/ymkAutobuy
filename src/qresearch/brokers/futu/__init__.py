"""Futu (富途) OpenD integration."""

from qresearch.brokers.futu.adapter import FutuBrokerAdapter
from qresearch.brokers.futu.config import (
    configured_trd_env,
    futu_opend_host,
    futu_opend_port,
    futu_trd_env_simulate,
    has_futu_opend,
    load_dotenv_if_present,
)

__all__ = [
    "FutuBrokerAdapter",
    "has_futu_opend",
    "futu_opend_host",
    "futu_opend_port",
    "futu_trd_env_simulate",
    "configured_trd_env",
    "load_dotenv_if_present",
]
