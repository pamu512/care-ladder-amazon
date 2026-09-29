import asyncio

from care_ladder.channels.speaker import SpeakerSimulator


def test_simulator_returns_ok_when_queued():
    sim = SpeakerSimulator(scripted=["I'm fine"])
    reply = asyncio.run(
        sim.prompt("Are you okay? Do you want me to call Alex?", wait_sec=1)
    )
    assert reply.kind == "ok"


def test_simulator_silence_on_timeout():
    sim = SpeakerSimulator(scripted=[])
    reply = asyncio.run(
        sim.prompt("Are you okay? Do you want me to call Alex?", wait_sec=0.05)
    )
    assert reply.kind == "silence"


def test_simulator_returns_call_caregiver():
    sim = SpeakerSimulator(scripted=["yes call"])
    reply = asyncio.run(
        sim.prompt("Are you okay? Do you want me to call Alex?", wait_sec=1)
    )
    assert reply.kind == "call_caregiver"
    assert "call" in reply.raw.lower()


def test_simulator_ok_variants():
    for phrase in ["ok", "I'm fine", "yes I'm okay", "don't worry"]:
        sim = SpeakerSimulator(scripted=[phrase])
        reply = asyncio.run(sim.prompt("Are you okay?", wait_sec=0.1))
        assert reply.kind == "ok", f"expected ok for {phrase!r}, got {reply.kind}"
        assert reply.intent == "clear_ok"


def test_simulator_mixed_hurt_is_not_ok():
    sim = SpeakerSimulator(scripted=["I'm okay but I think I'm hurt"])
    reply = asyncio.run(sim.prompt("Are you okay?", wait_sec=0.1))
    assert reply.kind != "ok"
    assert reply.intent == "needs_human"


def test_simulator_groan_is_silence():
    sim = SpeakerSimulator(scripted=["nngh"])
    reply = asyncio.run(sim.prompt("Are you okay?", wait_sec=0.1))
    assert reply.kind == "silence"
    assert reply.intent == "unclear"
