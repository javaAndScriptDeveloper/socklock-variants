from socklock_variants.naming import make_name, revision_name


def test_make_name():
    assert make_name("W12", "HOOK", "pain", 7) == "W12_HOOK_pain_v07"
    assert make_name("W12", "ONSCREEN", "social proof", 12) == "W12_ONSCREEN_social_proof_v12"


def test_revision_name():
    assert revision_name("W12_HOOK_pain_v07", set()) == "W12_HOOK_pain_v07b"
    taken = {"W12_HOOK_pain_v07b"}
    assert revision_name("W12_HOOK_pain_v07", taken) == "W12_HOOK_pain_v07c"
    # revising a revision continues the letter sequence of the base
    assert revision_name("W12_HOOK_pain_v07b", taken) == "W12_HOOK_pain_v07c"
