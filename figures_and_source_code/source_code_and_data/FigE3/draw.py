"""Run the local ORH A2 figure entry point."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from paper_orh_a2 import render_figure

if __name__ == "__main__":
    render_figure(HERE)
