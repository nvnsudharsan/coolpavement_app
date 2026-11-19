import importlib.util
import io
import os
import re
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Cool Seal Treatment Project at Austin", layout="wide",
                   initial_sidebar_state="auto")

# ---------------------------------------------------------------------------
# Look and feel
# ---------------------------------------------------------------------------
# Treated streets are the subject (blue); reference streets are the neutral baseline (gray).
# The difference panel uses a diverging pair: blue where the treated streets run cooler,
# red where they run warmer.
TREATMENT_COLOR = "#2a78d6"
REFERENCE_COLOR = "#7d838c"
DIFFERENCE_COLOR = "#3a3f46"
COOLER = "#2a78d6"
WARMER = "#e34948"
COOLER_FILL = "rgba(42, 120, 214, 0.30)"
WARMER_FILL = "rgba(227, 73, 72, 0.30)"


def theme_is_dark():
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


DARK = theme_is_dark()
INK = "#e8eaed" if DARK else "#1d2126"
MUTED = "#a3a9b1" if DARK else "#5b636e"
GRID = "#30353b" if DARK else "#e6e9ec"
AXIS = "#4a5058" if DARK else "#c5cad0"
NIGHT = "rgba(150, 170, 200, 0.10)" if DARK else "rgba(20, 40, 70, 0.06)"
FONT = "Barlow, 'Segoe UI', sans-serif"

