


import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import pytz
import datetime
import requests
from plotly.subplots import make_subplots
import numpy as np
import warnings
warnings.filterwarnings("ignore")
import os
import streamlit as st

def find_and_concat_excel_files(folder_path):
    # Step 1: Search for Excel files in the folder
    files = [f for f in os.listdir(folder_path) if f.endswith('.xlsx') or f.endswith('.xls')]
    print(f"Found files: {files}") 
    # Step 2: Group files by the first 8 letters of their names
    grouped_files = {}
    for file in files:
        key = file[:8]
        if key in grouped_files:
            grouped_files[key].append(file)
        else:
            grouped_files[key] = [file]
    print(f"Grouped files: {grouped_files}")
    # Step 3: Read and concatenate files
    for key, file_list in grouped_files.items():
        dataframes = []
        for file in file_list:
            df = pd.read_excel(os.path.join(folder_path, file))
            print(f"Reading file: {file}, shape: {df.shape}")
            dataframes.append(df)
        # Check if dataframes have the same columns
        columns = [df.columns for df in dataframes]
        if not all(columns[0].equals(col) for col in columns):
            print(f"Columns do not match for key: {key}")
            for i, df in enumerate(dataframes):
                print(f"File {file_list[i]} columns: {df.columns}")
            continue
        # Concatenate dataframes, handle duplicate indices by taking the average
        if dataframes:
            concatenated_df = pd.concat(dataframes)
            concatenated_df['Date-Time (CDT)'] = pd.to_datetime(concatenated_df['Date-Time (CDT)'])
            concatenated_df.set_index('Date-Time (CDT)', inplace=True)
            concatenated_df = concatenated_df.groupby(concatenated_df.index).mean()
            # Use the first 8 letters with an 's' in front as the variable name
            var_name = 's' + key
            globals()[var_name] = concatenated_df
            print(f"Variable '{var_name}' created and DataFrame stored in it, shape: {concatenated_df.shape}")
            print(globals()[var_name].head())
        else:
            print(f"No dataframes to concatenate for key: {key}")

folder_path = '/Users/geo-ns36752/Documents/GitHub/coolpavement_app/measurements'
find_and_concat_excel_files(folder_path)

# Calibration correction values
calibration_corrections = {
    's21471965': -0.014904143,
    's21479990': -0.093339073,
    's21479991': 0.000675938,
    's21479993': -0.035137113,
    's21479994': 0.0,
    's21479995': -0.027288099,
    's21479998': 0.262262291
}

# Location correction values
location_corrections = {
    's21479990': (0.9982, 0.0457),
    's21479991': (0.9908, 0.2413),
    's21479993': (0.9393, 1.7208),
    's21479994': (0.9996, 0.0111),
    's21479995': (0.9998, -0.046),
    's21479998': (0.9944, -0.1216),
    's21471965': (1.0, 0.0)  # no change
}

# Location of sensors
locations = {
    's21471965': 'control',
    's21479990': 'cool',
    's21479991': 'control',
    's21479993': 'cool',
    's21479994': 'cool',
    's21479995': 'control',
    's21479998': 'cool'
}


# Define the start time
start_time = pd.to_datetime('2024-06-25 17:00:00')

# Generalize the calibration correction, location correction, and time slicing
for var_name in calibration_corrections.keys():
    if var_name in globals():
        df = globals()[var_name]
        # Calibration correction
        df['Temperature'] = df['Temperature (°C) '] + calibration_corrections[var_name]
        # Location correction
        df['Temperature_c'] = location_corrections[var_name][0] * df['Temperature'] + location_corrections[var_name][1]
        # Convert temperatures from Celsius to Fahrenheit
        df['Temperature'] = df['Temperature'] * 9 / 5 + 32
        df['Temperature_c'] = df['Temperature_c'] * 9 / 5 + 32
        # Location of sensors
        df['Location'] = locations[var_name]
        # Slice DataFrames to start from the specified time
        df = df[df.index >= start_time]        
        # Resample to 15-minute intervals, taking the mean of each interval
        df = df.resample('15T').mean()       
        # Store the resampled DataFrame back to the variable
        globals()[var_name] = df
        # Print to verify
        print(f"{var_name} head after processing and resampling:")
        print(globals()[var_name].head())
    else:
        print(f"Variable {var_name} not found in globals.")


# Calculate the average temperature and temperature_c for each location
locations_avg = {}
for location in set(locations.values()):
    temperature_dfs = []
    temperature_c_dfs = []
    for var_name, loc in locations.items():
        if loc == location:
            temperature_dfs.append(globals()[var_name]['Temperature'])
            temperature_c_dfs.append(globals()[var_name]['Temperature_c'])
    if temperature_dfs:
        avg_temp = pd.concat(temperature_dfs, axis=1).mean(axis=1)
        locations_avg[f"{location}_temperature"] = pd.DataFrame(avg_temp, columns=['Temperature (°F)'])
    if temperature_c_dfs:
        avg_temp_c = pd.concat(temperature_c_dfs, axis=1).mean(axis=1)
        locations_avg[f"{location}_temperature_c"] = pd.DataFrame(avg_temp_c, columns=['Calibrated Temperature (°F)'])

# Print to verify
for location, df in locations_df.items():
    print(f"{location} head after averaging:")
    print(df.head())



# Plotting Control and Cool Pavement Temperatures
fig1 = go.Figure()
fig1 = fig1.add_trace(go.Scatter(x=locations_avg['control_temperature'].index, y=locations_avg['control_temperature']['Temperature (°F)'], name='Control',
                         line=dict(color='#FF0000', width=6, dash='dash')))
