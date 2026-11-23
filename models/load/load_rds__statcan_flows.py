"""Load: StatCan macroeconomic flows and trade by NAICS -> Amazon RDS (country_profiles schema).

Reads the StatCan marts and writes them to the two dashboard fact tables. Dimension
tables keep their existing surrogate IDs; only regions and trading partners not seen
before are appended.

| Reads (data/marts/)                  | Writes (country_profiles.) | Method                                   |
|--------------------------------------|----------------------------|------------------------------------------|
| fct_macroecon_flows_yearly.csv       | fact_macroecon_flows       | update changed values + insert new rows  |
| fct_trade_by_naics_yearly.parquet    | fact_trade_by_naics        | update changed values + insert new rows  |

No rows are deleted. Existing rows whose value StatCan has revised are updated, rows
for new years, regions or partners are inserted, and everything else is left as is.
Trade by NAICS is monthly data summed by year, so its latest year is usually partial
(year to date); it is loaded as is and completed by the next refresh.
Not loaded: rows with a null value (they carry no data), and in trade by NAICS the
'Total of all industries' rows and the 'Unknown or unspecified' partner, which RDS
does not store.

Usage (from the repo root, after running the StatCan raw -> staging -> intermediate -> marts notebooks):
    python models/load/load_rds__statcan_flows.py                     # dry run: checks, plan, comparison
    python models/load/load_rds__statcan_flows.py --test              # same load into *_test tables only
    python models/load/load_rds__statcan_flows.py --write             # backup, then load (one transaction)
    python models/load/load_rds__statcan_flows.py --rollback YYYYMMDD # restore the backup taken that day

--test leaves the real tables and dimension tables untouched: it writes
fact_macroecon_flows_test and fact_trade_by_naics_test (copies of the real tables with
the updates/inserts applied), rebuilding them on every run. Remove with:
    DROP TABLE country_profiles.fact_macroecon_flows_test, country_profiles.fact_trade_by_naics_test;

--write first copies both fact tables in full to <table>_bak_<YYYYMMDD>. Once the
dashboard has been checked, drop the backups:
    DROP TABLE country_profiles.fact_macroecon_flows_bak_YYYYMMDD,
               country_profiles.fact_trade_by_naics_bak_YYYYMMDD;

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
MARTS_DIR = ROOT / "data" / "marts"
SCHEMA = "country_profiles"

# fact table -> mart file, key columns (dimension IDs), value column, series shown in the comparison
FACTS = {
    "fact_macroecon_flows": dict(file="fct_macroecon_flows_yearly.csv",
                                 key=["year", "region", "flow_type"], value="dollar_value", series="flow_type"),
    "fact_trade_by_naics": dict(file="fct_trade_by_naics_yearly.parquet",
                                key=["year", "trade_type", "trading_partner", "naics_id"], value="cad_value",
                                series="trade_type"),
}
EXCLUDED_PARTNERS = {"Unknown or unspecified"}  # trading partner not stored in RDS
TOLERANCE = 0.5  # values are in dollars; smaller differences are floating-point noise, not revisions

# dim table -> (id column, name column or expression)
DIMS = {
    "dim_macroecon_region": ("macroecon_region_id", "region"),
    "dim_macroecon_flow_type": ("macroecon_flow_type_id", "flow_type"),
    "dim_naic_trade_type": ("naic_trade_type_id", "trade_type"),
    "dim_naic_trading_partner": ("naic_trading_partner_id", "trading_partner"),
    "dim_naics": ("naics_id", "naics_code::int"),  # matched on the 4-digit NAICS code
}
FIXED_DIMS = {"dim_macroecon_flow_type", "dim_naic_trade_type", "dim_naics"}  # closed vocabularies: new values mean bad input


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
        **{f"UPDATE, INSERT on {t}": f"has_table_privilege('{SCHEMA}.{t}', 'UPDATE') AND "
                                     f"has_table_privilege('{SCHEMA}.{t}', 'INSERT')" for t in FACTS},
        **{f"INSERT on {t} (new members)": f"has_table_privilege('{SCHEMA}.{t}', 'INSERT')"
           for t in DIMS if t not in FIXED_DIMS},
    }
    print("\nPermissions:")
    results = {}
    for label, expr in checks.items():
        results[label] = bool(conn.execute(text(f"SELECT {expr}")).scalar())
        print(f"  {'OK     ' if results[label] else 'MISSING'} {label}")
    return results


def read_mart(table: str, marts_dir: Path = MARTS_DIR) -> pd.DataFrame:
    """Read a StatCan mart, drop the rows RDS does not store, and validate it."""
    f = FACTS[table]
    path = marts_dir / f["file"]
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    value = f["value"]
    if table == "fact_trade_by_naics":
        left_out = df["naics_code"].isna() | df["trading_partner"].isin(EXCLUDED_PARTNERS)
        print(f"{f['file']}: {left_out.sum():,} rows left out ('Total of all industries', "
              f"{', '.join(sorted(EXCLUDED_PARTNERS))})")
        df = df[~left_out].astype({"naics_code": int})
    df["year"] = pd.to_numeric(df["year"], errors="raise").astype(int)
    df[value] = pd.to_numeric(df[value], errors="coerce").astype(float)
    df = df.dropna(subset=[value]).reset_index(drop=True)
    for c in df.columns.difference(["year", "naics_code", value]):
        df[c] = df[c].astype("string").str.strip()

    key = df.columns.difference([value, "naics_name"]).tolist()
    assert not df.duplicated(key).any(), f"{f['file']}: duplicate keys"
    print(f"{f['file']:36s} rows={len(df):>10,}  years {df.year.min()}-{df.year.max()}")
    return df


def build_dim_maps(conn, values: dict[str, pd.Series]) -> tuple[dict, dict]:
    """Map names to existing IDs; allocate new IDs (max + 1 ...) for unseen names."""
    maps, new_members = {}, {}
    for t, (idc, namec) in DIMS.items():
        cur = pd.read_sql(text(f"SELECT {idc} AS id, {namec} AS name FROM {t}"), conn)
        assert not cur["name"].duplicated().any(), f"{t} has duplicate names"
        new = sorted(set(values[t].dropna()) - set(cur["name"]))
        assert not (new and t in FIXED_DIMS), f"unexpected values for {t}: {new}"
        start = int(cur["id"].max()) + 1
        new_members[t] = pd.DataFrame({idc: range(start, start + len(new)), namec: new})
        maps[t] = dict(zip(cur["name"], cur["id"])) | dict(zip(new, new_members[t][idc]))
        if new:
            print(f"new members for {t}: {new}")
    return maps, new_members


def split_rows(new: pd.DataFrame, cur: pd.DataFrame, key: list[str], value: str,
               tolerance: float = TOLERANCE) -> pd.DataFrame:
    """Decide what happens to each new row. Pure function: no database access.

    new: rows from the mart (key columns as IDs, value).
    cur: existing rows of the fact table (same columns).
    Returns every new row with the existing value in <value>_rds and an action:
      'unchanged' - same value as in RDS (within the tolerance)
      'update'    - StatCan revised the value, or the existing row is empty
      'insert'    - no existing row for this key (new year, region or partner)
    Existing rows are only ever updated, never deleted.
    """
    plan = new.merge(cur, on=key, how="left", suffixes=("", "_rds"), indicator=True)
    assert len(plan) == len(new), "a new row matches more than one existing row (duplicate keys in RDS)"
    old = plan[f"{value}_rds"]
    plan["action"] = "unchanged"
    plan.loc[old.isna() | ((plan[value] - old).abs() > tolerance), "action"] = "update"
    plan.loc[plan["_merge"] == "left_only", "action"] = "insert"
    return plan.drop(columns="_merge")


def plan_table(conn, table: str, new: pd.DataFrame, series_names: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Read the current rows, split the new rows into updates and inserts, and report the plan."""
    f = FACTS[table]
    key, value, series = f["key"], f["value"], f["series"]
    cur = pd.read_sql(text(f"SELECT {', '.join(key)}, {value} FROM {table}"), conn)
    cur[value] = cur[value].astype(float)
    assert new["year"].max() >= cur["year"].max(), f"{table}: new data ends before RDS ({cur.year.max()})"

    plan = split_rows(new, cur, key, value)
    updates, inserts = plan[plan.action == "update"], plan[plan.action == "insert"]
    filled = updates[f"{value}_rds"].isna().sum()
    print(f"\n{table} plan: {(plan.action == 'unchanged').sum():,} unchanged, {len(updates) - filled:,} values "
          f"revised, {filled:,} empty rows filled, {len(inserts):,} rows inserted "
          f"({(inserts.year == new.year.max()).sum():,} for {new.year.max()}), 0 deleted")
    print("  rows updated by year: ", updates.groupby("year").size().tail(8).to_dict())
    print("  rows inserted by year:", inserts.groupby("year").size().tail(8).to_dict())

    # Effect of the load on sum(value) per series and year, over the last seven years
    delta = pd.concat([updates[[series, "year"]].assign(d=updates[value] - updates[f"{value}_rds"].fillna(0)),
                       inserts[[series, "year"]].assign(d=inserts[value])])
    since = int(new["year"].max()) - 6
    now = cur[cur.year >= since].groupby([series, "year"])[value].sum()
    after = now.add(delta[delta.year >= since].groupby([series, "year"])["d"].sum(), fill_value=0)
    pct = (after / now - 1).mul(100).round(2).rename("pct").reset_index()
    pct[series] = pct[series].map(series_names)
    print(f"{table}: % change in sum({value}) after the load (blank = year not in RDS yet)")
    print(pct.pivot(index=series, columns="year", values="pct").to_string(na_rep=""))

    expected = {"rows": len(cur) + len(inserts), "sum": float(cur[value].sum()) + float(delta["d"].sum())}
    return updates[key + [value]], inserts[key + [value]], expected


