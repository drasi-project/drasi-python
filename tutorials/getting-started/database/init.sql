-- Copyright 2026 The Drasi Authors.
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Getting Started Tutorial Database Schema
--
-- A single `message` table -- imagine a simple live message feed. The table and
-- columns are lower-case and unquoted so the node label and property names Drasi
-- sees match the Cypher continuous queries, which use (m:message) and m.message,
-- m.sender, m.messageid without any change.

-- Suppress noisy output during setup.
\set QUIET on
SET client_min_messages = ERROR;

-- Create a user with replication privileges for CDC.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'drasi_user') THEN
        CREATE USER drasi_user WITH REPLICATION LOGIN PASSWORD 'drasi_password';
    END IF;
END
$$;

-- Grant permissions on the database.
GRANT CREATE ON DATABASE getting_started TO drasi_user;
GRANT ALL PRIVILEGES ON DATABASE getting_started TO drasi_user;

-- Drop existing table if it exists.
DROP TABLE IF EXISTS message CASCADE;

-- message table: one row per message in the feed.
CREATE TABLE message (
    messageid  SERIAL PRIMARY KEY,
    sender     VARCHAR(50)  NOT NULL,
    message    VARCHAR(200) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Set REPLICA IDENTITY to FULL so change events include every column.
ALTER TABLE message REPLICA IDENTITY FULL;

-- Ensure drasi_user owns the table.
ALTER TABLE message OWNER TO drasi_user;

-- Grant permissions to drasi_user.
GRANT USAGE ON SCHEMA public TO drasi_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO drasi_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO drasi_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO drasi_user;

-- Create the publication for logical replication. The replication slot itself is
-- created by the Drasi PostgreSQL source on startup (with a consistent
-- snapshot), so the rows seeded below are loaded once via bootstrap and not also
-- replayed as change events.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'drasi_getting_started_pub') THEN
        CREATE PUBLICATION drasi_getting_started_pub FOR TABLE message;
    END IF;
END
$$;

-- Seed a few messages. One of them is exactly 'Hello World', which the
-- hello-world-from query matches.
INSERT INTO message (sender, message)
SELECT * FROM (VALUES
    ('Buzz Lightyear',  'To infinity and beyond!'),
    ('Brian Kernighan', 'Hello World'),
    ('Ada Lovelace',    'The Analytical Engine weaves algebraic patterns.')
) AS d(sender, message)
WHERE NOT EXISTS (SELECT 1 FROM message);

-- Summary.
SET client_min_messages = NOTICE;
DO $$
BEGIN
    RAISE NOTICE 'Getting Started database initialized successfully!';
    RAISE NOTICE 'Table: message';
    RAISE NOTICE 'Publication: drasi_getting_started_pub';
END
$$;
