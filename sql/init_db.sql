-- Automatically create the youtube_analytics database on container initialization
SELECT 'CREATE DATABASE youtube_analytics'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'youtube_analytics')\gexec