"""Command line entrypoint for the ingestion pipeline."""

from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv

from .config import load_config
from .pipeline import build_pipeline


load_dotenv()

def main(argv: list[str] | None = None) -> int:
    """Entrypoint used by the CLI script."""

    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )
    config = load_config()
    pipeline = build_pipeline(config)
    pipeline.run()
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(
        description="Ingest PDF documents into LlamaCloud and PostgreSQL.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level (default: INFO).",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
