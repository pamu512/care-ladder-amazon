"""Shared pytest fixtures."""

import pytest

from care_ladder.channels.care_conversation import CareConversation
from care_ladder.learning.schedule import reset_schedule_book


@pytest.fixture(autouse=True)
def _reset_care_conversations():
    CareConversation.reset_registry()
    reset_schedule_book()
    yield
    CareConversation.reset_registry()
    reset_schedule_book()


@pytest.fixture(autouse=True)
def _insecure_local_auth_default(monkeypatch):
    """Existing API tests are the local opt-out path. Auth tests override."""
    monkeypatch.setenv("CARE_LADDER_ALLOW_INSECURE_LOCAL", "1")
    monkeypatch.delenv("CARE_LADDER_API_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _no_live_sagemaker_endpoint(monkeypatch):
    """CI and local tests stay on the npz unless a test sets the endpoint."""
    monkeypatch.delenv("CARE_LADDER_SAGEMAKER_ENDPOINT", raising=False)
