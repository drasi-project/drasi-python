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

"""Curbside Pickup -- one integrated Streamlit UI driven by a Drasi reaction.

Run it with:

    streamlit run app.py

The six panels are rendered live from a Python reaction over two databases, and
the same page drives the changes: the Orders and Vehicles panels have inline
buttons that write to Postgres / MySQL, and the sidebar has a reset button and a
color-coded log of the SQL each button ran. No dashboard reaction, no separate
console -- the reaction *is* the application.
"""

from __future__ import annotations

from typing import Any

import streamlit as st
from demo.config import DELAY_SECONDS
from demo.engine import CurbsideEngine
from demo.queries import (
    DELAY,
    DELIVERY,
    ORDERS_PREPARING,
    ORDERS_READY,
    VEHICLES_CURBSIDE,
    VEHICLES_PARKING,
)
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Curbside Pickup", page_icon="🛒", layout="wide")


@st.cache_resource
def get_engine() -> CurbsideEngine:
    """Create (once) and return the shared Drasi engine."""
    engine = CurbsideEngine()
    with st.spinner("Starting Drasi: installing plugins and connecting to Postgres + MySQL..."):
        engine.wait_ready()
    return engine


def order_panel(rows: list[dict[str, Any]], *, ready: bool, engine: CurbsideEngine) -> None:
    title = "🍕 Orders · Ready" if ready else "🍕 Orders · Preparing"
    st.subheader(title)
    if not rows:
        st.caption("_No orders ready._" if ready else "_No orders being prepared._")
        return
    for row in sorted(rows, key=lambda r: r["orderId"]):
        st.markdown(f"**Order {row['orderId']}** — {row['customerName']} — plate `{row['plate']}`")
        if ready:
            if st.button("↩ Preparing", key=f"order-prep-{row['id']}", use_container_width=True):
                engine.set_order_status(int(row["id"]), "preparing")
                st.rerun()
        else:
            if st.button("Mark ready →", key=f"order-ready-{row['id']}", use_container_width=True):
                engine.set_order_status(int(row["id"]), "ready")
                st.rerun()


def vehicle_panel(rows: list[dict[str, Any]], *, curbside: bool, engine: CurbsideEngine) -> None:
    title = "🚗 Vehicles · Curbside" if curbside else "🚗 Vehicles · Parking"
    st.subheader(title)
    if not rows:
        st.caption("_No vehicles at the curb._" if curbside else "_No vehicles parked._")
        return
    for row in sorted(rows, key=lambda r: r["plate"]):
        st.markdown(f"**`{row['plate']}`** — {row['color']} {row['make']} {row['model']}")
        if curbside:
            if st.button("↩ Parking", key=f"veh-park-{row['plate']}", use_container_width=True):
                engine.set_vehicle_location(row["plate"], "Parking")
                st.rerun()
        else:
            if st.button("To Curbside →", key=f"veh-curb-{row['plate']}", use_container_width=True):
                engine.set_vehicle_location(row["plate"], "Curbside")
                st.rerun()


def matched_panel(rows: list[dict[str, Any]]) -> None:
    st.subheader("📦 Matched Orders")
    st.caption("Ready **and** the driver is at the curbside — carry it out.")
    if not rows:
        st.info("No matched orders yet. Mark an order ready and bring its vehicle to the curbside.")
        return
    for row in sorted(rows, key=lambda r: r["orderId"]):
        st.success(
            f"**Order {row['orderId']}** — {row['customerName']} — "
            f"{row['vehicleColor']} {row['vehicleMake']} {row['vehicleModel']} "
            f"(`{row['vehicleId']}`) is at the curbside."
        )


def _short_time(value: Any) -> str:
    """Show just the clock time from an ISO timestamp like 2026-07-31T00:58:53+00:00."""
    text = str(value)
    if "T" in text:
        return text.split("T", 1)[1][:8]
    return text


def delayed_panel(rows: list[dict[str, Any]]) -> None:
    st.subheader("⚠️ Delayed Orders")
    st.caption(f"At the curbside over {DELAY_SECONDS}s while the order is still not ready.")
    if not rows:
        st.info("No delayed orders.")
        return
    for row in sorted(rows, key=lambda r: r["orderId"]):
        st.warning(
            f"**Order {row['orderId']}** — {row['customerName']} — "
            f"waiting since {_short_time(row.get('waitingSinceTimestamp', ''))}"
        )


def render_sidebar(engine: CurbsideEngine, activity: list[dict[str, Any]]) -> None:
    st.sidebar.header("Drive the demo")
    st.sidebar.caption(
        "The buttons on each order and vehicle run a real SQL UPDATE — orders in "
        "PostgreSQL, vehicles in MySQL. Drasi observes both via CDC and the panels "
        "update on their own."
    )
    if st.sidebar.button("Reset everything", use_container_width=True):
        engine.reset()
        st.toast("Reset: all orders preparing, all vehicles parking.")
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("Activity log")
    if not activity:
        st.sidebar.caption("SQL you run will appear here, colored by database.")
        return
    for entry in reversed(activity):
        color = "blue" if entry["db"] == "PostgreSQL" else "orange"
        st.sidebar.markdown(
            f":gray[{entry['at']}] :{color}[**[{entry['db']}]**]  \n`{entry['sql']}`"
        )


def main() -> None:
    engine = get_engine()
    st_autorefresh(interval=1000, key="curbside-refresh")

    snapshot = engine.snapshot()
    if snapshot["error"]:
        st.error(f"The Drasi engine failed: {snapshot['error']}")
        return
    results = snapshot["results"]

    st.title("🛒 Curbside Pickup")
    st.caption(
        "Orders live in **PostgreSQL**, vehicles live in **MySQL**. Drasi joins them "
        "by license plate and reacts to changes on either side — no polling."
    )

    render_sidebar(engine, snapshot["activity"])

    top = st.columns(4)
    with top[0]:
        order_panel(results.get(ORDERS_PREPARING, []), ready=False, engine=engine)
    with top[1]:
        order_panel(results.get(ORDERS_READY, []), ready=True, engine=engine)
    with top[2]:
        vehicle_panel(results.get(VEHICLES_PARKING, []), curbside=False, engine=engine)
    with top[3]:
        vehicle_panel(results.get(VEHICLES_CURBSIDE, []), curbside=True, engine=engine)

    st.divider()

    bottom = st.columns(2)
    with bottom[0]:
        matched_panel(results.get(DELIVERY, []))
    with bottom[1]:
        delayed_panel(results.get(DELAY, []))


if __name__ == "__main__":
    main()
