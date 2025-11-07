# druxit/__init__.py
"""Druxit – complete Drupal 9 state exporter.

Collects full node metadata, users, taxonomy, files, and relationships
using only documented Drupal 9 table structures.
"""

__version__ = "0.1.0"

import json
import os
import getpass
from typing import Dict, List, Any, Optional
import mysql.connector
from logging import getLogger


SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "..", "settings.json")


if __name__ == "__main__":
    logger = getLogger(os.path.split(__file__)[1])
else:
    logger = getLogger(__name__)


class DrupalState:
    """Complete in-memory state of a Drupal 9 site for export."""

    def __init__(self, db: str, user: str, password: str, host: str = "localhost"):
        """Initialize and populate all tables.

        Args:
            db: Database name.
            user: Database username.
            password: Database password.
            host: MySQL host.
        """
        self.conn = mysql.connector.connect(
            host=host, database=db, user=user, password=password
        )
        self.cur = self.conn.cursor(dictionary=True)

        # Core collections
        self.users: Dict[int, Dict[str, Any]] = {}
        self.users_data: Dict[int, Dict[str, Any]] = {}
        self.users_field_data: Dict[int, Dict[str, Any]] = {}
        self.taxonomies: Dict[int, Dict[str, Any]] = {}
        self.files: Dict[int, Dict[str, Any]] = {}
        self.path_alias: Dict[str, Dict[str, Any]] = {}
        self.nodes: Dict[int, Dict[str, Any]] = {}

        self._load_users()
        self._load_taxonomies()
        self._load_files()
        self._load_path_alias()
        self._load_nodes()

        self.cur.close()
        self.conn.close()

    # --------------------------------------------------------------------- #
    # User tables (hard-coded)
    # --------------------------------------------------------------------- #
    def _load_users(self) -> None:
        """Load users, users_data, users_field_data, and user__roles."""
        self.cur.execute("SELECT * FROM users")
        for row in self.cur.fetchall():
            uid = row["uid"]
            self.users[uid] = row
            self.users[uid]["roles"] = []

        self.cur.execute("SELECT * FROM users_data")
        for row in self.cur.fetchall():
            uid = row["uid"]
            if uid not in self.users_data:
                self.users_data[uid] = {}
            self.users_data[uid][row["name"]] = row

        self.cur.execute("SELECT * FROM users_field_data")
        for row in self.cur.fetchall():
            uid = row["uid"]
            self.users_field_data[uid] = row

        # user__roles
        self.cur.execute("SHOW TABLES LIKE 'user__roles'")
        if self.cur.fetchone():
            self.cur.execute("SELECT * FROM user__roles WHERE deleted = 0")
            for row in self.cur.fetchall():
                uid = row["entity_id"]
                if uid in self.users:
                    self.users[uid]["roles"].append(row["roles_target_id"])

    # --------------------------------------------------------------------- #
    # Taxonomy
    # --------------------------------------------------------------------- #
    def _load_taxonomies(self) -> None:
        """Load taxonomy_term_data + parent + field_data."""
        self.cur.execute("SELECT * FROM taxonomy_term_data")
        for row in self.cur.fetchall():
            tid = row["tid"]
            self.taxonomies[tid] = row

        # parent
        self.cur.execute("SHOW TABLES LIKE 'taxonomy_term__parent'")
        if self.cur.fetchone():
            self.cur.execute(
                "SELECT entity_id, parent_target_id FROM taxonomy_term__parent WHERE deleted = 0"
            )
            for row in self.cur.fetchall():
                tid = row["entity_id"]
                if tid in self.taxonomies:
                    self.taxonomies[tid]["parent"] = row["parent_target_id"]

        # field_data
        self.cur.execute("SELECT * FROM taxonomy_term_field_data")
        for row in self.cur.fetchall():
            tid = row["tid"]
            if tid in self.taxonomies:
                self.taxonomies[tid]["field_data"] = row

    # --------------------------------------------------------------------- #
    # Files
    # --------------------------------------------------------------------- #
    def _load_files(self) -> None:
        """Load file_managed and file_metadata."""
        self.cur.execute("SELECT * FROM file_managed")
        for row in self.cur.fetchall():
            fid = row["fid"]
            self.files[fid] = row

        self.cur.execute("SHOW TABLES LIKE 'file_metadata'")
        if self.cur.fetchone():
            self.cur.execute("SELECT * FROM file_metadata")
            for row in self.cur.fetchall():
                fid = row["fid"]
                if fid in self.files:
                    if "metadata" not in self.files[fid]:
                        self.files[fid]["metadata"] = {}
                    self.files[fid]["metadata"][row["name"]] = row["value"]

    # --------------------------------------------------------------------- #
    # Path alias
    # --------------------------------------------------------------------- #
    def _load_path_alias(self) -> None:
        """Load all path aliases."""
        self.cur.execute("SELECT * FROM path_alias")
        for row in self.cur.fetchall():
            self.path_alias[row["alias"]] = row

    # --------------------------------------------------------------------- #
    # Nodes
    # --------------------------------------------------------------------- #
    def _load_nodes(self) -> None:
        """Load all nodes with full field data."""
        # Base node + field_data
        self.cur.execute("""
            SELECT n.*, nfd.*
            FROM node n
            JOIN node_field_data nfd ON n.nid = nfd.nid AND n.vid = nfd.vid
            WHERE n.type IN ('page', 'article', 'installation', 'kit') AND nfd.status = 1
            ORDER BY n.type, nfd.title
        """)
        for row in self.cur.fetchall():
            nid = row["nid"]
            meta = {
                "nid": nid,
                "vid": row["vid"],
                "type": row["type"],
                "uuid": row["uuid"],
                "langcode": row["langcode"],
                "data": {k: v for k, v in row.items() if k in [
                    "title", "uid", "status", "created", "changed"
                ]},
                "fields": {},
                "taxonomies": {},
                "children": [],
                "parents": [],
            }
            self.nodes[nid] = meta

        # Custom fields
        self.cur.execute("SHOW TABLES LIKE 'node__field_%'")
        field_tables_result = self.cur.fetchall()
        field_tables = [list(row.values())[0] for row in field_tables_result]

        for tbl in field_tables:
            print(f"\n\ntbl: {tbl}")
            field_name = tbl.replace("node__", "")
            self.cur.execute(f"SHOW COLUMNS FROM `{tbl}`")
            cols = [c["Field"] for c in self.cur.fetchall()]

            self.cur.execute(f"SELECT * FROM `{tbl}` WHERE deleted = 0")
            for row in self.cur.fetchall():
                nid = row["entity_id"]
                if nid not in self.nodes:
                    logger.warning(f"No parent node nid={nid} for {row}")
                    continue

                if field_name not in self.nodes[nid]["fields"]:
                    self.nodes[nid]["fields"][field_name] = []

                field_row = {}
                for col in cols:
                    if col.startswith(f"{field_name}_"):
                        clean_key = col.replace(f"{field_name}_", "")
                        field_row[clean_key] = row[col]
                field_row["delta"] = row["delta"]

                # Link file: field_name_target_id -> file_managed.fid
                if "target_id" in field_row:
                    fid = field_row["target_id"]
                    if fid in self.files:
                        field_row["file"] = self.files[fid]
                        file_uid = field_row["file"]["uid"]
                        print(f'field_row["file"]["uid"] = {file_uid}')
                        if file_uid in self.users:
                            field_row["file"]["user"] = self.users[file_uid]
                        else:
                            logger.warning(f"File uid={file_uid} not found in users")

                self.nodes[nid]["fields"][field_name].append(field_row)

        # Taxonomy index
        self.cur.execute("SELECT * FROM taxonomy_index")
        for row in self.cur.fetchall():
            nid = row["nid"]
            tid = row["tid"]
            if nid in self.nodes and tid in self.taxonomies:
                term = self.taxonomies[tid]
                name = term["field_data"]["name"] if "field_data" in term else str(tid)
                self.nodes[nid]["taxonomies"][name.lower().replace(" ", "_")] = term

        # URL alias
        for nid, meta in self.nodes.items():
            path = f"/node/{nid}"
            for alias, row in self.path_alias.items():
                if row["path"] == path:
                    meta["url"] = alias
                    break
            else:
                meta["url"] = path

        # Children & parents
        for nid, meta in self.nodes.items():
            # Children: any field referencing another node
            for field_name, items in meta["fields"].items():
                for item in items:
                    if "target_id" in item:
                        target_id = item["target_id"]
                        if target_id in self.nodes:
                            self.nodes[target_id]["parents"].append({
                                "nid": nid,
                                "title": meta["data"]["title"],
                                "via": "entity_reference",
                                "field": field_name
                            })
                            meta["children"].append({
                                "nid": target_id,
                                "title": self.nodes[target_id]["data"]["title"],
                                "type": self.nodes[target_id]["type"],
                                "field": field_name
                            })

    def export_json(self, path: str) -> None:
        """Export full state to JSON."""
        data = {
            "users": self.users,
            "users_data": self.users_data,
            "users_field_data": self.users_field_data,
            "taxonomies": self.taxonomies,
            "files": self.files,
            "path_alias": self.path_alias,
            "nodes": self.nodes,
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)


def export_nodes(db: str, user: str, password: str, host: str = "localhost") -> List[Dict[str, Any]]:
    """Export nodes with full state.

    Args:
        db: Database name.
        user: Database username.
        password: Database password.
        host: MySQL host.

    Returns:
        List of node metadata.
    """
    state = DrupalState(db, user, password, host)
    state.export_json("drupal_export.json")
    return list(state.nodes.values())


def main() -> int:
    """Interactive entry point."""
    settings = {}
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            settings = json.load(f)

    db = settings.get("database") or input("Database name: ").strip()
    user = settings.get("user") or input("Username: ").strip()
    pwd = settings.get("password") or getpass.getpass("Password: ")

    if "password" not in settings:
        save_pwd = input("Save password? (y/n): ").strip().lower() in {"y", "yes"}
    else:
        save_pwd = True

    data = {"database": db, "user": user}
    if save_pwd:
        data["password"] = pwd
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print("\nExporting...")
    export_nodes(db=db, user=user, password=pwd)
    print("\nDone. See drupal_export.json")
    return 0


__all__ = ["DrupalState", "export_nodes", "main"]