# Translation Notary

**A public record of whether a translation keeps what the original text commits to. Numbers are compared by plain code; whether the meaning is kept is judged by validators, and every fault they report must be backed by words that are really in one of the two texts.**

Anyone registers a *pair*: a source text and its translation (20 to 3000 characters each, different languages). The pair gets an id (the first 20 hex digits of the SHA-256 of its normalised text) and sits in the book unjudged. Anyone may then ask the validators to judge it. The record shows what was found, by whom and when, and can be read by anyone.

* `contracts/translation_notary.py`: the Intelligent Contract (one Python file, holds no funds).
* `tests/direct`: 153 direct-mode tests (genlayer-test; the model is mocked). `tests/glsim`: 5 tests on a local 5-validator network.
* `scripts/mutation_check.py`: breaks the contract on purpose in 106 ways and checks that the tests notice (all 106 caught; output in `evidence/mutation-check.txt`).

Status: **v0.1.0, written for GenVM v0.4. Tested in memory and on a local simulator, and run on Studio with real validator models** (see [Live run](#live-run)).

## Why a contract for this

A translated contract, price list or notice can quietly change a number, drop a "not" or turn "must" into "may". A reader who only sees one language cannot tell. A public book that fixes the pair, compares the numbers by code and records an independent judgement gives everyone the same finding to point at, and nobody can edit it afterwards.

## How it works

| Step | Call | Rule |
|---|---|---|
| 1. Register | `register(source_lang, source_text, target_lang, target_text)` | Languages are 2 to 3 lower-case letters and must differ. Each text is 20 to 3000 characters after spaces are collapsed, with no control characters, and the two texts must not be equal ignoring case. The same pair cannot be registered twice. The book holds at most 200 pairs. |
| 2. Judge | `judge(record_id)` | Anyone. Not once the pair is settled (`MATCH` or `DIFFERS`). At most 3 judgements per pair, at least 60 seconds apart. |
| 3. Read | `get_record_json`, `get_status`, `get_record_id`, `get_anchor_check`, `get_count`, `get_page_json(offset, limit)` | `get_page_json` returns up to 50 summaries, oldest first. |

### The part that needs no model: anchors

The contract lists the numbers that carry weight in both texts: three or more digits, or a number next to `%` or a currency sign (`$ € £ ₺ ¥`). Punctuation inside a number is ignored, so `1,500` and `1.500` are the same anchor. It then says which anchors only one side has, counting repeats. `0.5%` and `5%` are different anchors, which is a difference worth showing. Every validator computes the identical answer.

### The part validators judge

The model reads seven aspects and answers `OK`, `ISSUE` or `UNSURE` for each: `NUMBERS`, `NEGATION`, `OBLIGATION` (must / may / must not), `NAMES`, `CONDITIONS`, `OMISSION`, `ADDITION`. For every `ISSUE` it must name the side (`source` or `target`) and copy 8 to 200 characters from that side. **The contract, not the model, checks the quotation**: after collapsing spaces and ignoring case it must occur in that text. An answer in any other shape, or with a quotation that is not there, is an *error*, never an outcome. Both texts go to the model as untrusted data between markers and the prompt says never to obey them.

The outcome is plain code on that reading:

| Outcome | When |
|---|---|
| `MATCH` | every aspect is `OK` and the anchors are identical |
| `DIFFERS` | at least one aspect is an `ISSUE` |
| `UNCLEAR` | no `ISSUE`, but something is `UNSURE` or the anchors differ |

`MATCH` and `DIFFERS` are final. `UNCLEAR` may be judged again.

### What the validators must agree on

Validators run the model themselves (`gl.vm.run_nondet_default`). A validator accepts the leader's reading only if

1. it is exactly well formed: the seven keys, nothing else, and every quotation really in the text it names;
2. both reach the same **set of aspects flagged `ISSUE`**; and
3. both reach the same **outcome**.

Those two are everything that decides what is stored, so nothing that can change the outcome is left loose. They need not agree on the quotation itself (two good quotes for the same fault are both fine), nor on `OK` versus `UNSURE` when the outcome is the same. Two answers of "the model could not answer cleanly" agree with each other; an error against a reading does not. When there is no clean answer, `judge` returns `UNREADABLE` and stores nothing.

## What the record does not show

* It is a **model's reading, not a certified translation or legal advice.** It can miss a fault, or flag one that a human would accept. `MATCH` means the validators' models found nothing, not that nothing is wrong.
* The anchors cover only numbers. A changed name, a dropped clause or a wrong tense is found only by the model.
* The texts are stored on chain exactly as registered; the contract cannot tell who wrote the translation or whether the source is the original.
* Texts are limited to 3000 characters; a long document has to be registered in parts.
* Anyone can register any pair, so the book proves what was judged, not that the pair is genuine.

## Run the tests

```bash
pip install genlayer-test            # direct mode
python3 -m pytest tests/direct       # the model is mocked
pip install glsim fastapi uvicorn numpy
python3 -m pytest tests/glsim        # 5 tests on a local 5-validator network
python3 scripts/mutation_check.py 3  # breaks the contract 106 ways; survivors are listed
```

The contract file carries the runner hash of the published GenVM; the local harnesses ship their own, so the tests build `build/translation_notary_local.py` (not committed) with only that first line swapped.

## Live run

Deployed on GenLayer Studio (Studionet, Studio v0.123.2, runner `v0.4.0-rc1`) on 25 November 2026, with five validators running different models.

* Contract: `0xaF9DEe6c6B2Ea59c35955388aBd0e4a08B9bF274`
  ([Explorer](https://explorer-studio.genlayer.com/address/0xaF9DEe6c6B2Ea59c35955388aBd0e4a08B9bF274))
* Deploy transaction: `0xff7928480db60058a0521daabe579655cb905632c9db9ed27eb78614d62972ae` (FINALIZED, SUCCESS)

Two pairs were registered and judged (English lease clause and its Turkish translation):

| Pair | What was different | Result of `judge` |
|---|---|---|
| `ed2d3da1d5b877563b5b` | nothing (`1,500 euros` and `1.500 euro`) | `{"id": "ed2d3da1d5b877563b5b", "issues": [], "status": "MATCH"}` |
| `80eacb296d900fe26e9b` | the translation says `2.500 euro` | `{"id": "80eacb296d900fe26e9b", "issues": ["NUMBERS"], "status": "DIFFERS"}` (register: `0xce0f6242770dbdd2b43d4e297b33c2be19995ed83c05bd62ed2ab4144f2de2e0`) |

The Explorer lists the deploy, both `register` calls and the first `judge` as FINALIZED, SUCCESS and Accepted; the outputs above are the return values of the two `judge` calls as shown in Studio. This is two judgements of one short clause, not a measurement of how often validators agree on other texts.

## Licence

MIT.
