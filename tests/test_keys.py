import curses

from beepy_gpt.client.keys import BACK, BACKSPACE, DOWN, ENTER, UP, beepy_producible, normalize


def test_normalize():
    assert normalize("\n") == ENTER and normalize("\r") == ENTER
    assert normalize("\x1b") == BACK
    assert normalize("\x7f") == BACKSPACE and normalize(curses.KEY_BACKSPACE) == BACKSPACE
    assert normalize(curses.KEY_UP) == UP and normalize(curses.KEY_DOWN) == DOWN
    assert normalize("\t") == "TAB" and normalize("\x03") == "CTRL-C"
    assert normalize(curses.KEY_F0 + 5) == "F5"
    assert normalize("a") == "a" and normalize("é") == "é"
    assert normalize(curses.KEY_RESIZE) == "RESIZE"


def test_beepy_producible():
    assert beepy_producible(UP) and beepy_producible("y") and beepy_producible(BACK)
    assert not beepy_producible("TAB") and not beepy_producible("CTRL-C") and not beepy_producible("F5")
