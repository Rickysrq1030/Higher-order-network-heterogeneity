"""Run this paper figure from its local code and data."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from figure_pipeline import main


if __name__ == "__main__":
    main(HERE)

