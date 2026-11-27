"""Load: WIPO IP flows -> Amazon RDS (country_profiles schema).

Reads the intermediate WIPO tables and writes them to the three dashboard fact
tables. Dimension tables keep their existing surrogate IDs; only names not seen
before are appended.

| Reads (data/intermediate/)           | Writes (country_profiles.)  | Method                                   |
|--------------------------------------|-----------------------------|------------------------------------------|
| int_ip_flows.parquet                 | fact_yearly                 | update changed values + insert new rows  |
| int_ip_flows_by_class.parquet        | fact_class                  | full replace                             |
| int_ip_flows_by_residency.parquet    | fact_ip_total               | full replace                             |

fact_yearly: no rows are deleted. Existing rows whose value WIPO has revised are
updated, rows for new years or new country pairs are inserted, everything else is
left as is, including:
  - existing 'total' rows (Chinese trademark filings into China, 2014-2024) and the
    legacy indicators (ID5-ID9, PA9-PA10, TM5-TM9), which this load does not cover;
  - PA3 in the years RDS stores by applicant's origin.
Trademark applications into China for years after the existing 'total' data are
stored the same way, as 'total' = WIPO TM1a + TM1b (see CHINA_TOTAL_COVERS below).
Rows with a null count are not loaded (they carry no data).

Usage (from the repo root, after running the WIPO raw -> staging -> intermediate notebooks):
    python models/load/load_rds__wipo_ip_flows.py                     # dry run: checks, plan, comparison
    python models/load/load_rds__wipo_ip_flows.py --test              # same load into *_test tables only
    python models/load/load_rds__wipo_ip_flows.py --write             # backup, then load (one transaction)
    python models/load/load_rds__wipo_ip_flows.py --rollback YYYYMMDD # restore the backup taken that day

--test leaves the real tables, dimension tables and sequences untouched: it writes
fact_yearly_test (copy of fact_yearly with the updates/inserts applied), fact_class_test
and fact_ip_total_test, rebuilding them on every run. Remove with:
    DROP TABLE country_profiles.fact_yearly_test, country_profiles.fact_class_test,
               country_profiles.fact_ip_total_test;

--write first copies the three fact tables in full to <table>_bak_<YYYYMMDD>
(fact_class is the largest, about 4 GB). Once the dashboard has been checked, drop
the backups:
    DROP TABLE country_profiles.fact_yearly_bak_YYYYMMDD, country_profiles.fact_class_bak_YYYYMMDD,
               country_profiles.fact_ip_total_bak_YYYYMMDD;

Credentials come from .env in the repo root (RDS_HOST, RDS_PORT, RDS_DB, RDS_USER, RDS_PASSWORD).
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[2]
INT_DIR = ROOT / "data" / "intermediate"
SCHEMA = "country_profiles"
FACTS = ("fact_yearly", "fact_class", "fact_ip_total")
YEARLY_KEY = ["year", "origin", "indicator", "destination_office"]

YEARLY_INDICATORS = {"ID1a", "ID1b", "ID2a", "ID2b", "ID7", "PA1a", "PA1b", "PA2a", "PA2b", "PA3",
                     "TM1a", "TM1b", "TM2a", "TM2b", "TM7"}
CLASS_INDICATORS = {"ID3a", "ID3b", "ID4a", "ID4b", "PA4a", "PA5", "TM3a", "TM3b", "TM4a", "TM4b"}
TOTAL_INDICATORS = {"ID1a", "ID1b", "ID2a", "ID2b", "PA1a", "PA1b", "PA2a", "PA2b",
                    "TM1a", "TM1b", "TM2a", "TM2b"}

# Trademark applications into China are stored as one 'total' row per origin and year
# from 2014 (Chinese data, which already includes Madrid filings). For those years the
# WIPO TM1a/TM1b rows into China are skipped; for later years without 'total' (from
# 2025, WIPO reports China by origin) they are summed into 'total' = TM1a + TM1b.
# PA3 is left as is in the years RDS stores it by applicant's origin: the WIPO extract
# has office totals only (origin 'World'), which would double count next to them.
CHINA_TOTAL_COVERS = {"TM1a", "TM1b"}

# dim table -> (id column, name column)
DIMS = {
    "dim_origin": ("origin_id", "origin"),
    "dim_destination": ("destination_id", "destination_office"),
    "dim_indicator": ("dim_indicator_id", "indicator"),
    "dim_class_type": ("class_type_id", "class_type"),
    "dim_class_code": ("dim_class_code_id", "class_code"),
    "dim_ip_total_type": ("ip_total_type_id", "type"),
}
FIXED_DIMS = {"dim_indicator", "dim_class_type", "dim_class_code"}  # closed vocabularies: new values mean bad input


def engine():
    load_dotenv(ROOT / ".env")
    e = os.environ
    url = URL.create("postgresql+psycopg2", username=e["RDS_USER"], password=e["RDS_PASSWORD"],
                     host=e["RDS_HOST"], port=int(e["RDS_PORT"]), database=e["RDS_DB"])
    return create_engine(url, connect_args={"connect_timeout": 20, "options": f"-c search_path={SCHEMA}"})


def check_permissions(conn) -> dict[str, bool]:
    """Report every privilege the load needs; return {check: granted}."""
    checks = {
        "CREATE on schema (backup tables)": f"has_schema_privilege('{SCHEMA}', 'CREATE')",
        "TEMP on database (staging updates)": "has_database_privilege(current_database(), 'TEMP')",
        "UPDATE, INSERT on fact_yearly": f"has_table_privilege('{SCHEMA}.fact_yearly', 'UPDATE') AND has_table_privilege('{SCHEMA}.fact_yearly', 'INSERT')",
        "TRUNCATE, INSERT on fact_class": f"has_table_privilege('{SCHEMA}.fact_class', 'TRUNCATE') AND has_table_privilege('{SCHEMA}.fact_class', 'INSERT')",
        "TRUNCATE, INSERT on fact_ip_total": f"has_table_privilege('{SCHEMA}.fact_ip_total', 'TRUNCATE') AND has_table_privilege('{SCHEMA}.fact_ip_total', 'INSERT')",
        "USAGE on fact_yearly_id_seq": f"has_sequence_privilege('{SCHEMA}.fact_yearly_id_seq', 'USAGE')",
        "USAGE on fact_class_id_seq": f"has_sequence_privilege('{SCHEMA}.fact_class_id_seq', 'USAGE')",
    }
    print("\nPermissions:")
    results = {}
    for label, expr in checks.items():
        results[label] = bool(conn.execute(text(f"SELECT {expr}")).scalar())
        print(f"  {'OK     ' if results[label] else 'MISSING'} {label}")
    return results


def read_int(name: str, expected: set[str]) -> pd.DataFrame:
    df = pd.read_parquet(INT_DIR / name)
    df.columns = df.columns.str.lower()
    df["year"] = pd.to_numeric(df["year"], errors="raise").astype(int)
    df["count"] = pd.to_numeric(df["count"], errors="coerce")
    df = df.dropna(subset=["count"]).reset_index(drop=True)
    for c in df.columns.difference(["year", "count"]):
        df[c] = df[c].astype("string").str.strip()

    got = set(df["indicator"].unique())
    assert got == expected, f"{name}: missing {sorted(expected - got)}, unexpected {sorted(got - expected)}"
    key = df.columns.difference(["count"]).tolist()
    assert not df.duplicated(key).any(), f"{name}: duplicate keys"
    assert df["count"].ge(0).all(), f"{name}: negative counts"
    print(f"{name:36s} rows={len(df):>10,}  years {df.year.min()}-{df.year.max()}")
    return df


def build_dim_maps(conn, values: dict[str, pd.Series]) -> tuple[dict, dict]:
    """Map names to existing IDs; allocate new IDs (max + 1 ...) for unseen names."""
    maps, new_members = {}, {}
    for t, (idc, namec) in DIMS.items():
        cur = pd.read_sql(text(f'SELECT "{idc}" AS id, "{namec}" AS name FROM {t}'), conn)
        assert not cur["name"].duplicated().any(), f"{t} has duplicate names"
        new = sorted(set(values[t].dropna()) - set(cur["name"]))
        assert not (new and t in FIXED_DIMS), f"unexpected values for {t}: {new}"
        start = int(cur["id"].max()) + 1
        new_members[t] = pd.DataFrame({idc: range(start, start + len(new)), namec: new})
        maps[t] = dict(zip(cur["name"], cur["id"])) | dict(zip(new, new_members[t][idc]))
        if new:
            print(f"new members for {t}: {new}")
    return maps, new_members


def compare_to_rds(conn, table: str, new: pd.DataFrame, since: int) -> None:
    """Print % change of sum(count) per indicator/year vs what is in RDS now; stop if the new data ends earlier."""
    cur = pd.read_sql(text(f"""SELECT f.year, di.indicator, SUM(f.count) AS rds FROM {table} f
                               JOIN dim_indicator di ON di.dim_indicator_id = f.indicator
                               WHERE f.year >= :y GROUP BY 1, 2"""), conn, params={"y": since})
    cur = cur[cur["indicator"].isin(new["indicator"].unique())]
    assert new["year"].max() >= cur["year"].max(), f"{table}: new data ends before RDS ({cur.year.max()})"
    agg = new[new["year"] >= since].groupby(["year", "indicator"])["count"].sum().rename("new").reset_index()
    cmp = agg.merge(cur, on=["year", "indicator"], how="outer")
    cmp["pct"] = (cmp["new"] / cmp["rds"] - 1).mul(100).round(2)
    print(f"\n{table}: % change in sum(count) vs RDS (blank = year not in RDS yet)")
    print(cmp.pivot(index="indicator", columns="year", values="pct").to_string(na_rep=""))


def split_yearly(new: pd.DataFrame, cur: pd.DataFrame, *, world_id: int, pa3_id: int, china_id: int,
                 china_tm_ids: set[int], total_id: int,
                 china_total_years: set[int]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Decide what happens to each new fact_yearly row. Pure function: no database access.

    new: rows from the WIPO extract (year, origin, indicator, destination_office, office, count), as IDs.
    cur: existing fact_yearly rows for the same indicators plus 'total'
         (id, year, origin, indicator, destination_office, count).

    Trademark applications into China (TM1a/TM1b), by year:
      before the first year with 'total' rows -> loaded as TM1a/TM1b (as RDS already stores them)
      years that have 'total' rows            -> skipped; the existing 'total' rows are kept
      later years without 'total'             -> summed per origin into one 'total' row (TM1a + TM1b)
    PA3 in years RDS stores by applicant's origin -> skipped (the extract has office totals only).

    Returns (skipped, derived_total, plan):
      skipped       - new rows left out to avoid double counting
      derived_total - the 'total' rows built from WIPO's TM1a + TM1b into China
      plan          - every row to load, with action 'unchanged' / 'update' (incl. empty -> value) / 'insert'
    Existing rows are only ever updated, never deleted.
    """
    pa3_by_origin_years = set(cur.loc[(cur.indicator == pa3_id) & (cur.origin != world_id) & cur["count"].notna(), "year"])
    china_tm = (new.destination_office == china_id) & new.indicator.isin(china_tm_ids)
    to_total = china_tm & (new.year >= min(china_total_years, default=float("inf"))) & ~new.year.isin(china_total_years)
    skip = (china_tm & new.year.isin(china_total_years)) | ((new.indicator == pa3_id) & new.year.isin(pa3_by_origin_years))

    derived = (new[to_total].groupby(["year", "origin", "destination_office", "office"], as_index=False)["count"].sum()
               .assign(indicator=total_id)[new.columns])
    rows = pd.concat([new[~skip & ~to_total], derived], ignore_index=True)

    plan = rows.merge(cur, on=YEARLY_KEY, how="left", suffixes=("", "_rds"))
    assert len(plan) == len(rows), "a new row matches more than one existing fact_yearly row (duplicate keys in RDS)"
    plan["action"] = "unchanged"
    plan.loc[plan["count"] != plan["count_rds"], "action"] = "update"
    plan.loc[plan["id"].isna(), "action"] = "insert"
    return new[skip], derived, plan


