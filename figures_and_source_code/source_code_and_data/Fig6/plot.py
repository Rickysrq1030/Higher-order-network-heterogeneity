"""Regenerate this figure and synchronize its publication files."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from figure_pipeline import main


if __name__ == "__main__":
    main(HERE)