fig1 = fig1.add_trace(go.Scatter(x=locations_avg['cool_temperature'].index, y=locations_avg['cool_temperature']['Temperature (°F)'], name='Cool Pavement',
                         line=dict(color='#636EF4', width=6)))
fig1.update_traces(connectgaps=True)
fig1.update_layout(xaxis_title='Time',
                   yaxis_title='Air Temperature (°F)')
fig1.update_layout(
    font=dict(
        size=12,
    )
)

# Plotting Calibrated Control Temperature
fig2 = go.Figure()
fig2 = fig2.add_trace(go.Scatter(x=locations_avg['control_temperature_c'].index, y=locations_avg['control_temperature_c']['Calibrated Temperature (°F)'], name='Control',
                         line=dict(color='#FF0000', width=6, dash='dash')))
fig2 = fig2.add_trace(go.Scatter(x=locations_avg['cool_temperature_c'].index, y=locations_avg['cool_temperature_c']['Calibrated Temperature (°F)'], name='Cool Pavement',
                         line=dict(color='#636EF4', width=6)))
fig2.update_traces(connectgaps=True)
fig2.update_layout(xaxis_title='Time',
                   yaxis_title='Air Temperature (°F)')
fig2.update_layout(
    font=dict(
        size=12,
    )
)

# Get the sunrise and sunset times for Central Time
def get_sun_rise_set_time(date):
    response = requests.get('https://api.sunrise-sunset.org/json', params={
        'lat': 30.382749,
        'lng': -97.649183,
        'formatted': 0,
        'date': date})
    data = response.json()
    sunrise_time_str = data['results']['sunrise']
    sunset_time_str = data['results']['sunset']
    sunrise_time = pd.to_datetime(sunrise_time_str).tz_convert('US/Central')
    sunset_time = pd.to_datetime(sunset_time_str).tz_convert('US/Central')
    return sunrise_time, sunset_time

# Ensure daily_profile has the same structure as locations_avg
daily_profile = locations_avg['control_temperature']

date_list = np.unique(daily_profile.index.strftime('%Y-%m-%d'))
for i, date in enumerate(date_list):
    sunrise_time, sunset_time = get_sun_rise_set_time(date)
    fig1.add_vrect(
        x0=sunrise_time, x1=sunset_time,
        fillcolor="#EF810E", opacity=0.25,
        layer="below", line_width=0,
    )
    fig2.add_vrect(
        x0=sunrise_time, x1=sunset_time,
        fillcolor="#EF810E", opacity=0.25,
        layer="below", line_width=0,
    )
    if i == 0:
        fig1.add_vrect(
            x0=daily_profile.index[0], x1=sunrise_time,
            fillcolor="#053752", opacity=0.25,
            layer="below", line_width=0,
        )
        fig2.add_vrect(
            x0=daily_profile.index[0], x1=sunrise_time,
            fillcolor="#053752", opacity=0.25,
            layer="below", line_width=0,
        )
    if i != len(date_list) - 1:
        next_sunrise_time, _ = get_sun_rise_set_time(date_list[i+1])
        fig1.add_vrect(
            x0=sunset_time, x1=next_sunrise_time,
            fillcolor="#053752", opacity=0.25,
            layer="below", line_width=0,
        )
        fig2.add_vrect(
            x0=sunset_time, x1=next_sunrise_time,
            fillcolor="#053752", opacity=0.25,
            layer="below", line_width=0,
        )
    else:
        fig1.add_vrect(
            x0=sunset_time, x1=daily_profile.index[-1],
            fillcolor="#053752", opacity=0.25,
            layer="below", line_width=0,
        )
        fig2.add_vrect(
            x0=sunset_time, x1=daily_profile.index[-1],
            fillcolor="#053752", opacity=0.25,
            layer="below", line_width=0,
        )

fig1.update_layout(xaxis=dict(showgrid=False),
              yaxis=dict(showgrid=False), plot_bgcolor='rgba(256, 256, 256, 50)')

fig1.update_xaxes(
    mirror=True,
    ticks='outside',
    showline=True,
    linecolor='black',
    linewidth=6
)
fig1.update_yaxes(
    mirror=True,
    ticks='outside',
    showline=True,
    linecolor='black',
    linewidth=6
)
fig1.update_traces(opacity=1)
fig1.update_layout(
    font=dict(
        size=30,
    ), boxgap=0,
    autosize=False,
    width=3000,
    height=1000, boxgroupgap=1.0
)
#fig1.show()

fig2.update_layout(xaxis=dict(showgrid=False),
              yaxis=dict(showgrid=False), plot_bgcolor='rgba(256, 256, 256, 50)')

fig2.update_xaxes(
    mirror=True,
    ticks='outside',
    showline=True,
    linecolor='black',
    linewidth=6
)
fig2.update_yaxes(
    mirror=True,
    ticks='outside',
    showline=True,
    linecolor='black',
    linewidth=6
)
fig2.update_traces(opacity=1)
fig2.update_layout(
    font=dict(
        size=30,
    ), boxgap=0,
    autosize=False,
    width=3000,
    height=1000, boxgroupgap=1.0
)
#fig2.show()

# Streamlit App
st.title("Temperature Analysis of Control and Cool Pavement")

st.subheader("Control and Cool Pavement Temperatures")
st.plotly_chart(fig1, use_container_width=True)

st.subheader("Calibrated Control and Cool Pavement Temperatures")
st.plotly_chart(fig2, use_container_width=True)



