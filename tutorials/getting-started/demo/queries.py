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

"""The three continuous queries that power the demo.

They build up in complexity: a filter, an aggregation, and a temporal query that
detects the *absence* of change. Each is written out in full so you can read
exactly what Drasi runs.
"""

from __future__ import annotations

from dataclasses import dataclass

# Query ids, used to register the queries and to label their console output.
HELLO_WORLD_FROM = "hello-world-from"
MESSAGE_COUNT = "message-count"
INACTIVE_PEOPLE = "inactive-people"


@dataclass(frozen=True)
class Query:
    """One continuous query: how to register it and how to index its rows."""

    id: str
    key: str  # the RETURN column that identifies each row (its primary key)
    cypher: str


# Filter: messages whose text is exactly "Hello World", with who sent them.
HELLO_WORLD_FROM_QUERY = Query(
    id=HELLO_WORLD_FROM,
    key="MessageId",
    cypher="""
    MATCH (m:message)
    WHERE m.message = 'Hello World'
    RETURN m.messageid AS MessageId, m.sender AS MessageFrom
    """,
)

# Aggregation: how many times each distinct message has been sent.
MESSAGE_COUNT_QUERY = Query(
    id=MESSAGE_COUNT,
    key="Message",
    cypher="""
    MATCH (m:message)
    RETURN m.message AS Message, count(m) AS Frequency
    """,
)

# Temporal: senders who have not sent a message in the last 20 seconds.
# drasi.trueLater schedules a future re-evaluation so a sender appears the instant
# they cross the 20-second threshold, not only when some other change happens.
INACTIVE_PEOPLE_QUERY = Query(
    id=INACTIVE_PEOPLE,
    key="MessageFrom",
    cypher="""
    MATCH (m:message)
    WITH m.sender AS MessageFrom, max(drasi.changeDateTime(m)) AS LastMessageTimestamp
    WHERE LastMessageTimestamp <= datetime.realtime() - duration({ seconds: 20 })
       OR drasi.trueLater(
            LastMessageTimestamp <= datetime.realtime() - duration({ seconds: 20 }),
            LastMessageTimestamp + duration({ seconds: 20 })
          )
    RETURN MessageFrom, LastMessageTimestamp
    """,
)

# The engine registers these in order and subscribes one reaction to them all.
QUERIES = [
    HELLO_WORLD_FROM_QUERY,
    MESSAGE_COUNT_QUERY,
    INACTIVE_PEOPLE_QUERY,
]
