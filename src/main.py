from dotenv import load_dotenv

load_dotenv()

import argparse
import asyncio
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import httpx
import yaml

from src.collectors.base import BaseCollector
from src.collectors.greenhouse import GreenhouseCollector
from src.collectors.lever import LeverCollector
from src.collectors.gupy import GupyCollector
from src.config import load_config
from src.orchestrator import CrawlerOrchestrator

logger = logging.getLogger("job_hunter_ats")


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="Job Hunter ATS Crawler Core")
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Path to YAML configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging",
    )
    args = parser.parse_args()
    setup_logging(args.verbose)

    try:
        orchestrator = CrawlerOrchestrator.from_config_file(args.config)
        new_jobs = asyncio.run(orchestrator.run())
        logger.info(f"Crawl cycle completed successfully. Notified {len(new_jobs)} jobs.")
    except Exception as exc:
        logger.critical(f"Crawler encountered a fatal error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
