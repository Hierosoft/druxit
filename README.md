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

### Creating an export target
This sections explains how a page (or other content type) might be reconstructed.

Process each node as follows.

If node['type'] is a type of page you want, process it. Otherwise, make it something else (such as an article or other type of content that may be stored separately in the target CMS).
If has parents, consider not processing it, and instead pulling it in as child content:
```json
      "parents": [
        {
          "nid": 1196,
          "title": "Bachmann Baldwin RF-16 Sharknose",
          "via": "entity_reference",
          "field": "field_installation_pictures"
        }
      ],
```
- Example: if node 1033 has many children, it may have been used in Drupal merely to pull in content. So in that case ensure each applicable page gets 1033 at the bottom before the child nodes.
  - The ordering of putting the parent last should be determined by the 'type' of the node. For example, if the parent is a "page" it is used to construct content, so it's own body can be placed after the children but before the grandchildren.

Process the "url" to determine the target page:
```
      "url": "/installation/ho-scale/1855"
```
- taxonomies may be useful for constructing a good path and/or name applicable to the target CMS as well.

Display the node['taxonomies'] first, since they are useful as headings:
```json
      "taxonomies": {
        "ho_scale": {
          "tid": 7,
          "revision_id": 7,
          "vid": "scale",
          "uuid": "c17654fb-f05b-4ac3-ae82-507343482ea1",
          "langcode": "en",
          "parent": [
            0
          ],
          "field_data": {
            "tid": 7,
            "revision_id": 7,
            "vid": "scale",
            "langcode": "en",
            "name": "HO Scale",
            "description__value": null,
            "description__format": null,
            "weight": 0,
            "changed": 1644534477,
            "default_langcode": 1,
            "status": 1,
            "revision_translation_affected": 1
          }
        },
        "bachmann": {
          "tid": 25,
          "revision_id": 25,
          "vid": "locomotive_brand",
          "uuid": "36223849-87de-45f1-ac7b-152fa305c8c0",
          "langcode": "en",
          "parent": [
            0
          ],
          "field_data": {
            "tid": 25,
            "revision_id": 25,
            "vid": "locomotive_brand",
            "langcode": "en",
            "name": "Bachmann",
            "description__value": null,
            "description__format": null,
            "weight": 35,
            "changed": 1644549298,
            "default_langcode": 1,
            "status": 1,
            "revision_translation_affected": 1
          }
        }
      },
```

Process each `field in node['fields']` (many may have only one entry) that matched the parent node. Example list entry:
```json
          {
            "target_id": 6176,
            "alt": "This installation is for a HO Scale Bachmann F7A using a TCS WOW121 Diesel Decoder, AK-MB1 Motherboard with built in Keep Alive\u00ae, motor mount and 28mm WOWSpeaker.Kit Coming Soon! We are in the process of assembling all the items shown here into a new WOWKit. Please check back here to see the new WOWKit when it arrives. Shown prior to installation. ",
            "title": "",
            "width": 3481,
            "height": 1275,
            "delta": 0,
            "file": {
              "fid": 6176,
              "uuid": "25671b82-2cff-4925-af55-45a5606fcd19",
              "langcode": "en",
              "uid": 98,
              "filename": "shell on.jpg",
              "uri": "public://2018-06/shell on_3.jpg",
              "filemime": "image/jpeg",
              "filesize": 750970,
              "status": 1,
              "created": 1528744690,
              "changed": 1528746477,
              "type": "image",
              "metadata": {
                "height": "b'i:1275;'",
                "width": "b'i:3481;'"
              },
              "user": {
                "uid": 98,
                "uuid": "37d5481c-20c7-4a5f-ad69-74ae3394c421",
                "langcode": "en",
                "roles": [
                  "administrator",
                  "electron_tool"
                ]
              }
            }
```

Process children last, since they are useful as footers:
```json
      "children": [
        {
          "nid": 2421,
          "title": "WDK-BAC-5",
          "type": "kit",
          "field": "field_kit"
        },
        {
          "nid": 25,
          "title": "Athearn RTR AC4400",
          "type": "installation",
          "field": "field_locomotive_brand"
        },
        {
          "nid": 941,
          "title": "Important Soldering Tip",
          "type": "product_notes",
          "field": "field_product_notes"
        },
        {
          "nid": 1033,
          "title": "Other solder tips",
          "type": "product_notes",
          "field": "field_product_notes"
        }
      ],
    },
```