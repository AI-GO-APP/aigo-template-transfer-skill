"""沙箱資料面的路徑組裝——把「自建表」與「引用表」這兩個面分清楚。

平台有兩組長得像、語意完全不同的資料端點,餵錯表名 100% 404:

| metadata 欄位                | 語意             | 沙箱端點                              | SDK        |
|------------------------------|------------------|---------------------------------------|------------|
| `data_center_schema.tables[]`| 模板**自建**表   | `/data-center/tables/{key}/records`   | data_table |
| `data_references_schema[]`   | 引用 AI GO 既有表| `/proxy/{app_id}/{table}`             | proxy      |

自建表這一面的路徑在平台端換過:舊的 `/data/objects/{slug}/records` **已隨 AI GO 退場**
(見 ai-go-developer `backend/app/api/sandbox.py` 的 `_data_center_router` 檔頭註解),
現行是 `/data-center/tables/{table}/records`,且 update/delete **要帶表名**
(舊面是以 record id 全域反查)。舊面在平台上回 404,任何帶自建表的模板 S8 必然 hard_fail。

`/proxy` 與 `/tables/{t}/seed|rows` 這一面在平台端有 `assert_table` 硬驗 AI GO
快照(ai-go-developer `ctx_core/sandbox.py`),自建表名打過去一律回 404
「AI GO 無此表」。0.3.4 以前的 e2e 正是把 `data_center_schema` 的表名餵給
`/proxy`,任何帶自建表的模板 S8 必然 hard_fail,而真正該測的自建表那一面
從沒被呼叫過。

external 模板走 `ext/` 前綴且不帶 app_id,故所有組裝都吃 access_mode。
本模組**純函式、不做 I/O**,可單元測試。
"""
from typing import Any

# 平台對「引用表」CRUD 的 internal 形式路徑帶 app_id;沙箱以 version_id 充當。
# external 形式(ext/)不帶,兩者資料是同一份。


def is_external(access_mode: str | None) -> bool:
    return (access_mode or "internal") == "external"


# ── metadata 讀取(兩種宣告面)──────────────────────────────────

def declared_tables(meta: dict) -> list[dict]:
    """`data_center_schema` 宣告的**自建**表 spec。

    DSL 正式形狀是陣列 `[{key, display_name, fields: [...]}]`;歷史資料也出現過
    以表名為鍵的物件形狀(平台 preflight 同樣兩種都吃,見 ai-go-developer
    `preflight._declared_dc_tables`)。壞資料一律略過而不是炸掉。
    """
    dcs = meta.get("data_center_schema")
    if not isinstance(dcs, dict):
        return []
    raw = dcs.get("tables")
    out: list[dict] = []
    if isinstance(raw, list):
        for t in raw:
            if isinstance(t, dict) and t.get("key"):
                out.append(t)
    elif isinstance(raw, dict):
        for key, t in raw.items():
            if isinstance(t, dict):
                out.append({**t, "key": t.get("key") or key})
    return out


def declared_refs(meta: dict) -> list[dict]:
    """`data_references_schema` 宣告的 AI GO 引用表 `[{table_name, columns}]`。"""
    raw = meta.get("data_references_schema")
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict) and r.get("table_name")]


# ── 自建表(data_table SDK 面)────────────────────────────────

def _dc_prefix(access_mode: str | None) -> str:
    return "ext/data-center" if is_external(access_mode) else "data-center"


def data_tables(version_id: str, access_mode: str | None) -> str:
    """列出自建表結構(宣告了但還沒資料的表也會列)。"""
    return f"/sandbox/v/{version_id}/{_dc_prefix(access_mode)}/tables"


def data_records(version_id: str, object_key: str, access_mode: str | None) -> str:
    return f"/sandbox/v/{version_id}/{_dc_prefix(access_mode)}/tables/{object_key}/records"


def data_record(version_id: str, object_key: str, record_id: str,
                access_mode: str | None) -> str:
    """update/delete 的路徑**帶表名**——新的資料中心面以 (表, id) 定位。"""
    return f"{data_records(version_id, object_key, access_mode)}/{record_id}"


# ── 引用表(proxy SDK 面)──────────────────────────────────────

def proxy_rows(version_id: str, table: str, access_mode: str | None) -> str:
    if is_external(access_mode):
        return f"/sandbox/v/{version_id}/ext/proxy/{table}"
    return f"/sandbox/v/{version_id}/proxy/{version_id}/{table}"


def proxy_row(version_id: str, table: str, row_id: str, access_mode: str | None) -> str:
    return f"{proxy_rows(version_id, table, access_mode)}/{row_id}"


def proxy_query(version_id: str, table: str, access_mode: str | None) -> str:
    return f"{proxy_rows(version_id, table, access_mode)}/query"


def table_seed(version_id: str, table: str, count: int = 3) -> str:
    """只適用引用表(平台會驗 AI GO 快照)。無 ext 變體。"""
    return f"/sandbox/v/{version_id}/tables/{table}/seed?count={count}"


def table_rows(version_id: str, table: str) -> str:
    return f"/sandbox/v/{version_id}/tables/{table}/rows"


