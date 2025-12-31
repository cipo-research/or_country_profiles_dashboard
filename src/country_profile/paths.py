from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class DataPaths:
    root: Path
    raw_ip_indicators: Path
    stg_ip_indicators: Path
    stg_offices: Path
    stg_china: Path
    int_ip_flows: Path
    marts_ip_flows: Path




def resolve_root(user_root: str | None = None) -> Path:
    """Resolve a project root in a repo-agnostic way.
    Priority: CLI --root > $COUNTRY_PROFILE_ROOT > cwd.
    Ensures `data/` exists.
    """
    if user_root:
        root = Path(user_root).expanduser().resolve()
    else:
        env = os.environ.get("COUNTRY_PROFILE_ROOT")
        root = Path(env).expanduser().resolve() if env else Path.cwd().resolve()
    (root / "data").mkdir(parents=True, exist_ok=True)
    return root




def build_paths(root: Path) -> DataPaths:
    data = root / "data"
    raw_ip = data / "raw" / "wipo" / "ip_indicators"
    stg_ip = data / "staging" / "wipo" / "ip_indicators"
    stg_off = data / "staging" / "wipo" / "ip_offices"
    stg_cn = data / "staging" / "china"
    int_dir = data / "intermediate" 
    marts_dir = data / "marts" 


    # create output dirs
    for p in (stg_ip, stg_off, stg_cn, int_dir, marts_dir):
        p.mkdir(parents=True, exist_ok=True)


    return DataPaths(
        root=root,
        raw_ip_indicators=raw_ip,
        stg_ip_indicators=stg_ip,
        stg_offices=stg_off,
        stg_china=stg_cn,
        int_ip_flows=int_dir,
        marts_ip_flows=marts_dir,
    )
