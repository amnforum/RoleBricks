from pyspark import pipelines as dp
from pyspark.sql import functions as F


SOURCE_TABLE = spark.conf.get(
    "emotionos.source_table",
    "main.emotionos_worlds.scene_memory_search",
)


def changed_records():
    return (
        spark.readStream.option("readChangeFeed", "true")
        .table(SOURCE_TABLE)
        .where(F.col("_change_type").isin("insert", "update_postimage"))
        .drop("_change_type", "_commit_version", "_commit_timestamp")
    )


@dp.table(
    name="scene_memory_enriched",
    comment="Validated searchable memories and sources for living scenes.",
)
@dp.expect_or_drop("has_scene", "scene_id IS NOT NULL AND length(scene_id) > 0")
@dp.expect_or_drop("has_content", "content IS NOT NULL AND length(trim(content)) > 0")
def scene_memory_enriched():
    return changed_records().withColumn(
        "search_text",
        F.concat_ws(
            " | ",
            F.coalesce(F.col("title"), F.lit("")),
            F.col("content"),
            F.coalesce(F.col("character_key"), F.lit("scene")),
        ),
    )


@dp.table(
    name="scene_relationship_snapshots",
    comment="Incremental relationship and reflection checkpoints.",
)
def scene_relationship_snapshots():
    return (
        changed_records()
        .where(F.col("record_type") == "reflection")
        .select(
            "record_id",
            "scene_id",
            "character_key",
            "content",
            "importance",
            "visibility",
            "updated_at",
        )
    )


@dp.table(
    name="scene_grounding_sources",
    comment="Timestamped public evidence available to scene characters.",
)
def scene_grounding_sources():
    return (
        changed_records()
        .where(F.col("record_type") == "source")
        .select(
            "record_id",
            "scene_id",
            "character_key",
            "title",
            "url",
            "content",
            "freshness",
            "updated_at",
        )
    )
