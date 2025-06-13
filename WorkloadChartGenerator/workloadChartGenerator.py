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
from settings import REPORTS_JSON_PATH, DEFAULT_SMOOTHING


class WorkloadGraph:
    """
    Класс для подготовки и визуализации графика рабочей нагрузки по входящим данным.
    """
    def __init__(self, input_data, start_date=None, end_date=None, smoothing=DEFAULT_SMOOTHING):
        self.input_data = input_data  # исходные данные для построения графика
        self.current_year = datetime.now().year  # текущий год
        self.start_date = start_date if start_date else datetime(self.current_year, 1, 8)
        self.end_date = end_date if end_date else datetime.now()
        self.smoothing = smoothing  # степень сглаживания
        self.base = None  # Data before smoothing
        self.data = None  # Data after smoothing

    def get_smooth(self) -> int:
        """
        Get smoothing window size.
        Returns:
            int: Smoothing window size
        """
        return self.smoothing

    def set_smooth(self, value: int):
        """
        Set smoothing window size and update data.
        Args:
            value (int): New smoothing window size
        """
        self.smoothing = value
        if self.base is not None:
            self._update_smooth()
        logging.info(f"Smooth set to {value}. Data updated.")

    def prepare_data(self):
        """
        Готовит данные для построения графика, применяет сглаживание если задано.
        """
        agg = {}
        for _, dates in self.input_data.items():
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
            lambda d: datetime.strptime(f"{self.current_year}-{d}", "%Y-%m-%d")
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
        if self.smoothing:
            self._update_smooth()

    def _update_smooth(self) -> 'WorkloadGraph':
        """
        Update smoothed data using current smoothing window.
        Returns:
            self
        """
        if self.base is None:
            raise ValueError("No data. Run prepare_data() first.")
        if self.smoothing and self.smoothing > 1:
            self.data = self.base.rolling(
                window=self.smoothing,
                min_periods=1
            ).mean()
        else:
            self.data = self.base
        return self

    def generate_graph(self):
        """
        Строит график на основе подготовленных данных и сохраняет его во временный файл.
        """
        if self.data is None or self.data.empty:
            logging.warning("No data to show.")
            return None
        fig, ax = plt.subplots(figsize=(14, 7))
        self.data.plot(ax=ax)
        date_form = DateFormatter("%m-%d")
        ax.xaxis.set_major_formatter(date_form)
        ax.set_xlabel("Date")
        ax.set_ylabel("Workload") 
        ax.set_title("Workload by Project") 
        plt.tight_layout()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(tempfile.gettempdir()) / f'workload_{ts}.png'
        try:
            fig.savefig(path, bbox_inches='tight')
            logging.info(f"Chart saved: {path}")
            plt.close(fig)
            return path
        except Exception as err:
            logging.error(f"Save failed: {err}", exc_info=True)
            plt.close(fig)
            return None

    def show_graph(self):
        """
        Показывает график для проверки корректности построения.
        """
        path = self.generate_graph()
        if path:
            logging.info(f"Done. Chart: {path}")
        else:
            logging.warning("Chart not saved.")


def run(
    raw: Dict[str, Any],
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    smoothing: int = DEFAULT_SMOOTHING
) -> Optional[Path]:
    """
    Make and save workload chart in one call.
    Args:
        raw (dict): Raw data
        start_date (datetime): Start date
        end_date (datetime): End date
        smoothing (int): Smoothing window
    Returns:
        Path or None
    """
    graph = WorkloadGraph(raw, start_date, end_date, smoothing)
    graph.prepare_data()
    return graph.generate_graph()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info(f"Looking for data file at: {REPORTS_JSON_PATH}")
    try:
        with open(REPORTS_JSON_PATH, "r", encoding="utf-8") as file:
            raw = json.load(file)
        chart_path = run(raw)
        if chart_path:
            graph = WorkloadGraph(raw)
            graph.show_graph()
        else:
            logging.warning("Chart not saved.")
    except FileNotFoundError:
        logging.error(f"No data file {REPORTS_JSON_PATH}.")
    except Exception as err:
        logging.error(f"Error: {err}", exc_info=True)
