"""The O*NET loader's CSV reading (pipelines/ingest/load_onet.py); the database step is SQL."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

SKILLS = """O*NET-SOC Code,Title,Workplace Example,Element ID,Element Name,Hot Technology,In Demand
15-1252.00,Software Developers,Python,2.E.6.a,Object or component oriented development software,Y,Y
15-1252.00,Software Developers,Microsoft Excel,2.E.5.d,Spreadsheet software,Y,N
15-1252.00,Software Developers,Obscure Tool,2.E.5.d,Spreadsheet software,N,N
11-1011.00,Chief Executives,AdSense Tracker,2.E.6.f,Data base user interface software,N,N
17-2141.00,Mechanical Engineers,Dassault Systemes SolidWorks,2.E.1.a,CAD software,N,Y
"""
ZONES = """O*NET-SOC Code,Title,Job Zone,Date,Domain Source
15-1252.00,Software Developers,4,08/2023,Analyst
11-1011.00,Chief Executives,5,08/2023,Analyst
"""


def _load() -> ModuleType:
    path = ROOT / "pipelines" / "ingest" / "load_onet.py"
    spec = importlib.util.spec_from_file_location("load_onet", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, skills: str = SKILLS, zones: str = ZONES) -> tuple[Path, Path]:
    s, z = tmp_path / "software_skills.csv", tmp_path / "job_zones.csv"
    s.write_text(skills, encoding="utf-8")
    z.write_text(zones, encoding="utf-8")
    return s, z


def test_keeps_only_hot_or_in_demand_rows_and_their_occupations(tmp_path: Path) -> None:
    occupations, skills = _load().read_rows(*_write(tmp_path))
    assert skills == [
        {"soc_code": "15-1252.00", "example": "Python", "in_demand": True},
        {"soc_code": "15-1252.00", "example": "Microsoft Excel", "in_demand": False},
        {"soc_code": "17-2141.00", "example": "Dassault Systemes SolidWorks", "in_demand": True},
    ]
    # Chief Executives has no flagged row, so it is not loaded; an occupation missing from the
    # Job Zones file is kept with no zone.
    assert occupations == [
        {"code": "15-1252.00", "title": "Software Developers", "job_zone": 4},
        {"code": "17-2141.00", "title": "Mechanical Engineers", "job_zone": None},
    ]


def test_renamed_column_fails_loudly(tmp_path: Path) -> None:
    renamed = SKILLS.replace("Workplace Example", "Example")
    with pytest.raises(ValueError, match="Workplace Example"):
        _load().read_rows(*_write(tmp_path, skills=renamed))
