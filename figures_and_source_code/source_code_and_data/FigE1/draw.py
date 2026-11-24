"""Render this figure from its local ORH-PGG data."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from paper_orh_pgg import render_figure


if __name__ == "__main__":
    render_figure(HERE)
