"""Mutation check: change the contract on a disposable copy, one small edit at a time, and see whether the tests notice.

Run from the repository root:  python3 scripts/mutation_check.py [workers]
It first proves that the unmodified contract passes, then runs the tests against every mutant (stopping at the first
failing test). A mutant that survives is either a missing test or an equivalent change; survivors are listed.
Each entry is (label, text to find, replacement, which occurrence of the text to change: 1 = first).
"""
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/translation_notary.py"

MUTANTS = [
    ("text min 21", "TEXT_MIN, TEXT_MAX = 20, 3000", "TEXT_MIN, TEXT_MAX = 21, 3000", 1),
    ("text min 19", "TEXT_MIN, TEXT_MAX = 20, 3000", "TEXT_MIN, TEXT_MAX = 19, 3000", 1),
    ("text max 2999", "TEXT_MIN, TEXT_MAX = 20, 3000", "TEXT_MIN, TEXT_MAX = 20, 2999", 1),
    ("text max 3001", "TEXT_MIN, TEXT_MAX = 20, 3000", "TEXT_MIN, TEXT_MAX = 20, 3001", 1),
    ("201 records", "MAX_RECORDS = 200", "MAX_RECORDS = 201", 1),
    ("199 records", "MAX_RECORDS = 200", "MAX_RECORDS = 199", 1),
    ("4 judgements", "MAX_JUDGEMENTS = 3", "MAX_JUDGEMENTS = 4", 1),
    ("2 judgements", "MAX_JUDGEMENTS = 3", "MAX_JUDGEMENTS = 2", 1),
    ("gap 61", "JUDGE_GAP = 60 ", "JUDGE_GAP = 61 ", 1),
    ("gap 59", "JUDGE_GAP = 60 ", "JUDGE_GAP = 59 ", 1),
    ("page limit 51", "PAGE_LIMIT = 50", "PAGE_LIMIT = 51", 1),
    ("page limit 49", "PAGE_LIMIT = 50", "PAGE_LIMIT = 49", 1),
    ("quote min 9", "QUOTE_MIN, QUOTE_MAX = 8, 200", "QUOTE_MIN, QUOTE_MAX = 9, 200", 1),
    ("quote min 7", "QUOTE_MIN, QUOTE_MAX = 8, 200", "QUOTE_MIN, QUOTE_MAX = 7, 200", 1),
    ("quote max 199", "QUOTE_MIN, QUOTE_MAX = 8, 200", "QUOTE_MIN, QUOTE_MAX = 8, 199", 1),
    ("quote max 201", "QUOTE_MIN, QUOTE_MAX = 8, 200", "QUOTE_MIN, QUOTE_MAX = 8, 201", 1),
    ("anchor cap 59", "MAX_ANCHORS = 60", "MAX_ANCHORS = 59", 1),
    ("model answer limit 5999", "MAX_MODEL = 6000", "MAX_MODEL = 5999", 1),
    ("model answer limit 6001", "MAX_MODEL = 6000", "MAX_MODEL = 6001", 1),
    ("one model try", "MODEL_TRIES = 2", "MODEL_TRIES = 1", 1),
    ("three model tries", "MODEL_TRIES = 2", "MODEL_TRIES = 3", 1),
    ("id length 19", "ID_LENGTH = 20", "ID_LENGTH = 19", 1),
    ("an aspect missing", '"CONDITIONS", "OMISSION", "ADDITION")', '"CONDITIONS", "OMISSION")', 1),
    ("an aspect renamed", '"NUMBERS", "NEGATION", "OBLIGATION"', '"NUMBERS", "NEGATIONS", "OBLIGATION"', 1),
    ("verdict set grows", 'VERDICTS = ("OK", "ISSUE", "UNSURE")', 'VERDICTS = ("OK", "ISSUE", "UNSURE", "MAYBE")', 1),
    ("separator dot dropped", 'JOINERS = ".,\'' + chr(0x2019) + '"', 'JOINERS = ",\'' + chr(0x2019) + '"', 1),
    ("separator comma dropped", 'JOINERS = ".,\'' + chr(0x2019) + '"', 'JOINERS = ".\'' + chr(0x2019) + '"', 1),
    ("separator apostrophe dropped", 'JOINERS = ".,\'' + chr(0x2019) + '"', 'JOINERS = ".,' + chr(0x2019) + '"', 1),
    ("euro dropped", 'MONEY = "$' + chr(0x20ac) + chr(0xa3) + chr(0x20ba) + chr(0xa5) + '"', 'MONEY = "$' + chr(0xa3) + chr(0x20ba) + chr(0xa5) + '"', 1),
    ("dollar dropped", 'MONEY = "$' + chr(0x20ac) + chr(0xa3) + chr(0x20ba) + chr(0xa5) + '"', 'MONEY = "' + chr(0x20ac) + chr(0xa3) + chr(0x20ba) + chr(0xa5) + '"', 1),
    ("language too long allowed", "not 2 <= len(value) <= 3", "not 2 <= len(value) <= 4", 1),
    ("one letter language", "not 2 <= len(value) <= 3", "not 1 <= len(value) <= 3", 1),
    ("upper case language", 'any(c < "a" or c > "z" for c in value)', 'any(c < "A" or c > "z" for c in value)', 1),
    ("language letters unchecked", 'or any(c < "a" or c > "z" for c in value):', "or False:", 1),
    ("control characters allowed", "or any(ord(c) < 32 or ord(c) == 127 for c in text)", "or False", 1),
    ("delete character allowed", "ord(c) < 32 or ord(c) == 127", "ord(c) < 32", 1),
    ("same language allowed", 'if pair["source_lang"] == pair["target_lang"]:', "if False:", 1),
    ("identical texts allowed", 'if pair["source"].lower() == pair["target"].lower():', "if False:", 1),
    ("identical texts compared with case", 'if pair["source"].lower() == pair["target"].lower():', 'if pair["source"] == pair["target"]:', 1),
    ("whitespace kept", 'return " ".join(text.split())', "return text", 1),
    ("id ignores the target", '"target_lang": _language(target_lang), "target": _text(target, "target")}', '"target_lang": _language(target_lang), "target": ""}', 1),
    ("id ignores the direction", '"source_lang": _language(source_lang), "source": _text(source, "source"),', '"source_lang": "xx", "source": _text(source, "source"),', 1),
    ("duplicate allowed", 'if self.entries.get(record_id):\n            raise gl.vm.UserError("already registered")', "if False:\n            raise gl.vm.UserError(\"already registered\")", 1),
    ("full book allowed", "if position >= MAX_RECORDS:", "if position > MAX_RECORDS:", 1),
    ("count not advanced", "self.count = position + 1", "self.count = position", 1),
    ("registrant not recorded", '"by": _sender(), "registered": _now(), "status": "REGISTERED"', '"by": "", "registered": _now(), "status": "REGISTERED"', 1),
    ("registration time not recorded", '"registered": _now(), "status": "REGISTERED"', '"registered": 0, "status": "REGISTERED"', 1),
    ("anchor check not stored", '"anchors": _anchor_check(pair)', '"anchors": {"equal": True, "only_in_source": [], "only_in_target": []}', 1),
    ("settled pair judged again", 'if entry["status"] in ("MATCH", "DIFFERS"):', 'if entry["status"] == "MATCH":', 1),
    ("a difference judged again", 'if entry["status"] in ("MATCH", "DIFFERS"):', 'if entry["status"] == "DIFFERS":', 1),
    ("judgement limit off by one", 'if len(entry["judgements"]) >= MAX_JUDGEMENTS:', 'if len(entry["judgements"]) > MAX_JUDGEMENTS:', 1),
    ("gap exclusive", 'if entry["judgements"] and now < entry["judgements"][-1]["at"] + JUDGE_GAP:', 'if entry["judgements"] and now <= entry["judgements"][-1]["at"] + JUDGE_GAP:', 1),
    ("gap never", 'if entry["judgements"] and now < entry["judgements"][-1]["at"] + JUDGE_GAP:', "if False:", 1),
    ("gap counted from the first judgement", 'entry["judgements"][-1]["at"] + JUDGE_GAP', 'entry["judgements"][0]["at"] + JUDGE_GAP', 1),
    ("unreadable try stored", 'if reading["state"] != "OK":\n            return "UNREADABLE"', 'if False:\n            return "UNREADABLE"', 1),
    ("anchors flag ignored in the outcome", "status = _outcome(reading[\"aspects\"], entry[\"anchors\"][\"equal\"])", "status = _outcome(reading[\"aspects\"], True)", 1),
    ("anchors flag ignored by the validator", "_outcome(parsed[\"aspects\"], anchors_equal) == _outcome(mine[\"aspects\"], anchors_equal))", "_outcome(parsed[\"aspects\"], True) == _outcome(mine[\"aspects\"], True))", 1),
    ("judge time not recorded", '{"at": now, "by": _sender()', '{"at": 0, "by": _sender()', 1),
    ("judge sender not recorded", '{"at": now, "by": _sender()', '{"at": now, "by": ""', 1),
    ("status not updated", 'entry["status"] = status\n', "pass\n", 1),
    ("issues listed unsorted", 'return [name for name in ASPECTS if aspects[name]["verdict"] == "ISSUE"]', 'return [name for name in reversed(ASPECTS) if aspects[name]["verdict"] == "ISSUE"]', 1),
    ("an unsure counts as an issue", 'return [name for name in ASPECTS if aspects[name]["verdict"] == "ISSUE"]', 'return [name for name in ASPECTS if aspects[name]["verdict"] != "OK"]', 1),
    ("issue never differs", 'if _issues(aspects):\n        return "DIFFERS"', 'if False:\n        return "DIFFERS"', 1),
    ("match without anchors", 'if anchors_equal and all(', "if all(", 1),
    ("match despite doubt", 'all(aspects[name]["verdict"] == "OK" for name in ASPECTS)', 'any(aspects[name]["verdict"] == "OK" for name in ASPECTS)', 1),
    ("quote may be anywhere", "if not _on_text(quote, pair[side]):", 'if not _on_text(quote, pair["source"] + " " + pair["target"]):', 1),
    ("quote never checked", "if not _on_text(quote, pair[side]):", "if False:", 1),
    ("quote case sensitive", "_squash(quote).lower() in text.lower()", "_squash(quote) in text", 1),
    ("quote length unchecked", "return QUOTE_MIN <= len(quote) <= QUOTE_MAX and _squash(quote)", "return _squash(quote)", 1),
    ("side unchecked", 'if side not in ("source", "target"):\n        return None', 'if False:\n        return None', 1),
    ("keys not exact", 'if not isinstance(item, dict) or set(item) != {"verdict", "side", "quote"}:', "if not isinstance(item, dict):", 1),
    ("aspects not exact", "if not isinstance(raw, dict) or set(raw) != set(ASPECTS):", "if not isinstance(raw, dict):", 1),
    ("ok keeps its quote", 'return {"verdict": verdict, "side": "", "quote": ""}', 'return {"verdict": verdict, "side": side, "quote": quote}', 1),
    ("answer length unchecked", "if len(raw) > MAX_MODEL:\n                    continue", "if False:\n                    continue", 1),
    ("validator takes any leader text", "if not isinstance(proposed, str) or len(proposed) > MAX_MODEL:\n            return False", "if not isinstance(proposed, str):\n            return False", 1),
    ("validator skips the shape check", "if not _valid_reading(parsed, pair):\n            return False", "if not isinstance(parsed, dict):\n            return False", 1),
    ("validator ignores the issue set", "return (_issues(parsed[\"aspects\"]) == _issues(mine[\"aspects\"])\n                and _outcome(", "return (True\n                and _outcome(", 1),
    ("validator ignores the outcome", "and _outcome(parsed[\"aspects\"], anchors_equal) == _outcome(mine[\"aspects\"], anchors_equal))", "and True)", 1),
    ("validator takes any error", "return parsed[\"state\"] == mine[\"state\"]", "return True", 1),
    ("validator takes only a return", "if not isinstance(result, gl.vm.Return):\n            return False", "if False:\n            return False", 1),
    ("valid reading allows a changed quote", "if clean is None or clean != value[\"aspects\"][name]:", "if clean is None:", 1),
    ("valid reading allows any state", 'value["state"] != "OK" or not isinstance(value["aspects"], dict)', "not isinstance(value[\"aspects\"], dict)", 1),
    ("anchors ignore the left side", "a, b = _anchors(pair[\"source\"]), _anchors(pair[\"target\"])", "a, b = [], _anchors(pair[\"target\"])", 1),
    ("anchors ignore only-in-target", "only_source, only_target = _difference(a, b), _difference(b, a)", "only_source, only_target = _difference(a, b), []", 1),
    ("anchors ignore only-in-source", "only_source, only_target = _difference(a, b), _difference(b, a)", "only_source, only_target = [], _difference(b, a)", 1),
    ("anchors ignore repeats", "if item in rest:\n            rest.remove(item)", "if item in rest:\n            pass", 1),
    ("anchors three digits only", "if len(digits) >= 3 or before in MONEY", "if len(digits) >= 4 or before in MONEY", 1),
    ("anchors two digits count", "if len(digits) >= 3 or before in MONEY", "if len(digits) >= 2 or before in MONEY", 1),
    ("percent after ignored", 'or after in MONEY or after == "%":', "or after in MONEY:", 1),
    ("percent before ignored", 'or before == "%" or after', "or after", 1),
    ("money before ignored", "or before in MONEY or before ==", "or before ==", 1),
    ("money after ignored", "or after in MONEY or after ==", "or after ==", 1),
    ("space before skipped", 'if before == " " and i > 1:\n            before = text[i - 2]', "pass", 1),
    ("space after skipped", 'if after == " " and j + 1 < n:\n            after = text[j + 1]', "pass", 1),
    ("leading zeros dropped", 'digits = "".join(c for c in text[i:j] if c in DIGITS)', 'digits = "".join(c for c in text[i:j] if c in DIGITS).lstrip("0")', 1),
    ("separator kept in the number", 'digits = "".join(c for c in text[i:j] if c in DIGITS)', "digits = text[i:j]", 1),
    ("joiner at the end taken", 'text[j + 1:j + 2] != "" and text[j + 1] in DIGITS', 'text[j + 1:j + 2] != ""', 1),
    ("anchors unsorted", "return sorted(found)[:MAX_ANCHORS]", "return found[:MAX_ANCHORS]", 1),
    ("anchor cap off", "return sorted(found)[:MAX_ANCHORS]", "return sorted(found)", 1),
    ("page offset negative allowed", "or offset < 0 or", "or False or", 1),
    ("page limit zero allowed", "not 1 <= limit <= PAGE_LIMIT", "not 0 <= limit <= PAGE_LIMIT", 1),
    ("page not clipped", "range(offset, min(offset + limit, int(self.count)))", "range(offset, offset + limit)", 1),
    ("page type unchecked", "if type(offset) is not int or type(limit) is not int or", "if", 1),
    ("status of unknown", 'return json.loads(raw)["status"] if raw else "NONE"', 'return json.loads(raw)["status"] if raw else "REGISTERED"', 1),
    ("summary count wrong", '"judgements": len(entry["judgements"])', '"judgements": 1', 1),
    ("time parsing ignores the offset", "+ int(clock[0:2]) * 3600 + int(clock[3:5]) * 60 + int(clock[6:8]) - offset)", "+ int(clock[0:2]) * 3600 + int(clock[3:5]) * 60 + int(clock[6:8]))", 1),
]


