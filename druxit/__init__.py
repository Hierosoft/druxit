"""Druxit – dynamic Drupal 9 exporter.

This module exports published pages and articles from a Drupal 9 database
with full support for custom fields, taxonomy, URL aliases, and paragraph
children/parents. All discovery is dynamic – no hardcoded field names.

Example:
    >>> from druxit import export_nodes
    >>> export_nodes(db="mydb", user="root", password="secret")
"""

__version__ = "0.1.0"

import json
import os
import getpass
import mysql.connector
from typing import List, Dict, Any


SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "settings.json")
BLACKLIST = ["_zen_", "_revision"]


def _load_settings() -> Dict[str, str]:
    """Load connection settings from settings.json if present.

    Returns:
        Dict containing 'database', 'user', and optionally 'password'.
    """
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    return {}


def _save_settings(db: str, user: str, password: str | None = None) -> None:
    """Save connection settings to settings.json.

    Args:
        db: Database name.
        user: Database username.
        password: Database password (optional; omit to remove from file).
    """
    data = {"database": db, "user": user}
    if password is not None:
        data["password"] = password
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def export_nodes(db: str, user: str, password: str, host: str = "localhost") -> List[Dict[str, Any]]:
    """Export all published pages and articles from Drupal 9.

    Args:
        db: Database name.
        user: Database username.
        password: Database password.
        host: MySQL host (default: localhost).

    Returns:
        List of dictionaries, each representing a node with metadata,
        fields, children, and parents.
    """
    conn = mysql.connector.connect(host=host, database=db, user=user, password=password)
    cur = conn.cursor()

    # Discover field tables
    cur.execute("SHOW TABLES LIKE 'node__field_%'")
    field_tables = [
        t[0] for t in cur.fetchall()
        if not any(b in t[0] for b in BLACKLIST)
    ]

    # Map bundles to tables
    bundle_tables = {}
    for tbl in field_tables:
        cur.execute(f"SELECT DISTINCT bundle FROM `{tbl}` WHERE deleted = 0")
        bundle_tables[tbl] = [r[0] for r in cur.fetchall()]

    # Fetch nodes
    cur.execute("""
        SELECT n.nid, n.vid, n.type, nfd.title, nfd.langcode
        FROM node n
        JOIN node_field_data nfd ON n.nid = nfd.nid AND n.vid = nfd.vid
        WHERE n.type IN ('page', 'article') AND nfd.status = 1
        ORDER BY n.type, nfd.title
    """)
    nodes = cur.fetchall()

    results = []
    for nid, vid, ctype, title, lang in nodes:
        meta = {
            "nid": nid,
            "vid": vid,
            "type": ctype,
            "title": title,
            "langcode": lang,
            "url": _url_alias(cur, nid),
            "categories": _taxonomy_terms(cur, nid),
            "fields": _node_fields(cur, nid, vid, ctype, field_tables, bundle_tables),
            "children": _children(cur, nid),
            "parents": _parents(cur, nid),
        }
        results.append(meta)
        print(json.dumps(meta, indent=2))

    cur.close()
    conn.close()
    return results


def _url_alias(cur, nid: int) -> str:
    """Get URL alias for a node.

    Args:
        cur: Active database cursor.
        nid: Node ID.

    Returns:
        URL alias string or /node/{nid} if not found.
    """
    cur.execute(
        "SELECT alias FROM path_alias WHERE path = CONCAT('/node/', %s) ORDER BY id DESC LIMIT 1",
        (nid,),
    )
    row = cur.fetchone()
    return row[0] if row else f"/node/{nid}"


def _taxonomy_terms(cur, nid: int) -> List[str]:
    """Get taxonomy term names for a node.

    Args:
        cur: Active database cursor.
        nid: Node ID.

    Returns:
        List of term names.
    """
    cur.execute(
        """
        SELECT DISTINCT t.name
        FROM taxonomy_index ti
        JOIN taxonomy_term_field_data t ON ti.tid = t.tid
        WHERE ti.nid = %s AND t.langcode = 'en'
        """,
        (nid,),
    )
    return [r[0] for r in cur.fetchall()]


