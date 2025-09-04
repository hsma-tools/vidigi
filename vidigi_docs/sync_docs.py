import shutil
from pathlib import Path

root = Path(__file__).parent.parent
docs = root / "vidigi_docs"

files = {
    "LICENSE.md": "licence.qmd",
    "CODE_OF_CONDUCT.md": "code_of_conduct.qmd",
    "HISTORY.md": "changelog.qmd",
}

for src, dest in files.items():
    shutil.copy(root / src, docs / dest)

# YAML front matter to prepend
yaml_header = """---
format:
    html:
        toc: true
        toc-expand: 3
---

"""

# Files to prepend YAML to
for qmd_file in ["changelog.qmd"]:
    file_path = docs / qmd_file
    content = file_path.read_text(encoding="utf-8")
    file_path.write_text(yaml_header + content, encoding="utf-8")