def copy_rows(cur, table: str, df: pd.DataFrame) -> None:
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cols = ", ".join(f'"{c}"' for c in df.columns)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)", buf)
    print(f"  loaded {len(df):,} rows into {table}", flush=True)


def load(mode: str) -> None:
    """mode: 'dry' (report only), 'test' (write to *_test tables only), 'write' (load the real tables)."""
    macro = read_mart("fact_macroecon_flows")
    trade = read_mart("fact_trade_by_naics")

    eng = engine()
    with eng.connect() as conn:
        permissions = check_permissions(conn)
        maps, new_members = build_dim_maps(conn, {
            "dim_macroecon_region": macro.region,
            "dim_macroecon_flow_type": macro.flow_type,
            "dim_naic_trade_type": trade.trade_type,
            "dim_naic_trading_partner": trade.trading_partner,
            "dim_naics": trade.naics_code,
        })

        def ids(s: pd.Series, dim: str) -> pd.Series:
            return s.map(maps[dim]).astype(int)

        def names(dim: str) -> dict:
            return {v: k for k, v in maps[dim].items()}

        facts = {
            "fact_macroecon_flows": pd.DataFrame({
                "year": macro.year, "region": ids(macro.region, "dim_macroecon_region"),
                "flow_type": ids(macro.flow_type, "dim_macroecon_flow_type"), "dollar_value": macro.dollar_value}),
            # naic_trade_type_id / naic_trading_partner_id stay empty, as in the existing rows:
            # the IDs are stored in trade_type / trading_partner, which the Power BI view joins on.
            "fact_trade_by_naics": pd.DataFrame({
                "year": trade.year, "trade_type": ids(trade.trade_type, "dim_naic_trade_type"),
                "trading_partner": ids(trade.trading_partner, "dim_naic_trading_partner"),
                "naics_id": ids(trade.naics_code, "dim_naics"), "cad_value": trade.cad_value}),
        }
        plans = {
            "fact_macroecon_flows": plan_table(conn, "fact_macroecon_flows", facts["fact_macroecon_flows"],
                                               names("dim_macroecon_flow_type")),
            "fact_trade_by_naics": plan_table(conn, "fact_trade_by_naics", facts["fact_trade_by_naics"],
                                              names("dim_naic_trade_type")),
        }

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
    target = {t: f"{t}_test" if test else t for t in FACTS}

    stamp = dt.date.today().strftime("%Y%m%d")
    raw = eng.raw_connection()
    try:
        cur = raw.cursor()
        cur.execute(f"SET search_path TO {SCHEMA}")
        for t in FACTS:
            if test:
                cur.execute(f"DROP TABLE IF EXISTS {target[t]}")  # rebuilt on every test run
                cur.execute(f"CREATE TABLE {target[t]} AS TABLE {t}")
            else:  # exact copies, so --rollback restores the tables as they were
                cur.execute(f"CREATE TABLE {t}_bak_{stamp} AS TABLE {t}")
        print(f"  {'test tables created: *_test' if test else f'backups created: *_bak_{stamp}'}", flush=True)
        if not test:
            for t, df in new_members.items():
                if len(df):
                    copy_rows(cur, t, df)

        for t, (updates, inserts, _) in plans.items():
            key, value = FACTS[t]["key"], FACTS[t]["value"]
            cur.execute(f"CREATE TEMP TABLE updates_{t} ({', '.join(f'{c} integer' for c in key)}, "
                        f"{value} numeric) ON COMMIT DROP")
            copy_rows(cur, f"updates_{t}", updates)
            cur.execute(f"UPDATE {target[t]} f SET {value} = u.{value} FROM updates_{t} u WHERE "
                        + " AND ".join(f"f.{c} = u.{c}" for c in key))
            assert cur.rowcount == len(updates), f"updated {cur.rowcount} rows, expected {len(updates)}"
            print(f"  updated {cur.rowcount:,} {target[t]} rows", flush=True)
            copy_rows(cur, target[t], inserts)
        raw.commit()
        print("Committed.")
    except Exception:
        raw.rollback()
        print("Failed: transaction rolled back, RDS unchanged.")
        raise
    finally:
        raw.close()

    with eng.connect() as conn:
        for t, (_, _, expected) in plans.items():
            value = FACTS[t]["value"]
            n, s, y1 = conn.execute(text(f"SELECT COUNT(*), SUM({value}), MAX(year) FROM {target[t]}")).one()
            ok = n == expected["rows"] and abs(float(s) - expected["sum"]) <= 1e-9 * abs(expected["sum"]) + 1
            assert ok, f"{target[t]}: verification failed ({n:,} rows, sum {s})"
            print(f"verified {target[t]}: {n:,} rows, latest year {y1}")


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
    g.add_argument("--write", action="store_true", help="back up, then load the StatCan rows into RDS")
    g.add_argument("--rollback", metavar="YYYYMMDD", help="restore fact tables from the backups taken that day")
    args = p.parse_args()
    if args.rollback:
        rollback(args.rollback)
    else:
        load("write" if args.write else "test" if args.test else "dry")
