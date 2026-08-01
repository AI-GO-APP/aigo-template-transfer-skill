"""自建表 / 引用表兩個端點面的路徑組裝。

回歸重點(0.4.0 修的 bug):data_center_schema 的表名**絕不能**出現在 /proxy 路徑上。
平台 /proxy 有 assert_table 硬驗 AI GO 快照,自建表名打過去一律 404,
而 0.3.4 以前的 e2e 正是這樣做,任何帶自建表的模板 S8 必然 hard_fail。
"""
import unittest

import helpers  # noqa: F401
import devportal_paths as paths


META_SELF = {
    "data_center_schema": {"tables": [
        {"key": "terp_customers", "display_name": "客戶", "fields": [
            {"key": "name", "display_name": "姓名", "type": "text"},
            {"key": "qty", "display_name": "數量", "type": "number"},
            {"key": "tier", "display_name": "等級", "type": "select", "options": ["vip", "std"]},
            {"key": "owner", "display_name": "負責人", "type": "relation",
             "target_table": "terp_users"},
        ]},
    ]},
}

META_REF = {
    "data_references_schema": [
        {"table_name": "account_account_tags", "columns": ["name", "color"]},
    ],
}

VID = "v-123"


class TestDeclarationReading(unittest.TestCase):
    def test_reads_dsl_array_shape(self):
        tables = paths.declared_tables(META_SELF)
        self.assertEqual([t["key"] for t in tables], ["terp_customers"])

    def test_reads_legacy_object_shape(self):
        meta = {"data_center_schema": {"tables": {"foo": {"fields": []}}}}
        self.assertEqual([t["key"] for t in paths.declared_tables(meta)], ["foo"])

    def test_tolerates_junk(self):
        for meta in ({}, {"data_center_schema": None}, {"data_center_schema": {"tables": 5}},
                     {"data_center_schema": {"tables": ["x", {"no_key": 1}]}}):
            self.assertEqual(paths.declared_tables(meta), [])

    def test_refs_filters_entries_without_table_name(self):
        meta = {"data_references_schema": [{"table_name": "a"}, {"columns": []}, "x"]}
        self.assertEqual([r["table_name"] for r in paths.declared_refs(meta)], ["a"])

    def test_refs_tolerates_junk(self):
        self.assertEqual(paths.declared_refs({"data_references_schema": {}}), [])


class TestSurfaceSeparation(unittest.TestCase):
    """核心回歸:兩個面不可互串。"""

    def test_self_declared_table_never_hits_proxy(self):
        key = paths.declared_tables(META_SELF)[0]["key"]
        for access_mode in ("internal", "external"):
            path = paths.data_records(VID, key, access_mode)
            self.assertIn("/data/objects/", path)
            self.assertNotIn("/proxy", path)

    def test_referenced_table_uses_proxy(self):
        name = paths.declared_refs(META_REF)[0]["table_name"]
        for access_mode in ("internal", "external"):
            self.assertIn("/proxy", paths.proxy_rows(VID, name, access_mode))

    def test_internal_proxy_carries_app_id_external_does_not(self):
        self.assertEqual(paths.proxy_rows(VID, "t", "internal"),
                         f"/sandbox/v/{VID}/proxy/{VID}/t")
        self.assertEqual(paths.proxy_rows(VID, "t", "external"),
                         f"/sandbox/v/{VID}/ext/proxy/t")

    def test_data_paths_switch_on_access_mode(self):
        self.assertEqual(paths.data_records(VID, "o", "internal"),
                         f"/sandbox/v/{VID}/data/objects/o/records")
        self.assertEqual(paths.data_records(VID, "o", "external"),
                         f"/sandbox/v/{VID}/ext/data/objects/o/records")

    def test_record_path_has_no_table_name(self):
        """平台 update/delete 以 record id 反查,路徑不帶表名。"""
        path = paths.data_record(VID, "r-1", "internal")
        self.assertEqual(path, f"/sandbox/v/{VID}/data/records/r-1")

    def test_missing_access_mode_defaults_to_internal(self):
        self.assertEqual(paths.proxy_rows(VID, "t", None), paths.proxy_rows(VID, "t", "internal"))

    def test_row_and_query_extend_the_list_path(self):
        base = paths.proxy_rows(VID, "t", "internal")
        self.assertEqual(paths.proxy_row(VID, "t", "r1", "internal"), base + "/r1")
        self.assertEqual(paths.proxy_query(VID, "t", "internal"), base + "/query")

    def test_seed_and_rows_are_reference_surface_only(self):
        """seed/rows 沒有 ext 變體,且平台同樣會驗 AI GO 快照。"""
        self.assertIn("/tables/", paths.table_seed(VID, "t"))
        self.assertNotIn("ext", paths.table_rows(VID, "t"))


