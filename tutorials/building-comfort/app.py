# Copyright 2026 The Drasi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Building Comfort -- a Streamlit UI driven by a Drasi Python reaction.

Run it with:

    streamlit run app.py

The engine (Drasi + the six continuous queries + one Python reaction) is created
once and shared across every browser session by ``@st.cache_resource``. This
script only *reads* the reaction's snapshot and renders it, and offers controls
that write room changes back to Postgres for Drasi to observe via CDC.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import streamlit as st
from engine import (
    BUILDING_COMFORT_UI,
    COMFORT_MAX,
    COMFORT_MIN,
    FLOOR_ALERT,
    FLOOR_COMFORT_LEVEL,
    ROOM_ALERT,
    ComfortEngine,
)
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Building Comfort", page_icon="🏢", layout="wide")


@st.cache_resource
def get_engine() -> ComfortEngine:
    """Create (once) and return the shared Drasi engine.

    The spinner shows only on the very first run, while the engine downloads its
    plugins, connects to Postgres and bootstraps the queries.
    """
    engine = ComfortEngine()
    with st.spinner("Starting Drasi: installing plugins and connecting to Postgres..."):
        engine.wait_ready()
    return engine


def comfort_status(level: float) -> tuple[str, str]:
    """Map a comfort level to a status emoji and label."""
    if level > COMFORT_MAX:
        return "🔴", "too hot"
    if level < COMFORT_MIN:
        return "🔵", "too cold"
    return "🟢", "comfortable"


def render_building(rows: list[dict[str, Any]]) -> None:
    st.subheader("Building Comfort")
    if not rows:
        st.info("Waiting for room data...")
        return

    by_floor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_floor[row["FloorName"]].append(row)

    for floor_name in sorted(by_floor):
        st.markdown(f"### {floor_name}")
        for room in sorted(by_floor[floor_name], key=lambda r: r["RoomName"]):
            level = room["ComfortLevel"]
            emoji, label = comfort_status(level)
            st.markdown(
                f"- **{room['RoomName']}** — comfort **{level:g}** {emoji} {label}"
                f"  ·  🌡️ {room['Temperature']}°F"
                f"  💧 {room['Humidity']}%"
                f"  🫧 {room['CO2']} ppm"
            )


def render_overview(rows: list[dict[str, Any]]) -> None:
    st.subheader("Overall")
    if not rows:
        st.metric("Building comfort", "—")
        return

    average = sum(r["ComfortLevel"] for r in rows) / len(rows)
    emoji, label = comfort_status(average)
    st.metric("Building comfort", f"{average:.0f}", help="Average of every room")
    st.caption(f"{emoji} {label} · comfortable band is {COMFORT_MIN}–{COMFORT_MAX}")
    # A simple gauge: the comfort level on a 0–100 scale.
    st.progress(min(max(average / 100.0, 0.0), 1.0))


def render_floor_comfort(floor_rows: list[dict[str, Any]], ui_rows: list[dict[str, Any]]) -> None:
    st.subheader("Floor comfort")
    if not floor_rows:
        st.info("Waiting for floor data...")
        return

    names = {r["FloorId"]: r["FloorName"] for r in ui_rows}
    table = [
        {
            "Floor": names.get(r["FloorId"], r["FloorId"]),
            "Comfort level": round(r["ComfortLevel"], 1),
        }
        for r in sorted(floor_rows, key=lambda r: r["FloorId"])
    ]
    st.dataframe(table, hide_index=True, use_container_width=True)


def render_alerts(room_alerts: list[dict[str, Any]], floor_alerts: list[dict[str, Any]]) -> None:
    st.subheader("Comfort alerts")
    if room_alerts:
        for a in sorted(room_alerts, key=lambda r: r["RoomId"]):
            st.markdown(
                f"- ⚠️ **{a['RoomName']}** (`{a['RoomId']}`) — comfort **{a['ComfortLevel']:g}**"
            )
    else:
        st.success("All rooms are comfortable.")

    st.subheader("Floor alerts")
    if floor_alerts:
        for a in sorted(floor_alerts, key=lambda r: r["FloorId"]):
            st.markdown(
                f"- ⚠️ **{a['FloorName']}** (`{a['FloorId']}`) — comfort **{a['ComfortLevel']:g}**"
            )
    else:
        st.success("All floors are comfortable.")


def render_controls(engine: ComfortEngine, snapshot: dict[str, Any]) -> None:
    st.sidebar.header("Drive the demo")
    st.sidebar.caption(
        "These controls write SQL UPDATEs to Postgres. Drasi observes them via "
        "CDC and the view updates on its own — there is no middle tier."
    )

    # Simulation mode.
    simulate = st.sidebar.toggle("Simulation mode", value=snapshot["simulation"])
    if simulate != snapshot["simulation"]:
        engine.set_simulation(simulate)
        st.rerun()
    if simulate:
        st.sidebar.caption("Assigning a random room new readings every few seconds.")

    st.sidebar.divider()

    # Reset everything.
    if st.sidebar.button("Reset all rooms", use_container_width=True):
        engine.reset_room()
        st.toast("Reset every room to comfortable.")

    st.sidebar.divider()

    # Per-room controls.
    ui_rows = snapshot["results"].get(BUILDING_COMFORT_UI, [])
    if not ui_rows:
        return

    by_id = {r["RoomId"]: r for r in ui_rows}
    options = sorted(by_id, key=lambda rid: (by_id[rid]["FloorName"], by_id[rid]["RoomName"]))

    st.sidebar.subheader("Set a room")
    room_id = st.sidebar.selectbox(
        "Room",
        options,
        format_func=lambda rid: f"{by_id[rid]['FloorName']} / {by_id[rid]['RoomName']}",
    )
    current = by_id[room_id]

    with st.sidebar.form("set-room"):
        temperature = st.number_input("Temperature (°F)", value=int(current["Temperature"]))
        humidity = st.number_input("Humidity (%)", value=int(current["Humidity"]))
        co2 = st.number_input("CO₂ (ppm)", value=int(current["CO2"]))
        submitted = st.form_submit_button("Set room", use_container_width=True)
        if submitted:
            engine.set_room(room_id, int(temperature), int(humidity), int(co2))
            st.toast(f"Updated {current['RoomName']}.")

    if st.sidebar.button("Reset this room", use_container_width=True):
        engine.reset_room(room_id)
        st.toast(f"Reset {current['RoomName']} to comfortable.")


def main() -> None:
    engine = get_engine()

    # Re-run every 1.5s so the reaction's latest snapshot is rendered live.
    st_autorefresh(interval=1500, key="comfort-refresh")

    snapshot = engine.snapshot()
    if snapshot["error"]:
        st.error(f"The Drasi engine failed: {snapshot['error']}")
        return

    results = snapshot["results"]
    ui_rows = results.get(BUILDING_COMFORT_UI, [])
    building_name = ui_rows[0]["BuildingName"] if ui_rows else "Building Comfort"

    st.title(f"🏢 {building_name}")

    render_controls(engine, snapshot)

    left, right = st.columns([2, 1])
    with left:
        render_building(ui_rows)
    with right:
        render_overview(ui_rows)
        render_alerts(results.get(ROOM_ALERT, []), results.get(FLOOR_ALERT, []))

    render_floor_comfort(results.get(FLOOR_COMFORT_LEVEL, []), ui_rows)


if __name__ == "__main__":
    main()
