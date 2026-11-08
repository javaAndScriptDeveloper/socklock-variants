from socklock_variants.checks import check_diversity, check_variant
from socklock_variants.config import Settings
from socklock_variants.models import Variant
from socklock_variants.script import parse_script

SCRIPT = parse_script('''W12 · Washer thief
HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
PROBLEM 2.5-7s | VO: "Every wash, one goes missing..."
PRODUCT 7-15s | VO: "SockLock magnets keep pairs together"
CTA 15-20s | VO: "Get your first pack"
''')
S = Settings()


def v(text, element="HOOK", adjacent=None, name="x"):
    return Variant(name=name, element=element, angle="pain", text=text, adjacent=adjacent)


def test_six_words_fit_hook_slot():
    assert check_variant(v("one two three four five six"), SCRIPT, S) == []


def test_seven_words_exceed_hook_slot():
    assert "timing" in check_variant(v("one two three four five six seven"), SCRIPT, S)


def test_firstline_uses_second_segment_slot():
    # PROBLEM is 4.5 s -> 11 words allowed
    assert check_variant(v(" ".join(["w"] * 11), element="FIRSTLINE"), SCRIPT, S) == []
    assert "timing" in check_variant(v(" ".join(["w"] * 12), element="FIRSTLINE"), SCRIPT, S)


def test_onscreen_max_words():
    assert check_variant(v("a b c d e f g", element="ONSCREEN"), SCRIPT, S) == []
    assert "timing" in check_variant(v("a b c d e f g h", element="ONSCREEN"), SCRIPT, S)


def test_risky_claim_flagged():
    assert "risky:guaranteed" in check_variant(v("Guaranteed results"), SCRIPT, S)
    assert "risky:never lose" in check_variant(v("Never lose a sock"), SCRIPT, S)


def test_adjacent_scope():
    ok = {"segment": "PROBLEM", "field": "vo", "text": "Yours could be next"}
    bad = {"segment": "CTA", "field": "vo", "text": "Buy"}
    assert check_variant(v("Lost one?", adjacent=ok), SCRIPT, S) == []
    assert "scope" in check_variant(v("Lost one?", adjacent=bad), SCRIPT, S)


def test_word_count_and_seconds_filled():
    var = v("Washer ate one again?")
    check_variant(var, SCRIPT, S)
    assert var.words == 4
    assert var.seconds == 1.6


def test_diversity_duplicate_opening_and_near_duplicate():
    vs = [
        v("Lost another sock again?", name="a"),
        v("Lost another sock today, friend", name="b"),
        v("Your washer is a thief", name="c"),
        v("Your washer is a thief!", name="d"),
        v("Magnets fix laundry day", name="e"),
    ]
    res = check_diversity(vs)
    assert "duplicate_opening" in res["b"]
    assert "near_duplicate" in res["d"]
    assert res["a"] == [] and res["e"] == []