# ── 測試樣本列 ────────────────────────────────────────────────

# image 欄位存的是**檔案路徑字串**(前端上傳後拿到的 key),不是二進位。
# 這裡原本給 None,結果 required 的 image 欄位一律以
# `not_null_violation ... 缺必填欄位` 422 收場——而那不是模板的錯:
# action 端沒有 storage 模組,伺服器端根本產不出合法路徑,任何通用路徑
# (seed、匯入、本 e2e)都滿足不了必填 image。給一個佔位字串讓 CRUD 跑得完;
# 這一列在 insert→list→update→delete 的最後就被刪掉,不會留下髒資料。
_DSL_SAMPLE: dict[str, Any] = {
    "text": "e2e 測試", "number": 1, "boolean": True,
    "date": "2026-01-01", "datetime": "2026-01-01T00:00:00",
    "json": {}, "image": "e2e-placeholder.png",
}


def sample_for_fields(fields: Any) -> dict:
    """自建表:依 DSL 欄位型別給一列樣本。relation 需要真實外鍵,略過。"""
    row: dict[str, Any] = {}
    if not isinstance(fields, list):
        return row
    for f in fields:
        if not isinstance(f, dict) or not f.get("key"):
            continue
        ftype = f.get("type")
        if ftype == "relation":
            continue
        if ftype == "select":
            row[f["key"]] = (f.get("options") or ["e2e"])[0]
        else:
            row[f["key"]] = _DSL_SAMPLE.get(ftype, "e2e")
    return row


_SQL_SAMPLE: dict[str, Any] = {
    "VARCHAR": "e2e 測試", "TEXT": "e2e 測試", "CHAR": "e2e",
    "INTEGER": 1, "BIGINT": 1, "SMALLINT": 1, "NUMERIC": 1, "DECIMAL": 1,
    "REAL": 1.0, "DOUBLE PRECISION": 1.0, "FLOAT": 1.0,
    "BOOLEAN": True, "DATE": "2026-01-01",
    "TIMESTAMP": "2026-01-01T00:00:00", "TIMESTAMPTZ": "2026-01-01T00:00:00",
    "JSON": {}, "JSONB": {},
}


def sample_for_columns(columns: Any) -> dict:
    """引用表:依 `GET /refs/tables/{t}/columns` 的真實欄位給一列樣本。

    只填 **NOT NULL 且非系統欄** 的欄位——插一列只是要證明 CRUD 通,
    多填反而容易踩到約束。UUID 一律略過:那幾乎都是外鍵,亂給會違反 FK。
    """
    row: dict[str, Any] = {}
    if not isinstance(columns, list):
        return row
    for c in columns:
        if not isinstance(c, dict) or not c.get("name"):
            continue
        if c.get("is_system") or c.get("nullable", True):
            continue
        ctype = str(c.get("type") or "").upper()
        if ctype == "UUID":
            continue
        row[c["name"]] = _SQL_SAMPLE.get(ctype, "e2e")
    return row


# ── seed 週期的列辨識 ──────────────────────────────────────────
# e2e 用 seed 代 insert 時,「哪幾列是自己 seed 出來的」全靠 seed 前後的 id 差集。
# 這組判定錯了就會刪到既有沙箱資料,故抽成純函式獨立測。

def row_ids(rows: Any) -> set:
    """list 回應裡的 id 集合。非 list(端點失敗、回錯形狀)一律回空集合。

    **呼叫端不可拿「回空集合」當成「表是空的」**——兩者在這裡分不出來,
    要靠 `is_row_list()` 先確認回應本身可信,見 `new_rows` 的 docstring。
    """
    if not isinstance(rows, list):
        return set()
    return {r["id"] for r in rows if isinstance(r, dict) and r.get("id") is not None}


def is_row_list(rows: Any) -> bool:
    """這份回應能不能當成可信的列快照。"""
    return isinstance(rows, list)


def new_rows(before_ids: set, after: Any) -> list[dict]:
    """seed 之後多出來的列(帶得出 id 的才算)。

    沒有 id 的列一律排除:組不出 `proxy_row` 路徑就談不上 update/delete,
    早期版本用 `r.get("id") not in before_ids` 收進來,後面 `r["id"]` 直接 KeyError。

    **before 快照不可信時不准呼叫這支**——`before_ids` 會是空集合,
    差集就等於整張表,呼叫端接著刪 = 刪光既有沙箱資料。
    """
    if not isinstance(after, list):
        return []
    return [r for r in after if isinstance(r, dict)
            and r.get("id") is not None and r["id"] not in before_ids]


def updatable_field(row: dict) -> str | None:
    """挑一個可以 no-op 回填的字串欄,用來證明 PATCH 這條路通。

    外鍵(`*_id`)與系統欄不碰——亂改會踩 FK 或被平台拒絕。
    """
    if not isinstance(row, dict):
        return None
    return next((k for k, v in row.items()
                 if isinstance(v, str) and k not in ("id", "created_at", "updated_at")
                 and not k.endswith("_id")), None)
