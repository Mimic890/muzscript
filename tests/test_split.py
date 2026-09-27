from muz.actions.split import normalize_list, split_value
from muz.config import default_rules

R = default_rules()


def split(v):
    return normalize_list([v], R.artist_separators, R.artist_exceptions, R.artist_aliases)


def test_basic_separators():
    assert split("A feat. B") == ["A", "B"]
    assert split("A, B & C") == ["A", "B", "C"]
    assert split("A ft. B x C") == ["A", "B", "C"]
    assert split("A FEAT. B") == ["A", "B"]


def test_exceptions_are_not_split():
    assert split("Simon & Garfunkel") == ["Simon & Garfunkel"]
    assert split("Tyler, The Creator feat. Kali Uchis") == ["Tyler, The Creator", "Kali Uchis"]
    assert split("earth, wind & fire") == ["earth, wind & fire"]


def test_words_containing_separators_survive():
    # " x " needs spaces, so names with an x inside stay whole
    assert split("Xzibit") == ["Xzibit"]
    assert split("Alex Clare") == ["Alex Clare"]


def test_aliases_and_dedupe():
    aliases = {"Eldzhey": ["Allj", "Элджей"]}
    out = normalize_list(["Allj feat. Элджей, Other"], R.artist_separators, [], aliases)
    assert out == ["Eldzhey", "Other"]


def test_split_value_without_separators():
    assert split_value(" A ", []) == ["A"]
