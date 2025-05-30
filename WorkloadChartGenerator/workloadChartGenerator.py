import json
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
from matplotlib.dates import DateFormatter
import logging
import os

class WorkloadChartGenerator:
    def __init__(self, json_path: str, year: int = 2025, rolling_window: int = 3):
        self.path = Path(json_path)
        self.year = year
        self.rolling_window = rolling_window
        self.raw = None
        self.df = None
        self.df_original = None # To store original data before smoothing

    def load(self):
        with self.path.open("r", encoding="utf-8") as f:
            self.raw = json.load(f)
        return self

    def aggregate(self):
        agg = {}
        for _, dates in self.raw.items():
            for date_str, projects in dates.items():
                for proj, (percent, _) in projects.items():
                    key = (date_str, proj)
                    agg[key] = agg.get(key, 0) + percent
        records = [{"date": d, "project": p, "percent": v} for (d, p), v in agg.items()]
        df = pd.DataFrame(records)
        df["date_dt"] = df["date"].apply(
            lambda s: datetime.strptime(f"{self.year}-{s}", "%Y-%m-%d")
        )
        pivot = (
            df.pivot_table(index="date_dt", columns="project", values="percent", fill_value=0)
              .sort_index()
        )
        mask = pivot.sum(axis=1) > 0
        self.df_original = pivot[mask]

        if self.rolling_window and self.rolling_window > 1:
            self.df = self.df_original.rolling(window=self.rolling_window, min_periods=1).mean()
        else:
            self.df = self.df_original
        return self

    def plot(self, figsize=(14, 7), legend_loc="upper left", legend_bbox=(1.02, 1), save_path: str = None, show_plot: bool = False):
        if self.df is None or self.df.empty:
            logging.warning("No data to display for the chart.") # Return None if no data
            return None
        
        fig, ax = plt.subplots(figsize=figsize)
        self.df.plot(ax=ax)

        date_form = DateFormatter("%m-%d")
        ax.xaxis.set_major_formatter(date_form)

        ax.set_xlabel("Date (MM-DD)")
        ax.set_ylabel("Workload") 
        ax.set_title("Department Workload by Project") 
        ax.legend(title="Project", loc=legend_loc, bbox_to_anchor=legend_bbox)
        plt.tight_layout()

        # File saving logic
        if save_path is None:
            charts_dir = Path(__file__).resolve().parent / "charts"
            if not charts_dir.exists():
                try:
                    charts_dir.mkdir(parents=True, exist_ok=True)
                    logging.info(f"Created directory for charts: {charts_dir}")
                except OSError as e:
                    logging.error(f"Failed to create directory for charts {charts_dir}: {e}")
                    # If directory creation failed, save in the current directory
                    charts_dir = Path(__file__).resolve().parent 
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_name = f"workload_chart_{timestamp}.png"
            full_save_path = charts_dir / file_name
        else:
            full_save_path = Path(save_path)
            # Ensure the directory for the custom path exists
            if not full_save_path.parent.exists():
                try:
                    full_save_path.parent.mkdir(parents=True, exist_ok=True)
                    logging.info(f"Created directory for chart: {full_save_path.parent}")
                except OSError as e:
                    logging.error(f"Failed to create directory {full_save_path.parent} for chart: {e}")
                    # Attempting to save in the script's current directory if the specified path is invalid
                    file_name = full_save_path.name
                    full_save_path = Path(__file__).resolve().parent / file_name

        try:
            fig.savefig(full_save_path, bbox_inches='tight')
            logging.info(f"Chart saved to: {full_save_path}")
            if show_plot:
                 plt.show() # Show plot if specified
            plt.close(fig) # Close the figure to free up memory
            return str(full_save_path)
        except Exception as e:
            logging.error(f"Failed to save chart to {full_save_path}: {e}", exc_info=True)
            plt.close(fig) # Close the figure also in case of error
            return None

    def show_summary(self, n=5, original=False):
        df_to_show = self.df_original if original else self.df
        if df_to_show is None or df_to_show.empty:
            logging.warning("No data to display for the summary.")
            return self
        
        title_suffix = " (original)" if original else ""
        logging.info(f"Workload summary{title_suffix} (first {n} records):\n{df_to_show.head(n).to_string()}")
        return self

if __name__ == "__main__":
    # Basic logging configuration
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    script_dir = Path(__file__).resolve().parent
    json_file_path = script_dir / "reports.json"

    logging.info(f"Looking for data file at: {json_file_path}")

    try:
        # Now rolling_window is passed during object creation
        # year is left for clarity, can be removed if the default value 2025 is used
        gen = WorkloadChartGenerator(json_file_path, year=2025, rolling_window=3)
        gen.load().aggregate().show_summary(10)
        # Call plot and get the path. show_plot=False to only save
        saved_chart_path = gen.plot(show_plot=False)
        
        if saved_chart_path:
            logging.info(f"Processing complete. Chart available at: {saved_chart_path}")
        else:
            logging.warning("Chart was not saved.")
            
    except FileNotFoundError:
        logging.error(f"ERROR: Data file {json_file_path} not found. Please ensure it exists.")
    except Exception as e:
        # logging.error with exc_info=True will automatically add traceback
        logging.error(f"ERROR: An unexpected error occurred: {e}", exc_info=True)
