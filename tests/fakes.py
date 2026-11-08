import json


class FakeLLM:
    """Returns canned responses in order and records every call."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, messages):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        if not self.responses:
            raise AssertionError("FakeLLM ran out of responses")
        return self.responses.pop(0)


def variants_json(*items):
    return json.dumps({"variants": [
        {"element": e, "angle": a, "text": t, "adjacent": None, "why": "test"} for e, a, t in items
    ]})
