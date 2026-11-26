"""Translation Notary on a local GenLayer network (glsim, 5 validators). A pair is registered and judged through real
consensus rounds: the leader and four validators each read it with a (mocked) model, and the contract keeps the outcome
only when they agree. Mocks stay installed for a whole simulator run, so each test that needs them uses its own simulator.
The local simulator ships its own runner hash, so the tests run a copy of the contract with only that first line swapped.
"""
import json
from pathlib import Path

import pytest

from rpc import RpcError, Sim

ROOT = Path(__file__).resolve().parents[2]
LOCAL_HASH = "5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng"
ASPECTS = ("NUMBERS", "NEGATION", "OBLIGATION", "NAMES", "CONDITIONS", "OMISSION", "ADDITION")
ALICE = "0x3333333333333333333333333333333333333333"
BOB = "0x4444444444444444444444444444444444444444"
T0 = "2026-11-25T12:00:00Z"
T1 = "2026-11-25T12:05:00Z"
SRC = "The tenant must pay a deposit of 1,500 euros within 30 days and may not sublet the flat without written consent."
TGT = "Kiraci, 30 gun icinde 1.500 euro depozito odemelidir ve yazili onay olmadan daireyi kiraya veremez."


def build_local():
    lines = (ROOT / "contracts" / "translation_notary.py").read_text(encoding="utf-8").split("\n")
    lines[0] = '# { "Depends": "py-genlayer:%s" }' % LOCAL_HASH
    out = ROOT / "build" / "translation_notary_local.py"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return "build/translation_notary_local.py"


CONTRACT = build_local()


def aspect(verdict="OK", side="", quote=""):
    return {"verdict": verdict, "side": side, "quote": quote}


def reply(**changes):
    out = {name: aspect() for name in ASPECTS}
    out.update(changes)
    return json.dumps(out)


@pytest.fixture
def sim():
    simulator = Sim()
    try:
        yield simulator
    finally:
        simulator.close()


def start(sim, answer):
    sim.set_time(T0)
    sim.mocks(llm={"UNTRUSTED DATA": answer})
    contract = sim.deploy(CONTRACT, [], ALICE)
    rid = json.loads(sim.call(contract, "register", ["en", SRC, "tr", TGT], ALICE))["id"]
    return contract, rid


def test_a_faithful_pair_is_a_match_after_consensus(sim):
    contract, rid = start(sim, reply())
    out = json.loads(sim.call(contract, "judge", [rid], BOB))
    assert out == {"id": rid, "status": "MATCH", "issues": []}
    assert sim.read(contract, "get_status", [rid]) == "MATCH"
    record = sim.read_json(contract, "get_record_json", [rid])
    assert record["judgements"][0]["by"] == BOB and len(record["judgements"]) == 1


def test_a_changed_clause_is_a_difference_with_a_real_quote(sim):
    contract, rid = start(sim, reply(NUMBERS=aspect("ISSUE", "target", "30 gun icinde 1.500 euro")))
    out = json.loads(sim.call(contract, "judge", [rid], BOB))
    assert out["status"] == "DIFFERS" and out["issues"] == ["NUMBERS"]


def test_an_invented_quote_settles_nothing_on_the_network(sim):
    contract, rid = start(sim, reply(NUMBERS=aspect("ISSUE", "target", "words nobody wrote anywhere")))
    assert sim.call(contract, "judge", [rid], BOB) == "UNREADABLE"
    assert sim.read(contract, "get_status", [rid]) == "REGISTERED"


def test_an_unsure_reading_can_be_judged_again_after_a_minute(sim):
    contract, rid = start(sim, reply(NAMES=aspect("UNSURE")))
    assert json.loads(sim.call(contract, "judge", [rid], BOB))["status"] == "UNCLEAR"
    with pytest.raises(RpcError):
        sim.call(contract, "judge", [rid], BOB)                    # a minute has not passed
    sim.set_time(T1)
    assert json.loads(sim.call(contract, "judge", [rid], BOB))["status"] == "UNCLEAR"
    assert len(sim.read_json(contract, "get_record_json", [rid])["judgements"]) == 2


def test_the_rules_hold_on_the_network(sim):
    contract, rid = start(sim, reply())
    with pytest.raises(RpcError):
        sim.call(contract, "register", ["en", SRC, "tr", TGT], BOB)             # the same pair twice
    with pytest.raises(RpcError):
        sim.call(contract, "register", ["en", SRC, "en", TGT], BOB)             # same language
    with pytest.raises(RpcError):
        sim.call(contract, "judge", ["0" * 20], BOB)                            # unknown record
    sim.call(contract, "judge", [rid], BOB)
    sim.set_time(T1)
    with pytest.raises(RpcError):
        sim.call(contract, "judge", [rid], BOB)                                 # a match is final
    assert sim.read(contract, "get_count") == 1
