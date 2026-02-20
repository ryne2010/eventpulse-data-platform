import pytest

from eventpulse.naming import normalize_dataset_name


def test_normalize_dataset_name_lowercases():
    assert normalize_dataset_name("Parcels") == "parcels"


@pytest.mark.parametrize(
    "name",
    [
        "",  # empty
        "-bad",  # invalid start
        "123bad",  # must start with letter
        "bad-name",  # hyphen not allowed
        "bad name",  # whitespace
        "bad/name",  # path separator
        "bad.name",  # dot
    ],
)
def test_normalize_dataset_name_rejects_invalid(name: str):
    with pytest.raises(ValueError):
        normalize_dataset_name(name)


def test_normalize_dataset_name_length_limit():
    long_name = "a" + ("b" * 70)
    with pytest.raises(ValueError):
        normalize_dataset_name(long_name)
