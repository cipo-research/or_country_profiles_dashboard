from __future__ import annotations
import click

from country_profile.logging_utils import get_logger
from country_profile.paths import resolve_root, build_paths
from country_profile.pipelines.stage_wipo_indicators import stage
from country_profile.pipelines.build_int_ip_flows import build as build_nonclass
from country_profile.pipelines.build_int_ip_flows_by_class import build as build_class
from country_profile.pipelines.export_marts import export_yearly, export_yearly_by_class
from country_profile.sources.wipo_ip_indicators import fetch_all as fetch_wipo_all  # NEW


@click.group()
@click.option('--log-level', default='INFO', help='DEBUG, INFO, WARNING, ERROR')
@click.pass_context
def cli(ctx, log_level: str):
    ctx.ensure_object(dict)
    ctx.obj['logger'] = get_logger(level=log_level)


@cli.command('fetch-wipo')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None,
              help='Project root. Defaults to $COUNTRY_PROFILE_ROOT or CWD.')
@click.option('--from-year', type=int, default=1980, show_default=True)
@click.option('--to-year', type=int, default=None,
              help='Default = current_year - 2 (module default).')
@click.option('--overwrite', is_flag=True, default=False,
              help='Redownload and overwrite existing files.')
@click.option('--max-workers', type=int, default=8, show_default=True)
@click.pass_context
def fetch_wipo(ctx, root: str | None, from_year: int, to_year: int | None,
               overwrite: bool, max_workers: int):
    """Download all mapped WIPO IPS CSVs into data/raw/wipo/ip_indicators/."""
    logger = ctx.obj['logger']
    paths = build_paths(resolve_root(root))
    logger.info("Downloading WIPO raw to: %s", paths.raw_ip_indicators)
    fetch_wipo_all(paths, from_year=from_year, to_year=to_year,
                   overwrite=overwrite, max_workers=max_workers)
    logger.info("[bold green]Fetch complete.[/bold green]")


@cli.command('run-all')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None,
              help='Project root. Defaults to $COUNTRY_PROFILE_ROOT or CWD.')
@click.option('--allow-missing', is_flag=True, default=False,
              help='Process available raw files; warn for missing ones.')
@click.option('--with-class/--no-class', default=True,
              help='Also build/export class-based IP flows (PA5, TM4a/b, ID4a/b).')
@click.option('--fetch/--no-fetch', default=False,
              help='Download raw WIPO CSVs before staging.')
@click.option('--overwrite', is_flag=True, default=False,
              help='When used with --fetch, overwrite existing raw files.')
@click.option('--max-workers', type=int, default=8, show_default=True,
              help='When used with --fetch, concurrent download workers.')
@click.pass_context
def run_all(ctx, root: str | None, allow_missing: bool, with_class: bool, fetch: bool,
            overwrite: bool, max_workers: int):
    logger = ctx.obj['logger']
    root_path = resolve_root(root)
    paths = build_paths(root_path)

    logger.info("Root: %s", root_path)

    if fetch:
        logger.info("Fetching raw WIPO CSVs prior to staging...")
        fetch_wipo_all(paths, overwrite=overwrite, max_workers=max_workers)

    logger.info("Staging raw WIPO indicators → parquet...")
    stage(paths, allow_missing=allow_missing)

    logger.info("Building intermediate long table (int_ip_flows.parquet)...")
    build_nonclass(paths)

    if with_class:
        logger.info("Building intermediate class table (int_ip_flows_by_class.parquet)...")
        build_class(paths)

    logger.info("Exporting marts CSV.gz (fct_ip_flows_yearly.csv.gz)...")
    export_yearly(paths)

    if with_class:
        logger.info("Exporting class marts CSV.gz (fct_ip_flows_by_class_yearly.csv.gz)...")
        export_yearly_by_class(paths)

    logger.info("[bold green]Done. Raw → Staging → Intermediate → Marts completed.[/bold green]")


@cli.command('stage')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.option('--allow-missing', is_flag=True, default=False)
@click.pass_context
def stage_only(ctx, root: str | None, allow_missing: bool):
    paths = build_paths(resolve_root(root))
    stage(paths, allow_missing=allow_missing)


@cli.command('build-int')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.pass_context
def build_int(ctx, root: str | None):
    paths = build_paths(resolve_root(root))
    build_nonclass(paths)


@cli.command('build-int-class')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.pass_context
def build_int_class(ctx, root: str | None):
    paths = build_paths(resolve_root(root))
    build_class(paths)


@cli.command('export-marts')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.pass_context
def export_marts_cmd(ctx, root: str | None):
    paths = build_paths(resolve_root(root))
    export_yearly(paths)


@cli.command('export-marts-class')
@click.option('--root', type=click.Path(file_okay=False, dir_okay=True), default=None)
@click.pass_context
def export_marts_class_cmd(ctx, root: str | None):
    paths = build_paths(resolve_root(root))
    export_yearly_by_class(paths)


if __name__ == "__main__":
    cli()
