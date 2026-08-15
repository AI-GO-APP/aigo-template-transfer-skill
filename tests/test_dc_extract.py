# -*- coding: utf-8 -*-
"""dc_extract:租戶表定義 → DSL 的形狀轉換。

重點在 relation:AI GO 回 `target_table_id`(UUID),DSL 要 `target_table`(表 key)。
沒有這層對映,任何含 relation 的線上表都會在 DSL 驗證卡住。
"""
import unittest

import helpers  # noqa: F401
import dc_extract as dc


TABLES = [
    {"id": "11111111-1111-1111-1111-111111111111", "physical_name": "ad_avatars",
     "display_name": "人像素材庫"},
    {"id": "22222222-2222-2222-2222-222222222222", "physical_name": "ad_campaigns",
     "display_name": "行銷活動"},
]

DETAIL = {
    "physical_name": "ad_video_jobs",
    "display_name": "影片生成紀錄",
    "fields": [
        {"physical_name": "id", "field_type": "text", "is_required": True},
        {"physical_name": "created_at", "field_type": "datetime", "is_required": True},
        {"physical_name": "title", "field_type": "text", "is_required": True},
        {"physical_name": "avatar_ref", "field_type": "relation",
         "target_table_id": "11111111-1111-1111-1111-111111111111"},
        {"physical_name": "campaign_ref", "field_type": "relation",
         "target_table_id": "22222222-2222-2222-2222-222222222222"},
    ],
}


def field(table, key):
    return next(f for f in table["fields"] if f["key"] == key)


class TestTableIdMap(unittest.TestCase):
    def test_maps_id_to_key(self):
        m = dc.table_id_map(TABLES)
        self.assertEqual(m["11111111-1111-1111-1111-111111111111"], "ad_avatars")
        self.assertEqual(m["22222222-2222-2222-2222-222222222222"], "ad_campaigns")

    def test_tolerates_junk(self):
        self.assertEqual(dc.table_id_map(None), {})
        self.assertEqual(dc.table_id_map(["x", {}, {"id": "a"}, {"physical_name": "b"}]), {})


class TestRelationTarget(unittest.TestCase):
    def test_target_table_id_is_resolved_to_key(self):
        t = dc.table_to_dsl(DETAIL, dc.table_id_map(TABLES))
        self.assertEqual(field(t, "avatar_ref")["target_table"], "ad_avatars")
        self.assertEqual(field(t, "campaign_ref")["target_table"], "ad_campaigns")

    def test_explicit_target_table_wins_over_lookup(self):
        """--from-file 已經寫好 target_table 時不該被 id 對映蓋掉。"""
        detail = {"physical_name": "t", "fields": [
            {"physical_name": "ref", "field_type": "relation",
             "target_table": "already_a_key",
             "target_table_id": "11111111-1111-1111-1111-111111111111"}]}
        t = dc.table_to_dsl(detail, dc.table_id_map(TABLES))
        self.assertEqual(field(t, "ref")["target_table"], "already_a_key")

    def test_erp_key_still_supported(self):
        detail = {"physical_name": "t", "fields": [
            {"physical_name": "ref", "field_type": "relation", "target_erp_key": "customers"}]}
        t = dc.table_to_dsl(detail, {})
        self.assertEqual(field(t, "ref")["target_erp_key"], "customers")
        self.assertNotIn("target_table", field(t, "ref"))

    def test_unknown_id_leaves_target_absent(self):
        t = dc.table_to_dsl(DETAIL, {})
        self.assertNotIn("target_table", field(t, "avatar_ref"))

    def test_system_columns_still_dropped(self):
        t = dc.table_to_dsl(DETAIL, dc.table_id_map(TABLES))
        self.assertEqual([f["key"] for f in t["fields"]],
                         ["title", "avatar_ref", "campaign_ref"])


class TestUnresolvedRelations(unittest.TestCase):
    def test_reports_field_and_original_id(self):
        schema = {"version": 1, "tables": [dc.table_to_dsl(DETAIL, {})]}
        pending = dc.unresolved_relations(schema, [DETAIL])
        self.assertEqual(
            sorted(pending),
            [("ad_video_jobs.avatar_ref", "11111111-1111-1111-1111-111111111111"),
             ("ad_video_jobs.campaign_ref", "22222222-2222-2222-2222-222222222222")])

    def test_silent_when_all_resolved(self):
        schema = {"version": 1, "tables": [dc.table_to_dsl(DETAIL, dc.table_id_map(TABLES))]}
        self.assertEqual(dc.unresolved_relations(schema, [DETAIL]), [])


if __name__ == "__main__":
    unittest.main()
