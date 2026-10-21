"""
EnvironmentalDemo - cloud metrics plugin (lab)

=============================================================================
WHAT TO SEND (fields + tags)
=============================================================================
Each write is one CSV row as Influx point via the metrics gateway.

  fields (numeric): Temperature, Humidity, Pressure, PM1, PM10, PM25,
                    Rain, UV_index, Wind_direction, Wind_speed, alt, lat, lon
  tags   (strings): host (= row name), source (= source_file)

=============================================================================
HOW TO SEND (MetricsWriter template)
=============================================================================
SDK on LR: /opt/lab/s4t_metrics.py

  from s4t_metrics import MetricsWriter
  metrics = MetricsWriter.from_params(params)   # reads metrics_* below
  metrics.write(
      fields={"Temperature": 21.5, "Humidity": 48.0, ...},
      tags={"host": "sensor-1", "source": "structured_time_series_v2.csv"},
  )

HTTP equivalent (what the SDK does):

  POST {metrics_url}
  Authorization: Bearer {metrics_token}
  Content-Type: application/json

  {
    "fields": {"Temperature": 21.5, "Humidity": 48.0},
    "tags":   {"host": "sensor-1", "source": "csv"},
    "time":   "2026-01-15T12:00:00"   // optional ISO timestamp
  }

=============================================================================
HOW TO GET metrics_url / metrics_token
=============================================================================
Preferred (lab): IoT -> Plugins -> Start EnvironmentalDemo with
  "Enable cloud metrics" (default ON). Horizon provisions a stream and
  injects into start parameters:

  {
    "metrics_url":   "http://metrics-gateway:8093/v1/metrics/write",
    "metrics_token": "<opaque token from metrics-gateway>",
    "metrics_stream": "environmental_data"
  }

Manual provision (same values):

  POST http://metrics-gateway:8093/v1/streams
  {"board_uuid":"...","board_name":"...","plugin_name":"EnvironmentalDemo",
   "measurement":"environmental_data",
   "field_schema":["Temperature","Humidity","PM10","PM25"]}

  Response includes metrics_url + metrics_token.

Without metrics_url + metrics_token this plugin refuses to run (no silent empty run).
View live data: IoT -> Metrics (Grafana + stream list). Source CSV: /opt/data or CSV_URL.
=============================================================================
"""
import sys
import time
import pandas as pd
from datetime import datetime
from oslo_log import log as logging
from iotronic_lightningrod.modules.plugins import Plugin
import os
import requests

if '/opt/lab' not in sys.path:
    sys.path.insert(0, '/opt/lab')
from s4t_metrics import MetricsWriter

LOG = logging.getLogger(__name__)

# Configuration
CSV_DIR = "/opt/data"
CSV_FILE = os.path.join(CSV_DIR, "structured_time_series_v2.csv")
STATE_FILE = os.path.join(CSV_DIR, "last_index.state")
CSV_URL = "https://drive.google.com/uc?id=1ryiOeb_c2xqAi0JWPfAJqbNLSTM51BP0"

# Logging fallback
def log_info(msg):
    try:
        LOG.info(msg)
    except Exception:
        print("[INFO]", msg)

def log_error(msg):
    try:
        LOG.error(msg)
    except Exception:
        print("[ERROR]", msg)

