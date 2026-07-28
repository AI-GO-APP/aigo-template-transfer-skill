import unittest

import helpers  # noqa: F401  路徑設定
from dsl_validator import validate_data_center_schema


def table(**over):
    base = {
        "key": "tickets",
        "display_name": "工單",
        "fields": [{"key": "title", "display_name": "標題", "type": "text"}],
    }
    base.update(over)
    return base


class TestDslValidator(unittest.TestCase):
    def test_empty_schema_ok(self):
        self.assertEqual(validate_data_center_schema(None), [])
        self.assertEqual(validate_data_center_schema({}), [])

    def test_valid_schema(self):
        schema = {"version": 1, "tables": [table(seed=[{"title": "T-001"}])]}
        self.assertEqual(validate_data_center_schema(schema), [])

    def test_bad_version(self):
        errors = validate_data_center_schema({"version": 2, "tables": [table()]})
        self.assertTrue(any("version" in e for e in errors))

    def test_system_field_name_rejected(self):
        schema = {"version": 1, "tables": [table(fields=[
            {"key": "created_at", "display_name": "建立時間", "type": "datetime"}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("系統欄名" in e for e in errors))

    def test_bad_identifier(self):
        schema = {"version": 1, "tables": [table(key="Tickets")]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("非合法實體表名" in e for e in errors))

    def test_unknown_type(self):
        schema = {"version": 1, "tables": [table(fields=[
            {"key": "x", "display_name": "X", "type": "uuid"}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("不支援" in e for e in errors))

    def test_select_requires_options(self):
        schema = {"version": 1, "tables": [table(fields=[
            {"key": "status", "display_name": "狀態", "type": "select"}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("options 不可為空" in e for e in errors))

    def test_relation_target_must_exist(self):
        schema = {"version": 1, "tables": [table(fields=[
            {"key": "ref", "display_name": "關聯", "type": "relation", "target_table": "nope"}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("未宣告的表" in e for e in errors))

    def test_relation_both_targets_rejected(self):
        schema = {"version": 1, "tables": [table(fields=[
            {"key": "ref", "display_name": "關聯", "type": "relation",
             "target_table": "tickets", "target_erp_key": "res_partner"}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("恰一" in e for e in errors))

    def test_non_relation_with_target_rejected(self):
        schema = {"version": 1, "tables": [table(fields=[
            {"key": "x", "display_name": "X", "type": "text", "target_table": "tickets"}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("非 relation" in e for e in errors))

    def test_seed_unknown_field(self):
        schema = {"version": 1, "tables": [table(seed=[{"nope": 1}])]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("未宣告欄位" in e for e in errors))

    def test_cycle_detected(self):
        schema = {"version": 1, "tables": [
            {"key": "a", "display_name": "A", "fields": [
                {"key": "b_ref", "display_name": "B", "type": "relation", "target_table": "b"}]},
            {"key": "b", "display_name": "B", "fields": [
                {"key": "a_ref", "display_name": "A", "type": "relation", "target_table": "a"}]},
        ]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("成環" in e for e in errors))

    def test_self_reference_ok(self):
        schema = {"version": 1, "tables": [
            {"key": "persons", "display_name": "人員", "fields": [
                {"key": "manager", "display_name": "主管", "type": "relation",
                 "target_table": "persons"}]},
        ]}
        self.assertEqual(validate_data_center_schema(schema), [])

    def test_duplicate_table_and_field_keys(self):
        schema = {"version": 1, "tables": [table(), table()]}
        errors = validate_data_center_schema(schema)
        self.assertTrue(any("表 key 重複" in e for e in errors))
        schema2 = {"version": 1, "tables": [table(fields=[
            {"key": "x", "display_name": "X", "type": "text"},
            {"key": "x", "display_name": "X2", "type": "text"}])]}
        errors2 = validate_data_center_schema(schema2)
        self.assertTrue(any("欄位 key 重複" in e for e in errors2))


if __name__ == "__main__":
    unittest.main()
