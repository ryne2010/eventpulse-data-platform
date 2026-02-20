import pandas as pd

from eventpulse.schema import infer_schema, schema_hash


def test_schema_hash_is_order_independent() -> None:
    df_a = pd.DataFrame({"b": [1, 2], "a": ["x", "y"]})
    df_b = pd.DataFrame({"a": ["x", "y"], "b": [1, 2]})

    schema_a = infer_schema(df_a)
    schema_b = infer_schema(df_b)

    assert schema_hash(schema_a) == schema_hash(schema_b)