class Worker(Plugin.Plugin):
    def __init__(self, uuid, name, q_result=None, params=None):
        super(Worker, self).__init__(uuid, name, q_result, params)

        # Ensure the directory exists
        if not os.path.exists(CSV_DIR):
            os.makedirs(CSV_DIR)
            log_info(f"Created directory {CSV_DIR}")

        # Download the CSV if missing
        if not os.path.isfile(CSV_FILE):
            log_info("CSV file not found locally. Downloading...")
            try:
                self.download_csv()
                log_info(f"Downloaded CSV to {CSV_FILE}")
            except Exception as e:
                log_error(f"CSV download failed: {e}")
                raise

        # Load and validate CSV
        try:
            self.df = pd.read_csv(CSV_FILE)
            if self.df.shape[0] == 0 or self.df.shape[1] <= 1:
                raise ValueError("CSV file is empty or corrupt.")
            self.df['time'] = pd.to_datetime(self.df['time'])
            self.df = self.df.fillna(0)
            log_info(f"Loaded CSV with {len(self.df)} rows.")
        except Exception as e:
            log_error(f"Error reading CSV: {e}")
            raise

        self.metrics = MetricsWriter.from_params(params)

        # Index resume support
        self.last_index = self.load_last_index()

    def download_csv(self):
        """Download the CSV from a public Google Drive URL."""
        response = requests.get(CSV_URL)
        if response.status_code == 200:
            with open(CSV_FILE, 'wb') as f:
                f.write(response.content)
        else:
            raise Exception(f"Failed to download file. Status: {response.status_code}")

    def load_last_index(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    return int(f.read().strip())
            except Exception as e:
                log_error(f"Failed to read state file: {e}")
        return 0

    def save_last_index(self, index):
        try:
            with open(STATE_FILE, 'w') as f:
                f.write(str(index))
        except Exception as e:
            log_error(f"Failed to write state file: {e}")

    def generate_fields(self, row):
        def safe_float(value):
            try:
                return float(str(value).strip('"'))
            except:
                return 0.0

        return {
            "Gust": safe_float(row['Gust']),
            "Humidity": safe_float(row['Humidity']),
            "Light": safe_float(row['Light']),
            "PM10": safe_float(row['PM10']),
            "PM100": safe_float(row['PM100']),
            "PM25": safe_float(row['PM25']),
            "Part03": safe_float(row['Part03']),
            "Part05": safe_float(row['Part05']),
            "Part10": safe_float(row['Part10']),
            "Part100": safe_float(row['Part100']),
            "Part25": safe_float(row['Part25']),
            "Part50": safe_float(row['Part50']),
            "Precipitation": safe_float(row['Precipitation']),
            "Pressure": safe_float(row['Pressure']),
            "Temperature": safe_float(row['Temperature']),
            "UVI": safe_float(row['UVI']),
            "Wind_direction": safe_float(row['Wind_direction']),
            "Wind_speed": safe_float(row['Wind_speed']),
            "alt": safe_float(row['alt']),
            "lat": safe_float(row['lat']),
            "lon": safe_float(row['lon'])
        }

    def run(self):
        log_info(f"Plugin '{self.name}' started.")
        if not self.metrics.enabled:
            log_error(
                "Cloud metrics NOT configured (missing metrics_url/token). "
                "Refuse to run: Start again from Horizon with "
                "'Enable cloud metrics' (required for EnvironmentalDemo)."
            )
            return
        log_info("Cloud metrics enabled via metrics-gateway.")
        if self.last_index >= len(self.df):
            # Dataset already fully replayed (persisted index): restart so the demo stream stays live.
            log_info("Dataset exhausted on previous run: replaying from row 0.")
            self.last_index = 0
            self.save_last_index(0)
        log_info(f"Starting from row {self.last_index} of {len(self.df)}")

        while self._is_running:
            if self.last_index >= len(self.df):
                log_info("End of dataset reached: looping back to row 0.")
                self.last_index = 0
            current_row = self.df.iloc[self.last_index]
            fields = self.generate_fields(current_row)
            tags = {
                "host": current_row.get('name', 'unknown'),
                "source": current_row.get('source_file', 'unknown')
            }

            try:
                if self.metrics.write(fields=fields, tags=tags):
                    log_info(f"Row {self.last_index} sent.")
                else:
                    log_error(f"Failed to write row {self.last_index}.")
            except Exception as e:
                log_error(f"Exception during write: {e}")

            self.last_index += 1
            self.save_last_index(self.last_index)
            time.sleep(30)

        log_info("Dataset complete or plugin stopped.")
