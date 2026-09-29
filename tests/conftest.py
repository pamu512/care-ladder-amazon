"""Shared pytest fixtures."""

import pytest

from care_ladder.channels.care_conversation import CareConversation


@pytest.fixture(autouse=True)
def _reset_care_conversations():
    CareConversation.reset_registry()
    yield
    CareConversation.reset_registry()
