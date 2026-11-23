"""Configuration for the documentation build.

The reference is read off the package as text rather than imported, so the site
builds on a machine without Maya.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

project = "poseRBF"
author = "Luis de Campos"
copyright = "2026, Luis de Campos"
release = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]
version = release

extensions = [
    "myst_parser",
    "autoapi.extension",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx_design",  # the cards of the first page
]

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
root_doc = "index"
# The pages for development stay out of the site.
exclude_patterns = [
    "_build",
    "adr",
    "explanation/architecture.md",
    "how-to/run-the-checks.md",
]

autoapi_dirs = [str(ROOT / "poserbf")]
autoapi_root = "reference/api"
autoapi_options = ["members", "show-inheritance", "show-module-summary"]
autoapi_member_order = "bysource"
autoapi_python_class_content = "class"
autoapi_add_toctree_entry = False
autoapi_keep_files = False

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_use_ivar = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
}

# Maya's and Qt's modules are not on the machine that builds the site.
suppress_warnings = ["autoapi.python_import_resolution"]

html_theme = "furo"
html_title = f"{project} {release}"
html_logo = "../poserbf/poseRBF.svg"
html_favicon = "../poserbf/poseRBF.svg"
html_show_sphinx = False
html_copy_source = False
html_show_sourcelink = False
html_theme_options = {
    "source_repository": "https://github.com/ldecampos/poseRBF",
    "source_branch": "main",
    "source_directory": "docs/",
}
