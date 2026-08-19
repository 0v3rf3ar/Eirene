"""One code palette, shared by the chat and the diffs."""

from __future__ import annotations

from pygments.style import Style
from pygments.token import (Comment, Error, Generic, Keyword, Literal, Name,
                            Number, Operator, Punctuation, String, Token,
                            Whitespace)
from rich.syntax import PygmentsSyntaxTheme

# The saturated ANSI brights, which is where the vividness comes from.
FOREGROUND = "#ffffff"
BLUE = "#5555ff"
GREEN = "#55ff55"
CYAN = "#55ffff"
YELLOW = "#ffff55"
MAGENTA = "#ff55ff"
RED = "#ff5555"
GREY = "#8a8a8a"
BACKGROUND = "#000000"


class Vivid(Style):
    """Keywords blue, calls green, builtins cyan, strings yellow."""

    name = "eirene-vivid"
    background_color = BACKGROUND
    highlight_color = "#303030"
    line_number_color = GREY

    styles = {
        Token: FOREGROUND,
        Whitespace: FOREGROUND,
        Error: RED,
        Comment: GREY,
        Comment.Hashbang: GREY,
        Comment.Multiline: GREY,
        Comment.Preproc: MAGENTA,
        Comment.Single: GREY,
        Comment.Special: GREY,

        Keyword: BLUE,
        Keyword.Constant: BLUE,
        Keyword.Declaration: BLUE,
        Keyword.Namespace: BLUE,
        Keyword.Pseudo: BLUE,
        Keyword.Reserved: BLUE,
        Keyword.Type: CYAN,

        Operator: FOREGROUND,
        Operator.Word: BLUE,
        Punctuation: FOREGROUND,

        Name: FOREGROUND,
        Name.Attribute: FOREGROUND,
        Name.Builtin: CYAN,
        Name.Builtin.Pseudo: CYAN,
        Name.Class: GREEN,
        Name.Constant: CYAN,
        Name.Decorator: CYAN,
        Name.Entity: FOREGROUND,
        Name.Exception: GREEN,
        Name.Function: GREEN,
        Name.Function.Magic: GREEN,
        Name.Label: MAGENTA,
        Name.Namespace: FOREGROUND,
        Name.Other: FOREGROUND,
        Name.Tag: BLUE,
        Name.Variable: FOREGROUND,
        Name.Variable.Class: CYAN,
        Name.Variable.Global: FOREGROUND,
        Name.Variable.Instance: FOREGROUND,
        Name.Variable.Magic: CYAN,

        Literal: YELLOW,
        Literal.Date: YELLOW,
        String: YELLOW,
        String.Affix: BLUE,
        String.Backtick: YELLOW,
        String.Char: YELLOW,
        String.Delimiter: YELLOW,
        String.Doc: YELLOW,
        String.Double: YELLOW,
        String.Escape: MAGENTA,
        String.Heredoc: YELLOW,
        String.Interpol: MAGENTA,
        String.Other: YELLOW,
        String.Regex: RED,
        String.Single: YELLOW,
        String.Symbol: YELLOW,

        Number: MAGENTA,
        Number.Bin: MAGENTA,
        Number.Float: MAGENTA,
        Number.Hex: MAGENTA,
        Number.Integer: MAGENTA,
        Number.Integer.Long: MAGENTA,
        Number.Oct: MAGENTA,

        Generic: FOREGROUND,
        Generic.Deleted: RED,
        Generic.Emph: f"italic {FOREGROUND}",
        Generic.Error: RED,
        Generic.Heading: f"bold {FOREGROUND}",
        Generic.Inserted: GREEN,
        Generic.Output: GREY,
        Generic.Prompt: GREY,
        Generic.Strong: f"bold {FOREGROUND}",
        Generic.Subheading: f"bold {FOREGROUND}",
        Generic.Traceback: RED,
    }


CODE_THEME = PygmentsSyntaxTheme(Vivid)
