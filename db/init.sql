-- Sole job: create the SEPARATE, EMPTY database that ADK's DatabaseSessionService uses. ADK
-- auto-creates its own tables there on first connect, and we must not create any
-- (agent-platform docs/ADK_LESSONS_LEARNED.md §6a).
SELECT 'CREATE DATABASE aziza_sessions'
 WHERE NOT EXISTS (
     SELECT FROM pg_database WHERE datname = 'aziza_sessions'
 )\gexec
