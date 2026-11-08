from socklock_variants.script import parse_script

SAMPLE = '''W12 · Washer thief
HOOK 0-2.5s | VO: "Lost another sock?" | ON-SCREEN: "Your washer eats socks"
PROBLEM 2.5-7s | VO: "Every wash, one goes missing..."
PRODUCT 7-15s | VO: "SockLock magnets keep pairs together"
CTA 15-20s | VO: "Get your first pack — 30% off"
'''


def test_parses_sample():
    s = parse_script(SAMPLE)
    assert s.winner_id == "W12"
    assert s.title == "Washer thief"
    assert [seg.name for seg in s.segments] == ["HOOK", "PROBLEM", "PRODUCT", "CTA"]
    hook = s.segments[0]
    assert hook.seconds == 2.5
    assert hook.vo == "Lost another sock?"
    assert hook.onscreen == "Your washer eats socks"
    assert s.segments[1].onscreen == ""


def test_curly_quotes_crlf_and_en_dash():
    text = "W3\r\nHOOK 0–3s | VO: “Socks vanish?” | ON-SCREEN: ‘Again?’\r\nCTA 3–8s | VO: Buy now\r\n"
    s = parse_script(text)
    assert s.winner_id == "W3"
    assert s.segments[0].seconds == 3.0
    assert s.segments[0].vo == "Socks vanish?"
    assert s.segments[0].onscreen == "Again?"
    assert s.segments[1].vo == "Buy now"


def test_unparseable_falls_back():
    text = "Lost a sock again? Our magnets keep pairs together. Order today."
    s = parse_script(text)
    assert s.winner_id == "W00"
    assert len(s.segments) == 1
    seg = s.segments[0]
    assert seg.name == "SCRIPT"
    assert seg.vo == text
    assert seg.start is None and seg.seconds is None
