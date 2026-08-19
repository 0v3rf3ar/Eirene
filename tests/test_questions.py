"""Turning a prose question into choices."""

from __future__ import annotations

import pytest

from eirene.core import questions

PLAN = """I can build a small TUI file manager in C with ncurses.

Planned feature set:

- **Navigation:** j/k move, h/l parent/enter
- **Rendering:** portable Unicode symbols per file type
- **Speed:** lazy stat() caching

Before I write anything, confirm what you want:"""

WITH_OPTIONS = """Here is the plan.

- background notes
- more notes

Which layout do you want?

1. Flat files in one directory
2. A src package with tests
3. Whatever you think is best"""


@pytest.mark.parametrize("text", [
    "Which database should I use?",
    "Do you want tests as well?",
    "Before I write anything, confirm what you want:",
    "Let me know which one you prefer:",
    PLAN,
    WITH_OPTIONS,
])
def test_a_waiting_reply_is_spotted(text):
    assert questions.wants_an_answer(text) is True


@pytest.mark.parametrize("text", [
    "I wrote the file and the tests pass.",
    "Done. Three files changed.",
    "",
    "   ",
    "The function returns None when the path is missing.",
    "```python\nwhat = input('which one?')\n```",
])
def test_a_finished_reply_is_left_alone(text):
    assert questions.wants_an_answer(text) is False


def test_options_come_from_below_the_question():
    assert questions.options_from(WITH_OPTIONS) == [
        "Flat files in one directory",
        "A src package with tests",
        "Whatever you think is best",
    ]


def test_a_list_above_the_question_is_not_a_choice():
    assert questions.options_from(PLAN) == [], \
        "the feature list is not a set of answers"


def test_one_option_is_not_a_choice():
    assert questions.options_from("Which?\n\n- only this") == []


def test_options_lose_their_markdown():
    text = "Which one?\n\n- **Fast** — uses more memory\n- *Small* — slower"
    assert questions.options_from(text) == ["Fast", "Small"]


def test_a_long_option_is_shortened():
    text = "Which?\n\n- " + "word " * 40 + "\n- short one"
    picked = questions.options_from(text)
    assert len(picked[0]) <= questions.MAX_OPTION_CHARS + 1
    assert picked[0].endswith("…")


def test_numbered_and_lettered_lists_both_work():
    for body in ("Which?\n1. one\n2. two", "Which?\na) one\nb) two",
                 "Which?\n- one\n- two", "Which?\n* one\n* two"):
        assert questions.options_from(body) == ["one", "two"], body


def test_options_stop_at_the_next_paragraph():
    text = "Which?\n\n- one\n- two\n\nI will start once you say."
    assert questions.options_from(text) == ["one", "two"]


def test_code_fences_are_ignored():
    text = "Here:\n\n```\n- not an option\n- nor this\n```\n\nWhich one?\n- real\n- also real"
    assert questions.options_from(text) == ["real", "also real"]


def test_the_question_is_the_title():
    assert questions.question_from(WITH_OPTIONS) == "Which layout do you want?"
    assert questions.question_from(PLAN) == "Before I write anything, confirm what you want"


def test_a_missing_question_still_gives_a_title():
    assert questions.question_from("no question here") == "what would you like?"


def test_an_option_labelled_option_keeps_its_words():
    assert questions.options_from("Which?\n- Option 1: use sqlite\n- Option 2: use postgres") == [
        "use sqlite", "use postgres"]
    assert questions.options_from("Which?\n- option\n- other") == ["option", "other"]


def test_too_many_options_are_trimmed():
    body = "Which?\n" + "\n".join(f"- choice number {i}" for i in range(20))
    assert len(questions.options_from(body)) == questions.MAX_OPTIONS
