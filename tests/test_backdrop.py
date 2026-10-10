"""The face's empty pixels must match the surrounding theme."""

import pytest
from textual.color import Color

from eirene.ui.backdrop import faded_pixel_logo
from eirene.ui.splash import pixel_logo
from eirene.ui.theme import THEMES


@pytest.mark.parametrize("key", ["solarized-light", "gruvbox-light", "latte", "gruvbox"])
def test_face_has_no_rectangular_background(key):
    background = Color.parse(THEMES[key].background)
    source = pixel_logo(20, 10)
    face = faded_pixel_logo(20, 10, background)
    assert len(face.plain.splitlines()) == len(source.plain.splitlines())
    transparent_parts = 0
    for original, faded in zip(source.spans, face.spans):
        if (original.style.color.name == "#000000" or
                original.style.bgcolor.name == "#000000"):
            assert faded.style.bgcolor.get_truecolor() == background.rich_color.get_truecolor()
            transparent_parts += 1
    assert transparent_parts > 0
    assert any(span.style.color and
               span.style.color.get_truecolor() != background.rich_color.get_truecolor()
               for span in face.spans)
