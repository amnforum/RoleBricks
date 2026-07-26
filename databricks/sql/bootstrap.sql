-- Run once in the Databricks SQL editor before the first bundle deployment.
-- Change the catalog or schema here only if you also change databricks.yml and app.yaml.

CREATE SCHEMA IF NOT EXISTS main.emotionos_worlds;

CREATE TABLE IF NOT EXISTS main.emotionos_worlds.scene_memory_search (
  record_id STRING NOT NULL,
  scene_id STRING NOT NULL,
  character_key STRING,
  record_type STRING NOT NULL,
  content STRING NOT NULL,
  title STRING,
  url STRING,
  freshness STRING,
  importance INT,
  visibility STRING,
  updated_at TIMESTAMP NOT NULL
)
USING DELTA
TBLPROPERTIES (
  delta.enableChangeDataFeed = true,
  delta.enableRowTracking = true
);

CREATE TABLE IF NOT EXISTS main.emotionos_worlds.scene_provider_usage (
  event_id STRING NOT NULL,
  scene_id STRING NOT NULL,
  operation STRING NOT NULL,
  provider STRING NOT NULL,
  model STRING,
  prompt_tokens BIGINT,
  completion_tokens BIGINT,
  latency_ms BIGINT,
  succeeded BOOLEAN,
  occurred_at TIMESTAMP NOT NULL
)
USING DELTA
TBLPROPERTIES (delta.enableChangeDataFeed = true);
