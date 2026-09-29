"""Stub telephony channel + no-answer escalation helper (demo only)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from care_ladder.models import CarePlan, Contact

DialStatus = Literal["answered", "no_answer", "skipped"]

# Reserved fiction phones used in demo_home (+1212555010x). Never real 911.
_RESERVED_PHONE_TO_CONTACT_ID: dict[str, str] = {
    "+12125550101": "caregiver",
    "+12125550102": "secondary",
}


@dataclass(frozen=True)
class DialResult:
    status: DialStatus
    contact_id: str


class StubDialer:
    """Injectable scripted dial outcomes for demos/tests (no real telephony).

    ``behavior`` maps contact role ids (``caregiver``, ``secondary``, …) to a
    ``DialResult.status``. Contacts are resolved by role string, registered
    phone, or reserved demo phone numbers.
    """

    def __init__(
        self,
        behavior: Mapping[str, DialStatus],
        *,
        contacts: Mapping[str, Contact] | None = None,
    ) -> None:
        self._behavior: dict[str, DialStatus] = dict(behavior)
        self._contacts: dict[str, Contact] = dict(contacts or {})
        self._phone_to_id: dict[str, str] = {
            c.phone_e164: cid
            for cid, c in self._contacts.items()
            if c.phone_e164
        }

    def dial(self, contact: Contact | str, ring_sec: float = 30.0) -> DialResult:
        """Return a scripted dial outcome. ``ring_sec`` is accepted for API parity (no real ring)."""
        _ = ring_sec
        contact_id = self._resolve_contact_id(contact)
        if isinstance(contact, Contact) and not contact.phone_e164:
            return DialResult(status="skipped", contact_id=contact_id)
        status = self._behavior.get(contact_id, "no_answer")
        return DialResult(status=status, contact_id=contact_id)

    def _resolve_contact_id(self, contact: Contact | str) -> str:
        if isinstance(contact, str):
            return contact
        phone = contact.phone_e164
        if phone and phone in self._phone_to_id:
            return self._phone_to_id[phone]
        if phone and phone in _RESERVED_PHONE_TO_CONTACT_ID:
            return _RESERVED_PHONE_TO_CONTACT_ID[phone]
        for cid, registered in self._contacts.items():
            if registered is contact:
                return cid
        # Last resort: if behavior has a single key, use it (tests with one contact).
        if len(self._behavior) == 1:
            return next(iter(self._behavior))
        raise ValueError(
            f"Cannot resolve contact_id for dial stub contact={contact!r}; "
            "pass a role string, register contacts=, or use a reserved demo phone"
        )


def next_rung_after_no_answer(plan: CarePlan, current_index: int) -> int | None:
    """Index of the next escalation rung after a no-answer at ``current_index``.

    Advances to the next ``dial_contact`` rung, or ``emergency`` only when
    ``params.enabled is True`` (fail-closed). Disabled emergency is never
    selected. Returns ``None`` when nothing remains to try.
    """
    for i in range(current_index + 1, len(plan.rungs)):
        rung = plan.rungs[i]
        if rung.tool == "emergency":
            if rung.params.get("enabled") is True:
                return i
            continue
        if rung.tool == "dial_contact":
            return i
    return None
