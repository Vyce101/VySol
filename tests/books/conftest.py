from io import BytesIO
from zipfile import ZipFile

import pytest


@pytest.fixture
def epub():
    def make(documents=None, spine=None, version="3.0", extra_manifest="", extra_files=None, guide=""):
        documents = documents if documents is not None else {
            "chapter": '<h1>Chapter One</h1><p>Hello <em>reader</em>.</p>',
        }
        spine = list(documents) if spine is None else spine
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            archive.writestr("mimetype", "application/epub+zip")
            archive.writestr("META-INF/container.xml", '''<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="EPUB/book.opf" media-type="application/oebps-package+xml"/></rootfiles></container>''')
            manifest = "".join(f'<item id="{key}" href="{key}.xhtml" media-type="application/xhtml+xml"'
                               + (' properties="nav"' if key == "nav" else "") + '/>' for key in documents)
            references = "".join(f'<itemref idref="{key}" linear="no"/>' for key in spine)
            archive.writestr("EPUB/book.opf", f'<package xmlns="http://www.idpf.org/2007/opf" version="{version}">'
                             f'<manifest>{manifest}{extra_manifest}</manifest><spine toc="ncx">{references}</spine>{guide}</package>')
            for key, body in documents.items():
                archive.writestr(f"EPUB/{key}.xhtml", f'<html><head><title>Hidden title</title></head><body>{body}</body></html>')
            for path, content in (extra_files or {}).items():
                archive.writestr(path, content)
        return output.getvalue()
    return make
