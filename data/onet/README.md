# O*NET data

Two files from the O*NET 31.0 Database, unmodified, downloaded 2026-11-12:

- `software_skills.csv` from <https://www.onetcenter.org/dl_files/database/db_31_0_csv/software_skills.csv>
- `job_zones.csv` from <https://www.onetcenter.org/dl_files/database/db_31_0_csv/job_zones.csv>

`make ingest-onet` loads them (`pipelines/ingest/load_onet.py`). The loader keeps only the rows
flagged Hot Technology or In Demand.

This page includes information from the [O*NET 31.0 Database](https://www.onetcenter.org/database.html)
by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA). Used under
the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) license. O*NET® is a trademark of
USDOL/ETA.
