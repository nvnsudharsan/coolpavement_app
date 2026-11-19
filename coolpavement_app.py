import importlib.util
import os
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Set Streamlit page configuration
st.set_page_config(layout="wide", initial_sidebar_state="expanded")

# Custom CSS for styling
st.markdown("""
    <style>
    .css-1d391kg {
        background-color: #BF5700;
    }
    .stSlider > div:nth-child(1) {
        color: black;
    }
    .image-container {
        display: flex;
        justify-content: center;
        align-items: center;
    }
    .image-container img {
        margin: 0 10px;
    }
    .main {
        background-color: #ffffff;
    }
    .stSidebar {
        background-color: #f8f9fa;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
# The HOBO exports changed format over the project:
#   2024 files:  'Date-Time (CDT)'      + 'Temperature (°C) '
#   late 2024:   'Date-Time (CST/CDT)'  + 'Temperature (°C) '
#   2025 files:  'Date-Time (CST)' / 'Date-Time (CST/CDT)' / 'Date-Time (CDT)' + 'Temperature , °C'
# Column names are normalised here so every file can be combined.

folder_path = 'measurements'
EXCEL_ENGINE = 'calamine' if importlib.util.find_spec('python_calamine') else 'openpyxl'

# Fixed-offset labels used in the time column header. 'CST/CDT' is already local clock time.
FIXED_OFFSET_TZ = {'CDT': 'Etc/GMT+5', 'CST': 'Etc/GMT+6'}


def clean_column_name(name):
    """'Temperature , °C' and 'Temperature (°C) ' both become 'Temperature (°C)'."""
    name = str(name).strip()
    match = re.match(r'^(.*?)\s*,\s*(.+)$', name)
    if match:
        name = f"{match.group(1)} ({match.group(2)})"
    return name


def to_local_time(times, label):
    """Convert logger timestamps to naive America/Chicago clock time."""
    times = pd.to_datetime(times)
    tz = FIXED_OFFSET_TZ.get(label)
    if tz is None:
        return times
    return times.dt.tz_localize(tz).dt.tz_convert('America/Chicago').dt.tz_localize(None)


def read_logger_file(path):
    df = pd.read_excel(path, engine=EXCEL_ENGINE)
    df.columns = [clean_column_name(c) for c in df.columns]
    time_col = next(c for c in df.columns if c.startswith('Date-Time'))
    label_match = re.search(r'\((.*)\)', time_col)
    label = label_match.group(1) if label_match else 'CST/CDT'
    index = pd.DatetimeIndex(to_local_time(df[time_col], label), name='Date-Time')
    temperature = pd.to_numeric(df['Temperature (°C)'], errors='coerce').to_numpy()
    return pd.DataFrame({'Temperature (°C)': temperature}, index=index).dropna()


def folder_signature(path):
    """File names and modification times, so the cache refreshes when files change."""
    return tuple(sorted((f, os.path.getmtime(os.path.join(path, f)))
                        for f in os.listdir(path) if f.lower().endswith(('.xlsx', '.xls'))))


@st.cache_data(show_spinner="Loading sensor data...")
def load_station_data(path, signature):
    grouped_files = {}
    for file, _ in signature:
        grouped_files.setdefault(file[:8], []).append(file)

    stations, skipped = {}, []
    for station_id, file_list in grouped_files.items():
        frames = []
        for file in file_list:
            try:
                frames.append(read_logger_file(os.path.join(path, file)))
            except Exception as e:
                skipped.append(f"{file}: {e}")
        if frames:
            df = pd.concat(frames)
            # Consecutive exports overlap, so the same reading appears in several files
            df = df.groupby(level=0).mean()
            stations[f's{station_id}'] = df
    return stations, skipped


data_store = {}
try:
    data_store, skipped_files = load_station_data(folder_path, folder_signature(folder_path))
    if skipped_files:
        st.warning("Some files could not be read and were skipped:\n\n" + "\n\n".join(skipped_files))
except Exception as e:
    st.error(f"Failed to load data: {e}")

# Define correction dictionaries
calibration_corrections = {
    's21471965': -0.014904143,
    's21479990': -0.093339073,
    's21479991': 0.000675938,
    's21479993': -0.035137113,
    's21479994': 0.0,
    's21479995': -0.027288099,
    's21479998': 0.262262291
}

location_corrections = {
    's21471965': (1.0, 0.0),
    's21479990': (0.9982, 0.0457),
    's21479991': (0.9908, 0.2413),
    's21479993': (0.9393, 1.7208),
    's21479994': (0.9996, 0.0111),
    's21479995': (0.9998, -0.046),
    's21479998': (0.9944, -0.1216)
}

locations = {
    's21471965': 'control',
    's21479990': 'cool',
    's21479991': 'control',
    's21479993': 'cool',
    's21479994': 'cool',
    's21479995': 'control',
    's21479998': 'cool'
}

start_time = pd.to_datetime('2024-06-25 17:00:00')

# Apply corrections and resampling
processed = {}
for var_name in calibration_corrections:
    if var_name in data_store:
        df = data_store[var_name].copy()
        df['Temperature'] = df['Temperature (°C)'] + calibration_corrections[var_name]
        df['Temperature_c'] = location_corrections[var_name][0] * df['Temperature'] + location_corrections[var_name][1]
        df['Temperature'] = df['Temperature'] * 9 / 5 + 32
        df['Temperature_c'] = df['Temperature_c'] * 9 / 5 + 32
        df = df[df.index >= start_time]
        processed[var_name] = df[['Temperature', 'Temperature_c']].resample('15min').mean()

# Compute average temperatures
locations_avg = {}
for location in set(locations.values()):
    temp_dfs = [processed[k]['Temperature'] for k, v in locations.items() if v == location and k in processed]
    temp_c_dfs = [processed[k]['Temperature_c'] for k, v in locations.items() if v == location and k in processed]
    if temp_dfs:
        locations_avg[f"{location}_temperature"] = pd.DataFrame(pd.concat(temp_dfs, axis=1).mean(axis=1), columns=['Temperature (°F)'])
    if temp_c_dfs:
        locations_avg[f"{location}_temperature_c"] = pd.DataFrame(pd.concat(temp_c_dfs, axis=1).mean(axis=1), columns=['Calibrated Temperature (°F)'])

if 'cool_temperature' in locations_avg and 'control_temperature' in locations_avg:
    locations_avg['temperature_difference'] = locations_avg['cool_temperature']['Temperature (°F)'] - locations_avg['control_temperature']['Temperature (°F)']

if 'cool_temperature_c' in locations_avg and 'control_temperature_c' in locations_avg:
    locations_avg['temperature_c_difference'] = locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'] - locations_avg['control_temperature_c']['Calibrated Temperature (°F)']

# Streamlit UI
st.title("Cool Seal Treatment Project at Austin")

start_date, end_date = None, None
with st.sidebar:
    st.header("Filter Options")
    if 'control_temperature' in locations_avg:
        min_date = locations_avg['control_temperature'].index.min()
        max_date = locations_avg['control_temperature'].index.max()
        default_start = min_date + pd.DateOffset(weeks=1.05)
        default_end = min(default_start + pd.DateOffset(weeks=2), max_date)
        date_range = st.slider("Select date range:", min_value=min_date.to_pydatetime(), max_value=max_date.to_pydatetime(),
                               value=(default_start.to_pydatetime(), default_end.to_pydatetime()),
                               format="MM/DD/YYYY")
        start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])

    st.header("Color Options")
    control_color = st.color_picker("Reference", '#FF0000')
    cool_color = st.color_picker("Treatment area", '#636EF4')
    difference_color = st.color_picker("Difference", '#000000')

if start_date is not None and end_date is not None:
    for k in locations_avg:
        locations_avg[k] = locations_avg[k][(locations_avg[k].index >= start_date) & (locations_avg[k].index <= end_date)]

# Plotting
required = ['control_temperature_c', 'cool_temperature_c', 'temperature_c_difference']
if not all(k in locations_avg for k in required):
    st.error("Could not build the temperature comparison: treatment or reference data is missing. "
             f"Stations loaded: {', '.join(sorted(processed)) or 'none'}.")
elif locations_avg['temperature_c_difference'].dropna().empty:
    st.info("No overlapping treatment and reference data in the selected date range.")
else:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=locations_avg['control_temperature_c'].index,
                             y=locations_avg['control_temperature_c']['Calibrated Temperature (°F)'],
                             name='Reference', line=dict(color=control_color, width=3, dash='dash')))
    fig.add_trace(go.Scatter(x=locations_avg['cool_temperature_c'].index,
                             y=locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'],
                             name='Treatment', line=dict(color=cool_color, width=3)))
    fig.add_trace(go.Scatter(x=locations_avg['temperature_c_difference'].index,
                             y=locations_avg['temperature_c_difference'],
                             name='Difference', line=dict(color=difference_color, width=4, dash='dot'), yaxis="y2"))
    fig.add_shape(type="line", x0=start_date, x1=end_date, y0=0, y1=0,
                  line=dict(color="green", width=5, dash="dash"), yref="y2")

    fig.update_layout(
        height=1000,
        legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5, font=dict(size=22)),
        xaxis=dict(tickfont=dict(size=22)),
        yaxis=dict(title=dict(text="Air Temperature (°F)", font=dict(size=30)), tickfont=dict(size=22)),
        yaxis2=dict(title=dict(text="Difference (°F)", font=dict(size=30)), overlaying="y", side="right",
                    showgrid=False, tickfont=dict(size=22))
    )

    st.subheader("Comparison of Air Temperatures")
    st.plotly_chart(fig)

# Image display helpers
def display_image(path, caption=None):
    if os.path.exists(path):
        st.image(path, caption=caption)
    else:
        st.warning(f"Image not found: {path}")

# Display images and location map
st.subheader("Thermal Images")
st.markdown('<div class="image-container">', unsafe_allow_html=True)
display_image('flir/FLIR1350-Visual.jpeg')
display_image('flir/FLIR1350.jpg')
st.markdown('</div>', unsafe_allow_html=True)

st.subheader("Sensor Locations")
st.markdown('<div class="image-container">', unsafe_allow_html=True)
display_image('location.png')
st.markdown('</div>', unsafe_allow_html=True)
