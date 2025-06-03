import plotly.graph_objects as go
import pandas as pd
import os
import streamlit as st
import requests
import numpy as np

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

# Load and process Excel data
folder_path = 'measurements'
data_store = {}

try:
    files = [f for f in os.listdir(folder_path) if f.endswith(('.xlsx', '.xls'))]
    grouped_files = {}
    for file in files:
        station_id = file[:8]
        grouped_files.setdefault(station_id, []).append(file)

    for station_id, file_list in grouped_files.items():
        dfs = [pd.read_excel(os.path.join(folder_path, file)) for file in file_list]
        if all(df.columns.equals(dfs[0].columns) for df in dfs):
            df = pd.concat(dfs)
            df['Date-Time (CDT)'] = pd.to_datetime(df['Date-Time (CDT)'])
            df.set_index('Date-Time (CDT)', inplace=True)
            df = df.groupby(df.index).mean()
            data_store[f's{station_id}'] = df
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
for var_name in calibration_corrections:
    if var_name in data_store:
        df = data_store[var_name]
        if 'Temperature (°C) ' in df.columns:
            df['Temperature'] = df['Temperature (°C) '] + calibration_corrections[var_name]
            df['Temperature_c'] = location_corrections[var_name][0] * df['Temperature'] + location_corrections[var_name][1]
            df['Temperature'] = df['Temperature'] * 9 / 5 + 32
            df['Temperature_c'] = df['Temperature_c'] * 9 / 5 + 32
            df['Location'] = locations[var_name]
            df = df[df.index >= start_time]
            df = df.select_dtypes(include=[np.number]).resample('15min').mean()
            data_store[var_name] = df

# Compute average temperatures
locations_avg = {}
for location in set(locations.values()):
    temp_dfs = [data_store[k]['Temperature'] for k, v in locations.items() if v == location and k in data_store and 'Temperature' in data_store[k]]
    temp_c_dfs = [data_store[k]['Temperature_c'] for k, v in locations.items() if v == location and k in data_store and 'Temperature_c' in data_store[k]]
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

with st.sidebar:
    st.header("Filter Options")
    if 'control_temperature' in locations_avg:
        min_date, max_date = locations_avg['control_temperature'].index.min(), locations_avg['control_temperature'].index.max()
        date_range = st.slider("Select date range:", min_value=min_date.to_pydatetime(), max_value=max_date.to_pydatetime(),
                               value=(min_date + pd.DateOffset(weeks=1.05)).to_pydatetime(),
                               format="MM/DD/YYYY")
        start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
    else:
        start_date, end_date = None, None

    st.header("Color Options")
    control_color = st.color_picker("Reference", '#FF0000')
    cool_color = st.color_picker("Treatment area", '#636EF4')
    difference_color = st.color_picker("Difference", '#000000')

if start_date and end_date:
    for k in locations_avg:
        locations_avg[k] = locations_avg[k][(locations_avg[k].index >= start_date) & (locations_avg[k].index <= end_date)]

# Plotting
if 'control_temperature_c' in locations_avg and 'cool_temperature_c' in locations_avg and 'temperature_c_difference' in locations_avg:
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
        xaxis=dict(titlefont=dict(size=30), tickfont=dict(size=22)),
        yaxis=dict(title="Air Temperature (°F)", titlefont=dict(size=30), tickfont=dict(size=22)),
        yaxis2=dict(title="Difference (°F)", overlaying="y", side="right", showgrid=False, titlefont=dict(size=30), tickfont=dict(size=22))
    )

    st.subheader("Comparison of Air Temperatures")
    st.plotly_chart(fig, use_container_width=True)

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
