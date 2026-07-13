# tests/test_tome_labels.py
from wiki_creator.tome_labels import appearance_label, tome_number


def test_tome_number_strips_leading_zero():
    assert tome_number("01-throne-of-glass") == "1"


def test_tome_number_double_digit_unchanged():
    assert tome_number("10-some-book") == "10"


def test_tome_number_decimal_novella():
    assert tome_number("04.5_tales-of-alagaesia") == "4.5"


def test_tome_number_zero_prefix_prequel():
    assert tome_number("00-the_hobbit") == "0"


def test_tome_number_no_leading_digits_falls_back_to_slug():
    assert tome_number("le-jeu-de-lange") == "le-jeu-de-lange"


def test_tome_number_empty_or_none():
    assert tome_number(None) == ""
    assert tome_number("") == ""


def test_appearance_label_empty_books():
    assert appearance_label([]) == ""


def test_appearance_label_single_book_fr():
    assert appearance_label(["01-throne-of-glass"]) == "Apparaît au tome 1"


def test_appearance_label_multi_book_fr():
    assert appearance_label(["01-throne-of-glass", "02-crown-of-midnight"]) == (
        "Apparaît au tome 1, dernière apparition tome 2"
    )


def test_appearance_label_single_book_en():
    assert appearance_label(["01-throne-of-glass"], lang="en") == "Appears in book 1"


def test_appearance_label_multi_book_en():
    assert appearance_label(
        ["01-throne-of-glass", "02-crown-of-midnight", "03-heir-of-fire"], lang="en"
    ) == "First appears in book 1, last appears in book 3"
