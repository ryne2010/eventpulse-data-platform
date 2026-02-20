import pandas as pd

from eventpulse.contracts import DatasetContract
from eventpulse.quality import validate_df


def test_validate_df_missing_required_column_fails() -> None:
    contract = DatasetContract.from_dict(
        {
            "dataset": "unit_test",
            "description": "",
            "primary_key": None,
            "columns": {
                "id": {"type": "string", "required": True, "unique": True},
                "value": {"type": "number", "required": False},
            },
            "quality": {},
            "drift_policy": "warn",
        }
    )

    df = pd.DataFrame({"value": [1.0, 2.0]})
    result = validate_df(df, contract)

    assert result.passed is False
    assert any("Missing required columns" in e for e in result.errors)


def test_validate_df_primary_key_uniqueness() -> None:
    contract = DatasetContract.from_dict(
        {
            "dataset": "unit_test",
            "description": "",
            "primary_key": "id",
            "columns": {
                "id": {"type": "string", "required": True, "unique": True},
                "value": {"type": "number", "required": False},
            },
            "quality": {},
            "drift_policy": "warn",
        }
    )

    df = pd.DataFrame({"id": ["a", "a"], "value": [1.0, 2.0]})
    result = validate_df(df, contract)

    assert result.passed is False
    assert any("Primary key" in e for e in result.errors)
