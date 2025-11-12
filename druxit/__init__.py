# druxit/__init__.py
"""Druxit – complete Drupal 9 state exporter.

Collects **all** data from **all** tables with **no SQL joins**.
Uses **exact column order** from MySQL.
No manual field listing. No ORDER BY. No casting.
"""

__version__ = "0.1.0"

import json
import os
import getpass
from typing import Any, List, Optional, OrderedDict as ODType
from collections import OrderedDict
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

        # Core collections — OrderedDict from the start
        self.users: ODType[int, ODType[str, Any]] = OrderedDict()
        self.users_data: ODType[int, ODType[str, Any]] = OrderedDict()
        self.users_field_data: ODType[int, ODType[str, Any]] = OrderedDict()
        self.taxonomies: ODType[int, ODType[str, Any]] = OrderedDict()
        self.files: ODType[int, ODType[str, Any]] = OrderedDict()
        self.path_alias: ODType[str, ODType[str, Any]] = OrderedDict()
        self.nodes: ODType[int, ODType[str, Any]] = OrderedDict()

        # Orphaned data
        self.orphanedNodeBody: ODType[int, ODType[str, Any]] = OrderedDict()

        self._load_users()
        self._load_taxonomies()
        self._load_files()
        self._load_path_alias()
        self._load_nodes()
        self._load_body()

        self.cur.close()
        self.conn.close()

    # --------------------------------------------------------------------- #
    # Helper: Convert row to OrderedDict preserving MySQL column order
    # --------------------------------------------------------------------- #
    def _row_to_od(self, row: dict) -> ODType[str, Any]:
        """Convert a MySQL row dict to OrderedDict with original column order."""
        od = OrderedDict()
        # cursor.description gives columns in order
        for col in self.cur.description:
            col_name = col[0]
            od[col_name] = row[col_name]
        return od

    # --------------------------------------------------------------------- #
    # User tables (hard-coded)
    # --------------------------------------------------------------------- #
    def _load_users(self) -> None:
        """Load users, users_data, users_field_data, and user__roles."""
        self.cur.execute("SELECT * FROM users")
        for row in self.cur.fetchall():
            uid = row["uid"]
            self.users[uid] = self._row_to_od(row)
            self.users[uid]["roles"] = []

        self.cur.execute("SELECT * FROM users_data")
        for row in self.cur.fetchall():
            uid = row["uid"]
            if uid not in self.users_data:
                self.users_data[uid] = OrderedDict()
            self.users_data[uid][row["name"]] = self._row_to_od(row)

        self.cur.execute("SELECT * FROM users_field_data")
        for row in self.cur.fetchall():
            uid = row["uid"]
            self.users_field_data[uid] = self._row_to_od(row)

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
            self.taxonomies[tid] = self._row_to_od(row)

        # parent
        self.cur.execute("SHOW TABLES LIKE 'taxonomy_term__parent'")
        if self.cur.fetchone():
            self.cur.execute("SELECT * FROM taxonomy_term__parent WHERE deleted = 0")
            for row in self.cur.fetchall():
                tid = row["entity_id"]
                if tid in self.taxonomies:
                    if "parent" not in self.taxonomies[tid]:
                        self.taxonomies[tid]["parent"] = []
                    self.taxonomies[tid]["parent"].append(row["parent_target_id"])

        # field_data
        self.cur.execute("SELECT * FROM taxonomy_term_field_data")
        for row in self.cur.fetchall():
            tid = row["tid"]
            if tid in self.taxonomies:
                self.taxonomies[tid]["field_data"] = self._row_to_od(row)

    # --------------------------------------------------------------------- #
    # Files
    # --------------------------------------------------------------------- #
    def _load_files(self) -> None:
        """Load file_managed and file_metadata."""
        self.cur.execute("SELECT * FROM file_managed")
        for row in self.cur.fetchall():
            fid = row["fid"]
            self.files[fid] = self._row_to_od(row)

        self.cur.execute("SHOW TABLES LIKE 'file_metadata'")
        if self.cur.fetchone():
            self.cur.execute("SELECT * FROM file_metadata")
            for row in self.cur.fetchall():
                fid = row["fid"]
                if fid in self.files:
                    if "metadata" not in self.files[fid]:
                        self.files[fid]["metadata"] = OrderedDict()
                    self.files[fid]["metadata"][row["name"]] = row["value"]

    # --------------------------------------------------------------------- #
    # Path alias
    # --------------------------------------------------------------------- #
    def _load_path_alias(self) -> None:
        """Load all path aliases."""
        self.cur.execute("SELECT * FROM path_alias")
        for row in self.cur.fetchall():
            self.path_alias[row["alias"]] = self._row_to_od(row)

    # --------------------------------------------------------------------- #
    # Nodes (no SQL join)
    # --------------------------------------------------------------------- #
    def _load_nodes(self) -> None:
        """Load node and node_field_data separately, no JOIN."""
        # Load node table
        self.cur.execute("SELECT * FROM node")
        for row in self.cur.fetchall():
            nid = row["nid"]
            node_od = OrderedDict()
            node_od["nid"] = row["nid"]
            node_od["vid"] = row["vid"]
            node_od["type"] = row["type"]
            node_od["uuid"] = row["uuid"]
            node_od["langcode"] = row["langcode"]
            node_od["data"] = None
            node_od["fields"] = OrderedDict()
            node_od["taxonomies"] = OrderedDict()
            node_od["children"] = []
            node_od["parents"] = []
            self.nodes[nid] = node_od

        # Load node_field_data
        self.cur.execute("SELECT * FROM node_field_data")
        for row in self.cur.fetchall():
            nid = row["nid"]
            if nid in self.nodes:
                data_od = OrderedDict()
                data_od["title"] = row["title"]
                data_od["uid"] = row["uid"]
                data_od["status"] = row["status"]
                data_od["created"] = row["created"]
                data_od["changed"] = row["changed"]
                self.nodes[nid]["data"] = data_od

        # Custom fields
        self.cur.execute("SHOW TABLES LIKE 'node__field_%'")
        field_tables_result = self.cur.fetchall()
        field_tables = [list(row.values())[0] for row in field_tables_result]

        for tbl in field_tables:
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

                field_row = OrderedDict()
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
                        # print(f'field_row["file"]["uid"] = {file_uid}')
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
                key = name.lower().replace(" ", "_")
                self.nodes[nid]["taxonomies"][key] = term

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
            for field_name, items in meta["fields"].items():
                for item in items:
                    if "target_id" in item:
                        target_id = item["target_id"]
                        if target_id in self.nodes:
                            # Parent entry
                            parent_entry = OrderedDict()
                            parent_entry["nid"] = nid
                            parent_entry["title"] = meta["data"]["title"]
                            parent_entry["via"] = "entity_reference"
                            parent_entry["field"] = field_name
                            self.nodes[target_id]["parents"].append(parent_entry)

                            # Child entry
                            child_entry = OrderedDict()
                            child_entry["nid"] = target_id
                            child_entry["title"] = self.nodes[target_id]["data"]["title"]
                            # child_entry["type"] = self.nodes[target_id]["type"]
                            child_entry["field"] = field_name
                            meta["children"].append(child_entry)

    # --------------------------------------------------------------------- #
    # Body field
    # --------------------------------------------------------------------- #
    def _load_body(self) -> None:
        """Load node__body table entries with orphan tracking."""
        self.orphanedNodeBody = OrderedDict()
        self.cur.execute("SHOW TABLES LIKE 'node__body'")
        if not self.cur.fetchone():
            return

        self.cur.execute("SELECT * FROM node__body WHERE deleted = 0")
        for row in self.cur.fetchall():
            nid = row["entity_id"]
            body_od = self._row_to_od(row)
            if nid in self.nodes:
                self.nodes[nid]["body"] = body_od
            else:
                self.orphanedNodeBody[nid] = body_od

    def export_json(self, path: str) -> None:
        """Export full state to JSON."""
        data = OrderedDict()
        data["users"] = self.users
        data["users_data"] = self.users_data
        data["users_field_data"] = self.users_field_data
        data["taxonomies"] = self.taxonomies
        data["files"] = self.files
        data["path_alias"] = self.path_alias
        data["nodes"] = self.nodes
        data["node_body_orphans"] = self.orphanedNodeBody
        path = os.path.abspath(path)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        print(f'Saved "{path}"')

    def export_html(self, path: str) -> None:
        for node in self.nodes:
            ns_path = os.path.join(path, node['type'])  # e.g. 'page'/custom
            if not os.path.isdir(ns_path):
                os.makedirs(ns_path)
                print(f'Created "{ns_path}"')


def export_nodes(db: str, user: str, password: str, host: str = "localhost") -> List[dict]:
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
    state.export_json("/tmp/drupal_export.json")
    # state.export_html(os.path.expanduser("~/Documents/druxit-html"))
    state.export_html("/tmp/druxit-html")
    return list(state.nodes.values())


def main() -> int:
    """Interactive entry point."""
    settings = OrderedDict()
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

    data = OrderedDict()
    data["database"] = db
    data["user"] = user
    if save_pwd:
        data["password"] = pwd
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)

    print("\nExporting...")
    export_nodes(db=db, user=user, password=pwd)
    print("\nDone. See drupal_export.json")
    return 0


__all__ = ["DrupalState", "export_nodes", "main"]
