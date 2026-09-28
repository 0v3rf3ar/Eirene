"""Untrusted binary/control data must never operate the terminal."""
from eirene.core.text import safe_text
from eirene.ui.format import strip_escapes


def test_binary_controls_and_terminal_sequences_are_removed():
    payload = "hello\x00\x07\x9b2J\x1b]52;c;clipboard\x07\x1bPpayload\x1b\\world\n"
    assert safe_text(payload) == "helloworld\n"
    assert strip_escapes(payload) == "helloworld\n"


def test_printable_unicode_and_whitespace_survive():
    assert safe_text("سلام\t漢字\n") == "سلام\t漢字\n"
    assert safe_text("\ud800\u202eevil") == "evil"
