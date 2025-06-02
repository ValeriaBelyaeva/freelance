import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from matplotlib.dates import DateFormatter
import logging
import os
import tempfile
from typing import Optional, Dict, Any


class WorkloadChartGenerator:
    """
    Makes and saves workload charts from raw data.
    """
    
    def __init__(self, raw: Dict[str, Any], year: int = 2025, smooth: int = 3):
        """
        Args:
            raw (dict): Raw workload data
            year (int): Year for the chart
            smooth (int): Smoothing window size
        """
        self.raw = raw
        self.year = year
        self._smooth = smooth
        self.base = None  # Data before smoothing
        self.data = None  # Data after smoothing

    def get_smooth(self) -> int:
        """
        Get smoothing window size.
        Returns:
            int: Smoothing window size
        """
        return self._smooth

    def set_smooth(self, value: int):
        """
        Set smoothing window size and update data.
        Args:
            value (int): New smoothing window size
        """
        self._smooth = value
        if self.base is not None:
            self._update_smooth()
        logging.info(f"Smooth set to {value}. Data updated.")

    def prepare(self) -> 'WorkloadChartGenerator':
        """
        Prepare data for chart. This method:
        1. Aggregates workload percentages for each project and date from raw input.
        2. Converts aggregated data into a pandas DataFrame.
        3. Adds a datetime column for each date.
        4. Creates a pivot table with dates as index and projects as columns.
        5. Filters out rows where the total workload is zero (removes empty days).
        6. Stores the result in self.base.
        7. Calls _update_smooth to apply smoothing to the data.
        Returns:
            self
        """
        agg = {}
        for _, dates in self.raw.items():
            for date, projs in dates.items():
                for proj, (percent, _) in projs.items():
                    key = (date, proj)
                    agg[key] = agg.get(key, 0) + percent
        recs = [
            {"date": date, "project": proj, "percent": val} 
            for (date, proj), val in agg.items()
        ]
        df = pd.DataFrame(recs)
        df["dt"] = df["date"].apply(
            lambda d: datetime.strptime(f"{self.year}-{d}", "%Y-%m-%d")
        )
        piv = (
            df.pivot_table(
                index="dt",
                columns="project",
                values="percent",
                fill_value=0
            ).sort_index()
        )
        mask = piv.sum(axis=1) > 0
        self.base = piv[mask]
        self._update_smooth()
        return self

    def _update_smooth(self) -> 'WorkloadChartGenerator':
        """
        Update smoothed data using current smoothing window.
        Returns:
            self
        """
        if self.base is None:
            raise ValueError("No data. Run prepare() first.")
        if self._smooth and self._smooth > 1:
            self.data = self.base.rolling(
                window=self._smooth,
                min_periods=1
            ).mean()
        else:
            self.data = self.base
        return self

    def save(
        self,
        size: tuple = (14, 7),
        legend: str = "upper left",
        anchor: tuple = (1.02, 1),
        show: bool = False
    ) -> Optional[Path]:
        """
        Save chart to file.
        Args:
            size (tuple): Figure size
            legend (str): Legend location
            anchor (tuple): Legend anchor
            show (bool): Show plot
        Returns:
            Path or None
        """
        if self.data is None or self.data.empty:
            logging.warning("No data to show.")
            return None
        fig, ax = plt.subplots(figsize=size)
        self.data.plot(ax=ax)
        date_form = DateFormatter("%m-%d")
        ax.xaxis.set_major_formatter(date_form)
        ax.set_xlabel("Date")
        ax.set_ylabel("Workload") 
        ax.set_title("Workload by Project") 
        ax.legend(title="Project", loc=legend, bbox_to_anchor=anchor)
        plt.tight_layout()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(tempfile.gettempdir()) / f'workload_{ts}.png'
        try:
            fig.savefig(path, bbox_inches='tight')
            logging.info(f"Chart saved: {path}")
            if show:
                plt.show()
            plt.close(fig)
            return path
        except Exception as err:
            logging.error(f"Save failed: {err}", exc_info=True)
            plt.close(fig)
            return None


def run(
    raw: Dict[str, Any],
    year: int = 2025,
    smooth: int = 3
) -> Optional[Path]:
    """
    Make and save workload chart in one call.
    Args:
        raw (dict): Raw data
        year (int): Year
        smooth (int): Smoothing window
    Returns:
        Path or None
    """
    gen = WorkloadChartGenerator(raw, year=year, smooth=smooth)
    gen.prepare()
    return gen.save()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    script_dir = Path(__file__).resolve().parent
    json_file_path = script_dir / "reports.json"
    logging.info(f"Looking for data file at: {json_file_path}")
    try:
        with json_file_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        chart_path = run(raw, year=2025, smooth=3)
        if chart_path:
            logging.info(f"Done. Chart: {chart_path}")
        else:
            logging.warning("Chart not saved.")
    except FileNotFoundError:
        logging.error(f"No data file {json_file_path}.")
    except Exception as err:
        logging.error(f"Error: {err}", exc_info=True)
