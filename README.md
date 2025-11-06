# druxit
A comprehensive exit plan from Drupal ;)

Dynamic Drupal 9 content exporter for migrating to other CMS platforms.

## Features
- Zero-config field discovery
- Full support for Paragraphs, taxonomy, aliases
- Ready for WordPress, Hugo, or custom CMS

## Install
```bash
pip install -e .[dev]
```

### Avoid compiling mysql-connector-python
- Install the python mysql connector package from your distro repo such as:
```bash
sudo apt install python3-mysql.connector
```
- `python3 -m venv .venv`
- edit `.venv/pyvenv.cfg`'s `include-system-site-packages = false` line to:
```bash
include-system-site-packages = true
```

## Usage
### Interactive
```
python drupal-export.py
```

### Non-interactive (CI, scripts)
```
python -c "from druxit import export_nodes; export_nodes('mydb', 'root', 'secret')"
```

