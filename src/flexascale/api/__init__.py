"""
FlexaScale REST API and Dashboard backend.
"""

from flexascale.api.app import create_app
from flexascale.api.state_store import APIStateStore, get_state_store

__all__ = ["create_app", "APIStateStore", "get_state_store"]
