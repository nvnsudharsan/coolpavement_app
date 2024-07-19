import plotly.graph_objects as go
import pandas as pd
import os
import streamlit as st
import requests
import numpy as np

# Set the page configuration
st.set_page_config(layout="wide")

# Custom CSS to change the sidebar color to UT Austin orange
st.markdown(
    """
    <style>
    .css-1d391kg {  # This is the class for the sidebar
        background-color: #BF5700;
    }
    .stSlider > div:nth-child(1) {
        color: black;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Function to find and concatenate Excel files
def find_and_concat_excel_files(folder_path):
    try:
        files = [f for f in os.listdir(folder_path) if f.endswith('.xlsx') or f.endswith('.xls')]
        if not files:
            st.error(f"No Excel files found in directory: {folder_path}")
            return
    except FileNotFoundError as e:
        st.error(f"Directory not found: {folder_path}")
        return

    grouped_files = {}
    for file in files:
        key = file[:8]
        if key in grouped_files:
            grouped_files[key].append(file)
        else:
            grouped_files[key] = [file]

    for key, file_list in grouped_files.items():
        dataframes = [pd.read_excel(os.path.join(folder_path, file)) for file in file_list]
        if not all(df.columns.equals(dataframes[0].columns) for df in dataframes):
            continue
        concatenated_df = pd.concat(dataframes)
        concatenated_df['Date-Time (CDT)'] = pd.to_datetime(concatenated_df['Date-Time (CDT)'])
        concatenated_df.set_index('Date-Time (CDT)', inplace=True)
        concatenated_df = concatenated_df.groupby(concatenated_df.index).mean()
        globals()['s' + key] = concatenated_df

# Use relative path to the folder containing Excel files
folder_path = 'measurements'
find_and_concat_excel_files(folder_path)

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
for var_name in calibration_corrections.keys():
    if var_name in globals():
        df = globals()[var_name]
        df['Temperature'] = df['Temperature (°C) '] + calibration_corrections[var_name]
        df['Temperature_c'] = location_corrections[var_name][0] * df['Temperature'] + location_corrections[var_name][1]
        df['Temperature'] = df['Temperature'] * 9 / 5 + 32
        df['Temperature_c'] = df['Temperature_c'] * 9 / 5 + 32
        df['Location'] = locations[var_name]
        df = df[df.index >= start_time]
        
        # Ensure only numeric columns are used for the mean calculation
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        df = df[numeric_cols].resample('15T').mean()
        
        globals()[var_name] = df

# Calculate averages
locations_avg = {}
for location in set(locations.values()):
    temperature_dfs = [globals()[var_name]['Temperature'] for var_name, loc in locations.items() if loc == location]
    temperature_c_dfs = [globals()[var_name]['Temperature_c'] for var_name, loc in locations.items() if loc == location]
    if temperature_dfs:
        avg_temp = pd.concat(temperature_dfs, axis=1).mean(axis=1)
        locations_avg[f"{location}_temperature"] = pd.DataFrame(avg_temp, columns=['Temperature (°F)'])
    if temperature_c_dfs:
        avg_temp_c = pd.concat(temperature_c_dfs, axis=1).mean(axis=1)
        locations_avg[f"{location}_temperature_c"] = pd.DataFrame(avg_temp_c, columns=['Calibrated Temperature (°F)'])

# Calculate the difference between control and cool temperatures
locations_avg['temperature_difference'] = locations_avg['cool_temperature']['Temperature (°F)'] - locations_avg['control_temperature']['Temperature (°F)']
locations_avg['temperature_c_difference'] = locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'] - locations_avg['control_temperature_c']['Calibrated Temperature (°F)']

# Function to get sunrise and sunset times
def get_sun_rise_set_time(date):
    response = requests.get('https://api.sunrise-sunset.org/json', params={
        'lat': 30.382749,
        'lng': -97.649183,
        'formatted': 0,
        'date': date})
    data = response.json()
    sunrise_time = pd.to_datetime(data['results']['sunrise']).tz_convert('US/Central')
    sunset_time = pd.to_datetime(data['results']['sunset']).tz_convert('US/Central')
    return sunrise_time, sunset_time

# Streamlit App
st.title("Cool Seal Treatment Project at Austin")

# Sidebar for date range and color selection
with st.sidebar:
    st.header("Filter Options")
    
    # Date range selector
    min_date = locations_avg['control_temperature'].index.min()
    max_date = locations_avg['control_temperature'].index.max()
    default_start = min_date
    default_end = default_start + pd.DateOffset(weeks=2)

    date_range = st.slider(
        "Select date range:",
        min_value=min_date.to_pydatetime(),
        max_value=max_date.to_pydatetime(),
        value=(default_start.to_pydatetime(), default_end.to_pydatetime()),
        format="MM/DD/YYYY"
    )
    st.write(f'Data available from {min_date.date()} to {max_date.date()}')

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

# Plot calibrated control and cool pavement temperatures
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=locations_avg['control_temperature_c'].index, y=locations_avg['control_temperature_c']['Calibrated Temperature (°F)'], name='Reference (Normal Pavement)',
                         line=dict(color=control_color, width=3, dash='dash')))
fig2.add_trace(go.Scatter(x=locations_avg['cool_temperature_c'].index, y=locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'], name='Treatment Site',
                         line=dict(color=cool_color, width=3)))
fig2.add_trace(go.Scatter(x=locations_avg['control_temperature_c'].index, y=locations_avg['temperature_c_difference'], name='Difference (Treatment Site - Reference)',
                         line=dict(color=difference_color, width=4, dash='dot'), yaxis="y2"))
fig2.update_layout(
    legend=dict(orientation="h", yanchor="bottom", y=-0.7, xanchor="center", x=0.5, font=dict(size=22)),
    xaxis=dict(titlefont=dict(size=30), tickfont=dict(size=22)),
    yaxis=dict(title="Air Temperature (°F)", titlefont=dict(size=30, color="black"), tickfont=dict(size=22)),
    yaxis2=dict(title="Difference (°F)", titlefont=dict(size=30, color="black"), overlaying="y", side="right", tickfont=dict(size=22))
)

# Add sunrise and sunset times to the plots
daily_profile = locations_avg['control_temperature']
date_list = np.unique(daily_profile.index.strftime('%Y-%m-%d'))
for i, date in enumerate(date_list):
    sunrise_time, sunset_time = get_sun_rise_set_time(date)
    fig2.add_vrect(x0=sunrise_time, x1=sunset_time, fillcolor="#EF810E", opacity=0.25, layer="below", line_width=0)
    if i == 0:
        fig2.add_vrect(x0=daily_profile.index[0], x1=sunrise_time, fillcolor="#053752", opacity=0.25, layer="below", line_width=0)
    if i != len(date_list) - 1:
        next_sunrise_time, _ = get_sun_rise_set_time(date_list[i+1])
        fig2.add_vrect(x0=sunset_time, x1=next_sunrise_time, fillcolor="#053752", opacity=0.25, layer="below", line_width=0)
    else:
        fig2.add_vrect(x0=sunset_time, x1=daily_profile.index[-1], fillcolor="#053752", opacity=0.25, layer="below", line_width=0)

# Display plots in Streamlit app
st.subheader("Comparison of Air Temperatures recorded in Treatment area and Reference")
st.write('Toggle on or off the lines by clicking on the legends.')
st.write('Enlarge the figure by click on the view full screen icon on the top left corner of each figure.')
st.plotly_chart(fig2, use_container_width=True)

# Function to safely display images
def display_image(image_path, caption=None):
    if os.path.exists(image_path):
        st.image(image_path, caption=caption)
    else:
        st.warning(f"Image not found: {image_path}")

st.subheader("Thermal Images of the Pavement")
display_image('flir/FLIR1350-Visual.jpeg')
display_image('flir/FLIR1350.jpg')

# Embed Google Earth link
st.subheader("Sensor locations in Treatment and Reference area")
display_image('location.png')