st.markdown("""
<style>
div.cs-lede {font-size: 1.1rem; line-height: 1.5; opacity: 0.8; max-width: 70ch; margin: -0.4rem 0 1.8rem;}
div.cs-summary {font-family: 'Barlow Semi Condensed', 'Barlow', sans-serif; font-size: 1.8rem; font-weight: 500;
             line-height: 1.25; max-width: 42ch; margin: 0 0 1.2rem;}
.cs-stats {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
           border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 0.4rem; margin: 0 0 0.6rem;}
.cs-stat {padding: 0.8rem 1.1rem 0.95rem; border-left: 1px solid rgba(128, 128, 128, 0.3); min-width: 0;}
.cs-stat:first-child {border-left: none;}
.cs-stat-label {font-size: 0.95rem; font-weight: 500; opacity: 0.75;}
.cs-stat-value {font-family: 'Barlow Semi Condensed', 'Barlow', sans-serif; font-size: 2.1rem; font-weight: 600;
                line-height: 1.15; margin: 0.2rem 0 0.15rem;}
.cs-stat-note {font-size: 0.9rem; opacity: 0.75;}
.cs-swatch {display: inline-block; width: 0.65rem; height: 0.65rem; border-radius: 2px; margin-right: 0.35rem;}
.cs-panel-title {font-weight: 600; font-size: 1.05rem; margin: 0.4rem 0 -0.2rem;}
@media (max-width: 760px) {
  div.cs-summary {font-size: 1.4rem;}
  .cs-stats {grid-template-columns: repeat(2, minmax(0, 1fr));}
  .cs-stat:nth-child(3) {border-left: none;}
  .cs-stat:nth-child(n+3) {border-top: 1px solid rgba(128, 128, 128, 0.3);}
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

SITE_LAT, SITE_LON = 30.382749, -97.649183


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


def solar_elevation(index):
    """Solar elevation in degrees at the site for naive America/Chicago timestamps (NOAA approximation)."""
    utc = (pd.DatetimeIndex(index)
           .tz_localize('America/Chicago', ambiguous='NaT', nonexistent='shift_forward')
           .tz_convert('UTC'))
    hours = utc.hour + utc.minute / 60 + utc.second / 3600
    g = 2 * np.pi / 365 * (utc.dayofyear - 1 + (hours - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    hour_angle = np.radians((hours * 60 + eqtime + 4 * SITE_LON) / 4 - 180)
    lat = np.radians(SITE_LAT)
    cos_zenith = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(hour_angle)
    return 90 - np.degrees(np.arccos(np.clip(cos_zenith, -1, 1)))


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


@st.cache_data(show_spinner=False)
def build_series(path, signature):
    """Calibrated 15-minute group averages: Reference, Treatment, Difference (°F), logger counts, daylight flag."""
    stations, skipped = load_station_data(path, signature)
    groups = {'control': [], 'cool': []}
    for var_name in calibration_corrections:
        if var_name not in stations:
            continue
        df = stations[var_name]
        temp = df['Temperature (°C)'] + calibration_corrections[var_name]
        temp_c = location_corrections[var_name][0] * temp + location_corrections[var_name][1]
        temp_f = temp_c * 9 / 5 + 32
        temp_f = temp_f[temp_f.index >= start_time].resample('15min').mean().rename(var_name)
        groups[locations[var_name]].append(temp_f)

    if not groups['control'] or not groups['cool']:
        return None, skipped, sorted(stations)

    reference = pd.concat(groups['control'], axis=1)
    treatment = pd.concat(groups['cool'], axis=1)
    combined = pd.DataFrame({
        'Reference': reference.mean(axis=1),
        'Treatment': treatment.mean(axis=1),
        'Reference loggers': reference.notna().sum(axis=1),
        'Treatment loggers': treatment.notna().sum(axis=1),
    })
    combined['Difference'] = combined['Treatment'] - combined['Reference']
    combined['Daylight'] = np.asarray(solar_elevation(combined.index)) > -0.833
    return combined, skipped, sorted(stations)


@st.cache_data(show_spinner=False)
def load_web_image(path, max_size, modified):
    """Downsized JPEG of a large image so the page loads quickly."""
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert('RGB')
        im.thumbnail((max_size, max_size))
        buffer = io.BytesIO()
        im.save(buffer, format='JPEG', quality=85, optimize=True)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def fmt_date(t, with_year=True):
    return f"{t:%b} {t.day}, {t.year}" if with_year else f"{t:%b} {t.day}"


def fmt_range(start, end):
    if start.year == end.year:
        return f"{fmt_date(start, False)} to {fmt_date(end)}"
    return f"{fmt_date(start)} to {fmt_date(end)}"


def fmt_hour(t):
    hour = t.hour % 12 or 12
    return f"{hour} {'am' if t.hour < 12 else 'pm'}"


def fmt_hour_span(t):
    """'4 to 5 pm' for the hour starting at t."""
    start, end = fmt_hour(t), fmt_hour(t + pd.Timedelta(hours=1))
    if start.split()[1] == end.split()[1]:
        return f"{start.split()[0]} to {end}"
    return f"{start} to {end}"


def fmt_signed(v):
    if pd.isna(v):
        return "n/a"
    text = f"{abs(v):.1f}"
    if text == "0.0":
        return "0.0 °F"
    return f"{'−' if v < 0 else '+'}{text} °F"


def relation(v, against=None):
    """'0.4 °F cooler than <against>' / 'about the same as <against>'."""
    if pd.isna(v):
        return "no data"
    if abs(v) < 0.05:
        return f"about the same as {against}" if against else "about the same"
    word = "cooler" if v < 0 else "warmer"
    return f"{abs(v):.1f} °F {word} than {against}" if against else f"{abs(v):.1f} °F {word}"


def direction_note(v):
    if pd.isna(v) or abs(v) < 0.05:
        return "No clear difference"
    color, word = (COOLER, "Treated streets cooler") if v < 0 else (WARMER, "Treated streets warmer")
    return f'<span class="cs-swatch" style="background:{color}"></span>{word}'


def style_axes(fig):
    fig.update_layout(
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(family=FONT, size=14, color=INK),
        hoverlabel=dict(font_family=FONT, font_size=13),
        margin=dict(l=8, r=8, t=36, b=8),
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, ticks='outside', tickcolor=AXIS,
                     tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS, tickfont=dict(color=MUTED),
                     title_font=dict(size=13, color=MUTED))
    return fig


def symmetric_range(values, pad=1.12, floor=0.5):
    span = np.nanmax(np.abs(values)) if np.isfinite(values).any() else floor
    span = max(span, floor) * pad
    return [-span, span]


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
combined, skipped_files, stations_found = None, [], []
try:
    combined, skipped_files, stations_found = build_series(folder_path, folder_signature(folder_path))
except Exception as e:
    st.error(f"Could not load the measurements folder: {e}")

st.title("Cool Seal Treatment Project at Austin")
st.markdown(
    '<div class="cs-lede">Air temperature recorded every 15 minutes by four loggers on residential streets '
    'treated with a reflective cool seal, and by three loggers on untreated reference streets in the '
    'neighborhood to the south.</div>',
    unsafe_allow_html=True)

if skipped_files:
    st.warning("Some files could not be read and were skipped:\n\n" + "\n\n".join(skipped_files))

if combined is None:
    st.error("Treatment or reference data is missing, so the comparison can't be drawn. "
             f"Loggers loaded: {', '.join(stations_found) or 'none'}.")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
first_day = combined.index.min().normalize()
last_day = combined.index.max().normalize() + pd.Timedelta(days=1)
default_start = first_day + pd.Timedelta(days=8)
default_end = min(default_start + pd.Timedelta(days=14), last_day)

with st.sidebar:
    st.subheader("Dates shown")
    date_range = st.slider("Dates shown", min_value=first_day.to_pydatetime(), max_value=last_day.to_pydatetime(),
                           value=(default_start.to_pydatetime(), default_end.to_pydatetime()),
                           step=timedelta(days=1), format="MMM D, YYYY", label_visibility="collapsed")
    st.caption(f"Data available from {fmt_date(combined.index.min())} to {fmt_date(combined.index.max())}.")

    with st.expander("Line colors"):
        reference_color = st.color_picker("Reference streets", REFERENCE_COLOR)
        treatment_color = st.color_picker("Treated streets", TREATMENT_COLOR)
        difference_color = st.color_picker("Difference", DIFFERENCE_COLOR)

    st.subheader("About the data")
    st.caption("Each logger's readings are adjusted with its calibration and location corrections, "
               "then averaged within the treated and reference groups at 15-minute steps. "
               "Daylight means the sun is above the horizon at the site. Times are local (Austin).")

start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
window = combined[(combined.index >= start_date) & (combined.index < end_date)]
diff = window['Difference'].dropna()

if diff.empty:
    st.info("There is no overlapping treated and reference data for these dates. "
            "Move the date slider to a range with data.")
else:
    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    mean_all = diff.mean()
    mean_day = window.loc[window['Daylight'], 'Difference'].mean()
    mean_night = window.loc[~window['Daylight'], 'Difference'].mean()
    hourly = diff.resample('1h').mean().dropna()
    cooler_share = (hourly < 0).mean() if not hourly.empty else np.nan
    shown_start, shown_end = diff.index.min(), diff.index.max()

    st.markdown(
        f'<div class="cs-summary">From {fmt_range(shown_start, shown_end)}, air over the treated streets averaged '
        f'{relation(mean_all, "the reference streets")}, and {relation(mean_day)} in daylight.</div>',
        unsafe_allow_html=True)

    if not hourly.empty and hourly.min() < 0:
        when = hourly.idxmin()
        multi_year = shown_start.year != shown_end.year
        peak_value = fmt_signed(hourly.min())
        peak_note = f"{fmt_date(when, multi_year)}, {fmt_hour_span(when)}"
    else:
        peak_value, peak_note = "None", "Treated streets were never cooler"

    stats = [
        ("All hours", fmt_signed(mean_all),
         f"Cooler in {cooler_share:.0%} of hours" if pd.notna(cooler_share) else ""),
        ("Daylight", fmt_signed(mean_day), direction_note(mean_day)),
        ("Night", fmt_signed(mean_night), direction_note(mean_night)),
        ("Largest hourly cooling", peak_value, peak_note),
    ]
    st.markdown(
        '<div class="cs-stats">' + "".join(
            f'<div class="cs-stat"><div class="cs-stat-label">{label}</div>'
            f'<div class="cs-stat-value">{value}</div><div class="cs-stat-note">{note}</div></div>'
            for label, value, note in stats) + '</div>',
        unsafe_allow_html=True)

    n_treatment = int(window['Treatment loggers'].max())
    n_reference = int(window['Reference loggers'].max())
    st.caption(f"Treated minus reference air temperature. Based on {n_treatment} treated-street and "
               f"{n_reference} reference-street loggers for these dates.")

    # -----------------------------------------------------------------------
    # Time series: temperatures above, difference below (shared time axis)
    # -----------------------------------------------------------------------
    st.subheader("Air temperature over time")
    span_days = (shown_end - shown_start) / pd.Timedelta(days=1)
    plot_data = window[['Reference', 'Treatment', 'Difference']]
    if span_days > 45:
        plot_data = plot_data.resample('1h').mean()
    shade_nights = span_days <= 45

    # Both panels share one time axis so a single tooltip shows all three values
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=plot_data.index, y=plot_data['Reference'], name='Reference streets',
                             line=dict(color=reference_color, width=1.6), yaxis='y',
                             hovertemplate='%{y:.1f} °F'))
    fig.add_trace(go.Scatter(x=plot_data.index, y=plot_data['Treatment'], name='Treated streets',
                             line=dict(color=treatment_color, width=1.8), yaxis='y',
                             hovertemplate='%{y:.1f} °F'))
    d = plot_data['Difference']
    fig.add_trace(go.Scatter(x=d.index, y=d.clip(upper=0), fill='tozeroy', fillcolor=COOLER_FILL, yaxis='y2',
                             line=dict(width=0), hoverinfo='skip', showlegend=False))
    fig.add_trace(go.Scatter(x=d.index, y=d.clip(lower=0), fill='tozeroy', fillcolor=WARMER_FILL, yaxis='y2',
                             line=dict(width=0), hoverinfo='skip', showlegend=False))
    fig.add_trace(go.Scatter(x=d.index, y=d, name='Treated minus reference', showlegend=False, yaxis='y2',
                             line=dict(color=difference_color, width=1.1),
                             hovertemplate='%{y:+.2f} °F'))

    if shade_nights:
        daylight = window['Daylight']
        night = ~daylight
        run_id = (night != night.shift()).cumsum()
        for _, run in night[night].groupby(run_id[night]):
            fig.add_shape(type='rect', xref='x', yref='paper', y0=0, y1=1, x0=run.index[0],
                          x1=run.index[-1] + pd.Timedelta(minutes=15), fillcolor=NIGHT, line_width=0,
                          layer='below')

    style_axes(fig)
    fig.update_layout(
        height=640, hovermode='x unified', hoversubplots='axis',
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0, font=dict(size=14)),
        xaxis=dict(anchor='y2', hoverformat='%b %d, %Y %I:%M %p'),
        yaxis=dict(domain=[0.42, 1.0], title_text='Air temperature (°F)'),
        yaxis2=dict(domain=[0.0, 0.34], title_text='Treated minus<br>reference (°F)', zeroline=True,
                    zerolinecolor=AXIS, zerolinewidth=1, range=symmetric_range(d.to_numpy())),
    )
    for text, y, anchor in [("Treated warmer", 0.98, 'top'), ("Treated cooler", 0.02, 'bottom')]:
        fig.add_annotation(text=text, xref='x domain', yref='y2 domain', x=0.005, y=y, xanchor='left',
                           yanchor=anchor, showarrow=False, font=dict(size=12, color=MUTED))

    st.plotly_chart(fig, config={'displaylogo': False})
    note = "Shaded bands are night. " if shade_nights else "Hourly means are shown for ranges longer than 45 days. "
    st.caption(note + "Hover for values, drag to zoom, double-click to reset.")

    export = window[['Reference', 'Treatment', 'Difference']].rename(columns={
        'Reference': 'Reference streets (°F)', 'Treatment': 'Treated streets (°F)',
        'Difference': 'Treated minus reference (°F)'}).round(3)
    st.download_button("Download these dates as CSV", data=export.to_csv().encode('utf-8'),
                       file_name=f"coolpavement_{start_date:%Y%m%d}_{end_date:%Y%m%d}.csv", mime='text/csv')

    # -----------------------------------------------------------------------
    # Average day
    # -----------------------------------------------------------------------
    st.subheader("Average day")
    st.caption("Mean for each hour of the day across the dates shown. Shaded hours are mostly dark.")
    by_hour = window.groupby(window.index.hour)[['Reference', 'Treatment', 'Difference']].mean()
    daylight_share = window.groupby(window.index.hour)['Daylight'].mean()
    hour_ticks = dict(tickmode='array', tickvals=[0, 3, 6, 9, 12, 15, 18, 21],
                      ticktext=['12 am', '3 am', '6 am', '9 am', '12 pm', '3 pm', '6 pm', '9 pm'],
                      range=[-0.5, 23.5])

    def shade_dark_hours(figure):
        dark_hours = [h for h in daylight_share.index if daylight_share[h] < 0.5]
        for h in dark_hours:
            figure.add_vrect(x0=h - 0.5, x1=h + 0.5, fillcolor=NIGHT, line_width=0, layer='below')

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown('<p class="cs-panel-title">Air temperature by hour</p>', unsafe_allow_html=True)
        fig_hour = go.Figure()
        for col, name, color in [('Reference', 'Reference streets', reference_color),
                                 ('Treatment', 'Treated streets', treatment_color)]:
            fig_hour.add_trace(go.Scatter(x=by_hour.index, y=by_hour[col], name=name, mode='lines+markers',
                                          line=dict(color=color, width=2),
                                          marker=dict(size=7, color=color),
                                          hovertemplate='%{y:.1f} °F'))
        shade_dark_hours(fig_hour)
        style_axes(fig_hour)
        fig_hour.update_layout(height=380, hovermode='x unified',
                               legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0))
        fig_hour.update_xaxes(**hour_ticks)
        fig_hour.update_yaxes(title_text='Air temperature (°F)')
        st.plotly_chart(fig_hour, config={'displaylogo': False, 'displayModeBar': False})

    with right:
        st.markdown('<p class="cs-panel-title">Treated minus reference by hour</p>', unsafe_allow_html=True)
        hour_diff = by_hour['Difference']
        fig_diff = go.Figure(go.Bar(
            x=hour_diff.index, y=hour_diff,
            marker=dict(color=[COOLER if v < 0 else WARMER for v in hour_diff.fillna(0)], cornerradius=3),
            hovertemplate='%{y:+.2f} °F<extra></extra>', name='Treated minus reference'))
        shade_dark_hours(fig_diff)
        style_axes(fig_diff)
        fig_diff.update_layout(height=380, showlegend=False, bargap=0.25)
        fig_diff.update_xaxes(**hour_ticks)
        fig_diff.update_yaxes(title_text='Difference (°F)', zeroline=True, zerolinecolor=AXIS, zerolinewidth=1,
                              range=symmetric_range(hour_diff.to_numpy(), floor=0.2))
        for text, y, anchor in [("Treated warmer", 0.98, 'top'), ("Treated cooler", 0.02, 'bottom')]:
            fig_diff.add_annotation(text=text, xref='x domain', yref='y domain', x=0.01, y=y, xanchor='left',
                                    yanchor=anchor, showarrow=False, font=dict(size=12, color=MUTED))
        st.plotly_chart(fig_diff, config={'displaylogo': False, 'displayModeBar': False})

# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------
def display_image(path, caption=None, max_size=None):
    if not os.path.exists(path):
        st.warning(f"Image not found: {path}")
        return
    if max_size:
        st.image(load_web_image(path, max_size, os.path.getmtime(path)), caption=caption)
    else:
        st.image(path, caption=caption)


st.subheader("The site")
map_col, photo_col = st.columns([3, 2], gap="large")
with map_col:
    display_image('location.png', max_size=1800,
                  caption="Logger locations. Treated streets are in the northern neighborhood "
                          "(21479990, 21479993, 21479994, 21479998); reference streets are to the south "
                          "(21471965, 21479991, 21479995).")
with photo_col:
    display_image('flir/FLIR1350-Visual.jpeg', caption="Pavement photo")
    display_image('flir/FLIR1350.jpg', caption="Thermal image of the same view (°F)")