def plan_yearly(conn, new: pd.DataFrame, maps: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the current fact_yearly rows, split the new rows into updates and inserts, and report the plan."""
    ind = maps["dim_indicator"]
    cur = pd.read_sql(text("SELECT id, year, origin, indicator, destination_office, count FROM fact_yearly "
                           "WHERE indicator = ANY(:ids)"), conn,
                      params={"ids": [int(ind[i]) for i in YEARLY_INDICATORS | {"total"}]})
    china_total_years = set(cur.loc[(cur.indicator == ind["total"]) & cur["count"].notna(), "year"])
    skipped, derived, plan = split_yearly(
        new, cur, world_id=maps["dim_origin"]["World"], pa3_id=ind["PA3"],
        china_id=maps["dim_destination"]["China"], china_tm_ids={ind[i] for i in CHINA_TOTAL_COVERS},
        total_id=ind["total"], china_total_years=china_total_years)
    updates, inserts = plan[plan.action == "update"], plan[plan.action == "insert"]

    def span(years) -> str:
        years = set(years)
        if not years:
            return "none"
        return str(min(years)) if min(years) == max(years) else f"{min(years)}-{max(years)}"

    print(f"\nfact_yearly kept as is: {len(skipped):,} new rows skipped "
          f"(TM1a/TM1b into China for {span(china_total_years)}, covered by 'total'; "
          f"PA3 for {span(skipped.loc[skipped.indicator == ind['PA3'], 'year'])}, stored by origin)")
    print(f"China trademarks for {span(derived.year)} stored as 'total' (WIPO TM1a + TM1b): "
          f"{len(derived):,} rows, {derived['count'].sum():,.0f} applications")
    filled = updates["count_rds"].isna().sum()
    print(f"fact_yearly plan: {(plan.action == 'unchanged').sum():,} unchanged, "
          f"{len(updates) - filled:,} values revised, {filled:,} empty rows filled, {len(inserts):,} rows inserted "
          f"({(inserts.year == new.year.max()).sum():,} for {new.year.max()}), 0 deleted")
    print("  rows inserted by year:", inserts.groupby("year").size().tail(8).to_dict())

    expected = cur.set_index("id")["count"]
    expected.loc[updates["id"].astype(int)] = updates["count"].values
    expected_sum = float(expected.sum()) + float(inserts["count"].sum())
    expected_rows = len(cur) + len(inserts)
    return (updates[["id", "count"]].astype({"id": int}),
            inserts[["year", "origin", "indicator", "destination_office", "office", "count"]],
            pd.DataFrame({"rows": [expected_rows], "sum": [expected_sum]}))


def copy_rows(cur, table: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)", buf)
    print(f"  loaded {len(df):,} rows into {table}", flush=True)


def load(mode: str) -> None:
    """mode: 'dry' (report only), 'test' (write to *_test tables only), 'write' (load the real tables)."""
    yearly = read_int("int_ip_flows.parquet", YEARLY_INDICATORS)
    klass = read_int("int_ip_flows_by_class.parquet", CLASS_INDICATORS)
    total = read_int("int_ip_flows_by_residency.parquet", TOTAL_INDICATORS)
    # The Locarno label file names the residual class "Other - Other / Not Specified"; RDS uses "Other".
    klass["class_code"] = klass["class_code"].replace({"Other - Other / Not Specified": "Other"})

    eng = engine()
    with eng.connect() as conn:
        permissions = check_permissions(conn)
        maps, new_members = build_dim_maps(conn, {
            "dim_origin": pd.concat([yearly.origin, klass.origin, total.origin]),
            "dim_destination": pd.concat([yearly.office, klass.office, total.office]),
            "dim_indicator": pd.concat([yearly.indicator, klass.indicator, total.indicator]),
            "dim_class_type": klass.class_type,
            "dim_class_code": klass.class_code,
            "dim_ip_total_type": total.type,
        })

        def ids(s: pd.Series, dim: str) -> pd.Series:
            return s.map(maps[dim]).astype(int)

        fact_yearly = pd.DataFrame({
            "year": yearly.year, "origin": ids(yearly.origin, "dim_origin"),
            "indicator": ids(yearly.indicator, "dim_indicator"),
            "destination_office": ids(yearly.office, "dim_destination"),
            "office": yearly.office, "count": yearly["count"]})
        fact_class = pd.DataFrame({
            "year": klass.year, "origin": ids(klass.origin, "dim_origin"),
            "destination_office": ids(klass.office, "dim_destination"),
            "indicator": ids(klass.indicator, "dim_indicator"),
            "class_type": ids(klass.class_type, "dim_class_type"),
            "class_code": ids(klass.class_code, "dim_class_code"), "count": klass["count"]})
        fact_ip_total = pd.DataFrame({
            "year": total.year, "office": ids(total.office, "dim_destination"),
            "origin": ids(total.origin, "dim_origin"), "type": ids(total.type, "dim_ip_total_type"),
            "indicator": ids(total.indicator, "dim_indicator"), "count": total["count"]})

        updates, inserts, expected = plan_yearly(conn, fact_yearly, maps)
        since = int(yearly["year"].max()) - 6
        compare_to_rds(conn, "fact_class", klass, since)
        compare_to_rds(conn, "fact_ip_total", total, since)

    if mode == "dry":
        print("\nDry run complete. Nothing was written. Re-run with --test or --write to load.")
        return
    test = mode == "test"
    needed = [k for k in permissions if not test or k.startswith(("CREATE", "TEMP"))]
    missing = [k for k in needed if not permissions[k]]
    if missing:
        raise SystemExit(f"Missing permissions: {'; '.join(missing)}. Nothing was written.")
    if test:
        assert not any(len(df) for df in new_members.values()), \
            "test mode does not write dimension tables, but this load would add new dimension members"
    yt, ct, tt = (f"{t}_test" if test else t for t in FACTS)

    stamp = dt.date.today().strftime("%Y%m%d")
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"SET search_path TO {SCHEMA}")
        if test:
            for t in (yt, ct, tt):
                cur.execute(f"DROP TABLE IF EXISTS {t}")  # rebuilt on every test run
            cur.execute(f"CREATE TABLE {yt} AS TABLE fact_yearly")
            cur.execute(f"CREATE TABLE {ct} AS TABLE fact_class WITH NO DATA")
            cur.execute(f"CREATE TABLE {tt} AS TABLE fact_ip_total WITH NO DATA")
            # Tables created this way have no id sequence, so ids are assigned here.
            cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {yt}")
            start = cur.fetchone()[0] + 1
            inserts = inserts.assign(id=range(start, start + len(inserts)))
            fact_class = fact_class.assign(id=range(1, len(fact_class) + 1))
            print(f"  test tables created: {yt}, {ct}, {tt}", flush=True)
        else:
            for t in FACTS:  # exact copies, so --rollback restores the tables as they were
                cur.execute(f"CREATE TABLE {t}_bak_{stamp} AS TABLE {t}")
            print(f"  backups created: *_bak_{stamp}", flush=True)
            for t, df in new_members.items():
                if len(df):
                    copy_rows(cur, t, df)

        cur.execute("CREATE TEMP TABLE yearly_updates (id integer PRIMARY KEY, count numeric) ON COMMIT DROP")
        copy_rows(cur, "yearly_updates", updates)
        cur.execute(f"UPDATE {yt} f SET count = u.count FROM yearly_updates u WHERE f.id = u.id")
        assert cur.rowcount == len(updates), f"updated {cur.rowcount} rows, expected {len(updates)}"
        print(f"  updated {cur.rowcount:,} {yt} rows", flush=True)
        copy_rows(cur, yt, inserts)

        if not test:
            cur.execute("TRUNCATE fact_class, fact_ip_total")
        copy_rows(cur, ct, fact_class)
        copy_rows(cur, tt, fact_ip_total)
        raw.commit()
        print("Committed.")
    except Exception:
        raw.rollback()
        print("Failed: transaction rolled back, RDS unchanged.")
        raise
    finally:
        raw.close()

    yearly_ids = ",".join(str(int(maps["dim_indicator"][i])) for i in YEARLY_INDICATORS | {"total"})
    with eng.connect() as conn:
        for t, rows, total_sum, where in [
            (yt, int(expected.rows[0]), float(expected["sum"][0]), f"indicator IN ({yearly_ids})"),
            (ct, len(fact_class), float(fact_class["count"].sum()), "TRUE"),
            (tt, len(fact_ip_total), float(fact_ip_total["count"].sum()), "TRUE"),
        ]:
            n, s, y1 = conn.execute(text(f"SELECT COUNT(*), SUM(count), MAX(year) FROM {t} WHERE {where}")).one()
            assert n == rows and abs(float(s) - total_sum) < 1, f"{t}: verification failed ({n:,} rows)"
            print(f"verified {t}: {n:,} rows, latest year {y1}")


def rollback(stamp: str) -> None:
    with engine().begin() as conn:
        for t in FACTS:
            conn.execute(text(f"TRUNCATE {t}"))
            conn.execute(text(f"INSERT INTO {t} SELECT * FROM {t}_bak_{stamp}"))
            print(f"restored {t} from {t}_bak_{stamp}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--test", action="store_true", help="load into *_test tables only (real tables untouched)")
    g.add_argument("--write", action="store_true", help="back up, then load the WIPO rows into RDS")
    g.add_argument("--rollback", metavar="YYYYMMDD", help="restore fact tables from the backups taken that day")
    args = p.parse_args()
    if args.rollback:
        rollback(args.rollback)
    else:
        load("write" if args.write else "test" if args.test else "dry")