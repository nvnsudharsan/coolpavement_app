import importlib.util
import os
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

# Set the page configuration with light theme
st.set_page_config(layout="wide", initial_sidebar_state="expanded")

# Custom CSS to change the sidebar color to UT Austin orange and ensure light theme
st.markdown(
    """
    <style>
    .css-1d391kg {  /* This is the class for the sidebar */
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
    /* Light theme settings */
    .main {
        background-color: #ffffff; /* Light theme background */
    }
    .stSidebar {
        background-color: #f8f9fa; /* Light theme sidebar background */
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
# The HOBO exports changed format over the project:
#   2024 files:  'Date-Time (CDT)'      + 'Temperature (°C) '
#   late 2024:   'Date-Time (CST/CDT)'  + 'Temperature (°C) '
#   2025 files:  'Date-Time (CST)' / 'Date-Time (CST/CDT)' / 'Date-Time (CDT)' + 'Temperature , °C'
# Column names are normalised here so every file can be combined.

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


# Function to find and concatenate Excel files (cached so it only runs when the files change)
@st.cache_data(show_spinner="Loading sensor data...")
def find_and_concat_excel_files(folder_path, signature):
    grouped_files = {}
    for file, _ in signature:
        grouped_files.setdefault(file[:8], []).append(file)

    stations, skipped = {}, []
    for key, file_list in grouped_files.items():
        dataframes = []
        for file in file_list:
            try:
                dataframes.append(read_logger_file(os.path.join(folder_path, file)))
            except Exception as e:
                skipped.append(f"{file}: {e}")
        if dataframes:
            concatenated_df = pd.concat(dataframes)
            # Consecutive exports overlap, so the same reading appears in several files
            concatenated_df = concatenated_df.groupby(level=0).mean()
            stations['s' + key] = concatenated_df
    return stations, skipped


# Use relative path to the folder containing Excel files
folder_path = 'measurements'
try:
    stations, skipped_files = find_and_concat_excel_files(folder_path, folder_signature(folder_path))
except FileNotFoundError:
    st.error(f"Directory not found: {folder_path}")
    st.stop()

if not stations:
    st.error(f"No Excel files found in directory: {folder_path}")
    st.stop()
if skipped_files:
    st.warning("Some files could not be read and were skipped:\n\n" + "\n\n".join(skipped_files))

# Calibration and location corrections
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
    's21479990': (0.9982, 0.0457),
    's21479991': (0.9908, 0.2413),
    's21479993': (0.9393, 1.7208),
    's21479994': (0.9996, 0.0111),
    's21479995': (0.9998, -0.046),
    's21479998': (0.9944, -0.1216),
    's21471965': (1.0, 0.0)
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

# Apply corrections to data
processed = {}
for var_name in calibration_corrections.keys():
    if var_name in stations:
        df = stations[var_name].copy()
        df['Temperature'] = df['Temperature (°C)'] + calibration_corrections[var_name]
        df['Temperature_c'] = location_corrections[var_name][0] * df['Temperature'] + location_corrections[var_name][1]
        df['Temperature'] = df['Temperature'] * 9 / 5 + 32
        df['Temperature_c'] = df['Temperature_c'] * 9 / 5 + 32
        df = df[df.index >= start_time]
        processed[var_name] = df[['Temperature', 'Temperature_c']].resample('15min').mean()

missing_groups = {loc for loc in locations.values()} - {locations[k] for k in processed}
if missing_groups:
    st.error(f"No data loaded for: {', '.join(sorted(missing_groups))}. "
             f"Stations loaded: {', '.join(sorted(processed)) or 'none'}.")
    st.stop()

# Calculate averages
locations_avg = {}
for location in set(locations.values()):
    temperature_dfs = [processed[var_name]['Temperature'] for var_name, loc in locations.items() if loc == location and var_name in processed]
    temperature_c_dfs = [processed[var_name]['Temperature_c'] for var_name, loc in locations.items() if loc == location and var_name in processed]
    if temperature_dfs:
        avg_temp = pd.concat(temperature_dfs, axis=1).mean(axis=1)
        locations_avg[f"{location}_temperature"] = pd.DataFrame(avg_temp, columns=['Temperature (°F)'])
    if temperature_c_dfs:
        avg_temp_c = pd.concat(temperature_c_dfs, axis=1).mean(axis=1)
        locations_avg[f"{location}_temperature_c"] = pd.DataFrame(avg_temp_c, columns=['Calibrated Temperature (°F)'])

# Calculate the difference between control and cool temperatures
locations_avg['temperature_difference'] = locations_avg['cool_temperature']['Temperature (°F)'] - locations_avg['control_temperature']['Temperature (°F)']
locations_avg['temperature_c_difference'] = locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'] - locations_avg['control_temperature_c']['Calibrated Temperature (°F)']


# Function to get sunrise and sunset times (local clock time).
# Successful lookups are cached; failures are not, so they are retried on the next rerun.
@st.cache_data(show_spinner=False)
def fetch_sun_rise_set_time(date):
    response = requests.get('https://api.sunrise-sunset.org/json', params={
        'lat': 30.382749,
        'lng': -97.649183,
        'formatted': 0,
        'date': date}, timeout=10)
    response.raise_for_status()
    data = response.json()
    sunrise_time = pd.to_datetime(data['results']['sunrise']).tz_convert('America/Chicago').tz_localize(None)
    sunset_time = pd.to_datetime(data['results']['sunset']).tz_convert('America/Chicago').tz_localize(None)
    return sunrise_time, sunset_time


def get_sun_rise_set_time(date):
    try:
        return fetch_sun_rise_set_time(date)
    except Exception:
        return None, None


# Streamlit App
st.title("Cool Seal Treatment Project at Austin")

# Sidebar for date range and color selection
with st.sidebar:
    st.header("Filter Options")

    # Date range selector
    min_date = locations_avg['control_temperature'].index.min()
    max_date = locations_avg['control_temperature'].index.max()
    default_start = min_date + pd.DateOffset(weeks=1.05)
    default_end = min(default_start + pd.DateOffset(weeks=2), max_date)

    date_range = st.slider(
        "Select date range:",
        min_value=min_date.to_pydatetime(),
        max_value=max_date.to_pydatetime(),
        value=(default_start.to_pydatetime(), default_end.to_pydatetime()),
        format="MM/DD/YYYY"
    )
    #st.write(f'Data available from {min_date.date()} to {max_date.date()}')

    start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])

    # Color selection
    default_colors = {
        'control': '#FF0000',
        'cool': '#636EF4',
        'difference': '#000000'
    }

    st.header("Color Options")
    control_color = st.color_picker("Reference", default_colors['control'])
    cool_color = st.color_picker("Treatment area", default_colors['cool'])
    difference_color = st.color_picker("Difference", default_colors['difference'])

# Filter data based on selected date range
for key in ['control_temperature', 'cool_temperature', 'control_temperature_c', 'cool_temperature_c', 'temperature_difference', 'temperature_c_difference']:
    locations_avg[key] = locations_avg[key][(locations_avg[key].index >= start_date) & (locations_avg[key].index <= end_date)]

if locations_avg['temperature_c_difference'].dropna().empty:
    st.info("No overlapping treatment and reference data in the selected date range. Try a different range.")
    st.stop()

# Plot calibrated control and cool pavement temperatures
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=locations_avg['control_temperature_c'].index, y=locations_avg['control_temperature_c']['Calibrated Temperature (°F)'], name='Reference (Normal Pavement)',
                         line=dict(color=control_color, width=3, dash='dash')))
fig2.add_trace(go.Scatter(x=locations_avg['cool_temperature_c'].index, y=locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'], name='Treatment Site',
                         line=dict(color=cool_color, width=3)))
fig2.add_trace(go.Scatter(x=locations_avg['temperature_c_difference'].index, y=locations_avg['temperature_c_difference'], name='Difference (Treatment Site - Reference)',
                         line=dict(color=difference_color, width=4, dash='dot'), yaxis="y2"))
# Add a horizontal line at zero for the difference
fig2.add_shape(
    type="line",
    x0=locations_avg['control_temperature_c'].index.min(),
    y0=0,
    x1=locations_avg['control_temperature_c'].index.max(),
    y1=0,
    line=dict(color="green", width=5, dash="dash"),
    yref="y2"  # Make sure the line is drawn on the second y-axis (difference axis)
)

fig2.update_layout(
    height=1000,  # Increase the height of the plot
    legend=dict(orientation="h", yanchor="bottom", y=-0.1, xanchor="center", x=0.5, font=dict(size=22)),
    xaxis=dict(tickfont=dict(size=22)),
    yaxis=dict(title=dict(text="Air Temperature (°F)", font=dict(size=30, color="black")), tickfont=dict(size=22)),
    yaxis2=dict(title=dict(text="Difference (°F)", font=dict(size=30, color="black")), overlaying="y", side="right", tickfont=dict(size=22),
    showgrid=False)
)

# Add sunrise and sunset times to the plots
daily_profile = locations_avg['control_temperature']
date_list = np.unique(daily_profile.index.strftime('%Y-%m-%d'))
sun_times = [get_sun_rise_set_time(date) for date in date_list]
for i, (sunrise_time, sunset_time) in enumerate(sun_times):
    if sunrise_time is None:
        continue
    fig2.add_vrect(x0=sunrise_time, x1=sunset_time, fillcolor="#EF810E", opacity=0.25, layer="below", line_width=0)
    if i == 0:
        fig2.add_vrect(x0=daily_profile.index[0], x1=sunrise_time, fillcolor="#053752", opacity=0.25, layer="below", line_width=0)
    if i != len(sun_times) - 1:
        next_sunrise_time = sun_times[i + 1][0]
        if next_sunrise_time is not None:
            fig2.add_vrect(x0=sunset_time, x1=next_sunrise_time, fillcolor="#053752", opacity=0.25, layer="below", line_width=0)
    else:
        fig2.add_vrect(x0=sunset_time, x1=daily_profile.index[-1], fillcolor="#053752", opacity=0.25, layer="below", line_width=0)

# Display plots in Streamlit app
st.subheader("Comparison of Air Temperatures recorded in Treatment area and Reference")
st.write('Toggle on or off the lines by clicking on the legends.')
st.write('Enlarge the figure by click on the view full screen icon on the top left corner of each figure.')
if any(sunrise_time is None for sunrise_time, _ in sun_times):
    st.caption("Day/night shading is missing for some days because the sunrise-sunset service could not be reached.")
st.plotly_chart(fig2)

# Function to safely display images
def display_image(image_path, caption=None):
    if os.path.exists(image_path):
        st.image(image_path, caption=caption)
    else:
        st.warning(f"Image not found: {image_path}")

# Display images side by side
st.subheader("Thermal Images of the Pavement")
st.markdown('<div class="image-container">', unsafe_allow_html=True)
display_image('flir/FLIR1350-Visual.jpeg')
display_image('flir/FLIR1350.jpg')
st.markdown('</div>', unsafe_allow_html=True)

# Embed Google Earth link
st.subheader("Sensor locations in Treatment and Reference area")
st.markdown('<div class="image-container">', unsafe_allow_html=True)
display_image('location.png')
st.markdown('</div>', unsafe_allow_html=True)
