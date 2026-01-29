import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import yaml

from .config import settings


@dataclass(frozen=True)
class DatasetContract:
    dataset: str
    description: str
    primary_key: Optional[str]
    columns: Dict[str, Dict[str, Any]]
    quality: Dict[str, Any]
    drift_policy: Optional[str]

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DatasetContract":
        return DatasetContract(
            dataset=d["dataset"],
            description=d.get("description", ""),
            primary_key=d.get("primary_key"),
            columns=d.get("columns", {}) or {},
            quality=d.get("quality", {}) or {},
            drift_policy=d.get("drift_policy"),
        )


def load_contract(dataset: str) -> DatasetContract:
    path = os.path.join(settings.contracts_dir, f"{dataset}.yaml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Contract not found for dataset '{dataset}' at {path}")
    with open(path, "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)
    return DatasetContract.from_dict(d)