class TestSampleRows(unittest.TestCase):
    def test_dsl_sample_covers_types_and_skips_relation(self):
        fields = paths.declared_tables(META_SELF)[0]["fields"]
        row = paths.sample_for_fields(fields)
        self.assertEqual(row["qty"], 1)
        self.assertEqual(row["tier"], "vip")
        self.assertIsInstance(row["name"], str)
        self.assertNotIn("owner", row)  # relation 需要真外鍵

    def test_dsl_sample_tolerates_junk(self):
        self.assertEqual(paths.sample_for_fields(None), {})
        self.assertEqual(paths.sample_for_fields([{"no_key": 1}, "x"]), {})

    def test_sql_sample_only_required_non_system_columns(self):
        cols = [
            {"name": "id", "type": "UUID", "nullable": False, "is_system": True},
            {"name": "name", "type": "VARCHAR", "nullable": False, "is_system": False},
            {"name": "color", "type": "INTEGER", "nullable": True, "is_system": False},
            {"name": "country_id", "type": "UUID", "nullable": False, "is_system": False},
            {"name": "active", "type": "BOOLEAN", "nullable": False, "is_system": False},
        ]
        row = paths.sample_for_columns(cols)
        self.assertEqual(set(row), {"name", "active"})  # 系統欄、可空欄、外鍵 UUID 都不填
        self.assertIs(row["active"], True)

    def test_sql_sample_unknown_type_falls_back(self):
        row = paths.sample_for_columns(
            [{"name": "x", "type": "WEIRDTYPE", "nullable": False, "is_system": False}])
        self.assertEqual(row["x"], "e2e")

    def test_sql_sample_tolerates_junk(self):
        self.assertEqual(paths.sample_for_columns(None), {})


class TestSeededRowIdentification(unittest.TestCase):
    """seed 週期靠這組判定「哪幾列是自己 seed 的」;錯了就會刪到既有沙箱資料。"""

    def test_new_rows_is_the_id_difference(self):
        before = [{"id": "a"}, {"id": "b"}]
        after = before + [{"id": "c", "name": "seeded"}]
        mine = paths.new_rows(paths.row_ids(before), after)
        self.assertEqual([r["id"] for r in mine], ["c"])

    def test_rows_without_id_are_never_mine(self):
        """組不出 proxy_row 路徑的列不能收進來——舊版收了,delete 時 KeyError 炸掉整支 e2e。"""
        mine = paths.new_rows(set(), [{"name": "no id here"}, {"id": None}, {"id": "x"}])
        self.assertEqual([r["id"] for r in mine], ["x"])

    def test_failed_before_snapshot_is_distinguishable_from_empty_table(self):
        """兩者的 row_ids 都是空集合,故呼叫端必須另外看 is_row_list——這是不刪光整表的唯一防線。"""
        self.assertEqual(paths.row_ids({"detail": "HTTP 500"}), set())
        self.assertEqual(paths.row_ids([]), set())
        self.assertFalse(paths.is_row_list({"detail": "HTTP 500"}))
        self.assertTrue(paths.is_row_list([]))

    def test_new_rows_tolerates_junk_after(self):
        self.assertEqual(paths.new_rows(set(), None), [])
        self.assertEqual(paths.new_rows(set(), [{"id": "a"}, "junk", 3]), [{"id": "a"}])

    def test_updatable_field_skips_foreign_keys_and_system_columns(self):
        row = {"id": "r1", "created_at": "2026-01-01", "partner_id": "p1",
               "qty": 3, "note": "hello"}
        self.assertEqual(paths.updatable_field(row), "note")

    def test_updatable_field_none_when_no_plain_string_column(self):
        self.assertIsNone(paths.updatable_field({"id": "r1", "qty": 3, "owner_id": "o1"}))
        self.assertIsNone(paths.updatable_field(None))


if __name__ == "__main__":
    unittest.main()