def _node_fields(cur, nid: int, vid: int, bundle: str,
                 field_tables: List[str], bundle_tables: dict) -> Dict[str, Any]:
    """Extract all field values for a node.

    Args:
        cur: Active database cursor.
        nid: Node ID.
        vid: Revision ID.
        bundle: Content type (e.g. 'page').
        field_tables: List of node__field_* tables.
        bundle_tables: Mapping of table to bundles.

    Returns:
        Dictionary of field_name -> value(s).
    """
    fields = {}
    for tbl in field_tables:
        if bundle not in bundle_tables.get(tbl, []):
            continue

        # Find value and target columns
        cur.execute(f"SHOW COLUMNS FROM `{tbl}` WHERE Field LIKE '%_value'")
        value_cols = [r[0] for r in cur.fetchall()]
        cur.execute(f"SHOW COLUMNS FROM `{tbl}` WHERE Field LIKE '%_target_id'")
        target_cols = [r[0] for r in cur.fetchall()]
        cols = value_cols + target_cols

        if not cols:
            continue

        cur.execute(
            f"SELECT {', '.join(cols)} FROM `{tbl}` WHERE entity_id = %s AND revision_id = %s AND deleted = 0",
            (nid, vid),
        )
        rows = cur.fetchall()
        if not rows:
            continue

        field_name = tbl.replace("node__", "")
        data = []
        for row in rows:
            d = {}
            for col, val in zip(cols, row):
                clean = col.replace(f"{field_name}_", "")
                d[clean] = val
            data.append(d)
        fields[field_name] = data[0] if len(data) == 1 else data
    return fields


def _children(cur, nid: int) -> List[Dict[str, Any]]:
    """Find paragraph children of a node.

    Args:
        cur: Active database cursor.
        nid: Node ID.

    Returns:
        List of child paragraph metadata.
    """
    cur.execute("SHOW TABLES LIKE 'node__field_%'")
    candidate_tables = [
        t[0] for t in cur.fetchall()
        if any(keyword in t[0] for keyword in ["paragraph", "content", "block", "section", "component"])
    ]

    children = []
    for tbl in candidate_tables:
        field = tbl.replace("node__", "")
        cur.execute(f"SHOW COLUMNS FROM `{tbl}` LIKE %s", (f"{field}_target_id",))
        if not cur.fetchone():
            continue

        cur.execute(
            f"SELECT {field}_target_id, delta FROM `{tbl}` WHERE entity_id = %s AND deleted = 0 ORDER BY delta",
            (nid,),
        )
        for pid, delta in cur.fetchall():
            cur.execute("SELECT type FROM paragraphs_item WHERE id = %s", (pid,))
            ptype = cur.fetchone()
            if ptype:
                children.append({
                    "paragraph_id": pid,
                    "type": ptype[0],
                    "delta": delta,
                    "field": field
                })
    return children


def _parents(cur, nid: int) -> List[Dict[str, Any]]:
    """Find parent nodes that reference this paragraph.

    Args:
        cur: Active database cursor.
        nid: Paragraph ID.

    Returns:
        List of parent node metadata.
    """
    cur.execute("""
        SELECT DISTINCT pfd.parent_id, pfd.parent_type, pfd.parent_field_name
        FROM paragraphs_item_field_data pfd
        WHERE pfd.id = %s
    """, (nid,))
    parents = cur.fetchall()

    results = []
    for parent_id, parent_type, field_name in parents:
        if parent_type != "node":
            continue
        try:
            parent_nid = int(parent_id)
        except (ValueError, TypeError):
            continue

        cur.execute("""
            SELECT nfd.title
            FROM node_field_data nfd
            WHERE nfd.nid = %s AND nfd.langcode = 'en'
        """, (parent_nid,))
        title_row = cur.fetchone()
        if title_row:
            results.append({
                "nid": parent_nid,
                "title": title_row[0],
                "field": field_name
            })
    return results


def main() -> int:
    """Interactive entry point for drupal-export.py."""
    settings = _load_settings()

    db = settings.get("database") or input("Database name: ").strip()
    user = settings.get("user") or input("Username: ").strip()
    pwd = settings.get("password") or getpass.getpass("Password: ")

    if "password" not in settings:
        save_pwd = input("Save password? (y/n): ").strip().lower() in {"y", "yes"}
    else:
        save_pwd = True

    _save_settings(db, user, pwd if save_pwd else None)

    print("\nExporting...")
    export_nodes(db=db, user=user, password=pwd)
    print("\nDone.")
    return 0


__all__ = ["export_nodes", "main"]