def run_tests(directory: Path) -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/direct", "-q", "-x", "-p", "no:cacheprovider"],
                            cwd=directory, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    source = (ROOT / CONTRACT).read_text()
    with tempfile.TemporaryDirectory(prefix="mutation-") as tmp:
        base = Path(tmp)

        def prepare(name: str) -> Path:
            work = base / name
            shutil.copytree(ROOT / "contracts", work / "contracts")
            shutil.copytree(ROOT / "tests", work / "tests", ignore=shutil.ignore_patterns("__pycache__"))
            return work

        if not run_tests(prepare("clean")):
            print("The unmodified contract does not pass its tests; stopping.")
            return 2
        print("unmodified contract passes; %d mutants" % len(MUTANTS), flush=True)

        def one(index_item):
            index, (label, old, new, nth) = index_item
            parts = source.split(old)
            if len(parts) <= nth:
                return label, "NOT FOUND"
            mutated = old.join(parts[:nth]) + new + old.join(parts[nth:])
            if mutated == source:
                return label, "NO CHANGE"
            work = prepare("m%d" % index)
            (work / CONTRACT).write_text(mutated)
            caught = not run_tests(work)
            shutil.rmtree(work, ignore_errors=True)
            return label, "caught" if caught else "SURVIVED"

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(one, enumerate(MUTANTS)))
    bad = [(label, state) for label, state in results if state != "caught"]
    print("%d of %d mutants caught" % (len(results) - len(bad), len(results)))
    for label, state in bad:
        print("  %s: %s" % (state, label))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
