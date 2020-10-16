import html
import os
import re
import traceback
import urllib
from concurrent.futures import Future

import anki.importing as importing
import requests
from anki.httpclient import HttpClient
from anki.importing.csvfile import TextImporter
from anki.lang import _
from aqt import mw
from aqt.editor import pics
from aqt.importing import ImportDialog, showUnicodeWarning
from aqt.qt import *
from aqt.utils import TR, getFile, showInfo, showText, showWarning, tr


# fnameToLink and _retrieveURL are taken from aqt/editor.py with modifications
def fnameToLink(fname):
    ext = fname.split(".")[-1].lower()
    if ext in pics:
        # name = urllib.parse.quote(fname.encode("utf8"))
        return (
            '<img src=""%s"">' % fname
        )  # double quotes because imported fields are wrapped in quotes
    else:
        return "[sound:%s]" % html.escape(fname, quote=False)


def _retrieveURL(url: str):
    # url = urllib.parse.unquote(url)
    url = html.unescape(url)
    if url.lower().startswith("file://"):
        url = url.replace("%", "%25")
        url = url.replace("#", "%23")
        local = True
    else:
        local = False
    # fetch it into a temporary folder
    mw.progress.start(immediate=not local)
    content_type = None
    error_msg = None
    try:
        if local:
            req = urllib.request.Request(
                url, None, {"User-Agent": "Mozilla/5.0 (compatible; Anki)"}
            )
            with urllib.request.urlopen(req) as response:
                filecontents = response.read()
        else:
            with HttpClient() as client:
                client.timeout = 30
                # print(f"_retrieveURL(): url = '{url}'")
                with client.get(url) as response:
                    # print(f"_retrieveURL(): response.status_code = '{response.status_code}'")
                    if response.status_code != 200:
                        error_msg = (
                            _("Unexpected response code: %s") % response.status_code
                        )
                        return None
                    filecontents = response.content
                    content_type = response.headers.get("content-type")
    except (urllib.error.URLError, requests.exceptions.RequestException) as e:
        error_msg = _("An error occurred while opening %s") % e
        return None
    finally:
        mw.progress.finish()
        if error_msg:
            showWarning(error_msg)
    # strip off any query string
    fname = os.path.basename(urllib.parse.unquote(url))
    if not fname.strip():
        fname = "paste"
    if content_type:
        fname = mw.col.media.add_extension_based_on_mime(fname, content_type)

    return mw.col.media.write_data(fname, filecontents)


def transform_file(filename):
    def process_field(name, content):
        if name == "رابط تحميل الصورة":
            content = content.strip()
            try:
                fname = _retrieveURL(content)
                # print(f"fname = {fname}")
                if fname:
                    return fnameToLink(fname)
                else:
                    return content
            except Exception as e:
                # print(e)
                return content
        else:
            return content

    fields = [
        "العنوان",
        "النص",
        "اسم الصورة",
        "رابط تحميل الصورة",
        "التخصص",
        "العلم",
        "المؤلف",
        "الكتاب",
        "الطبعة",
        "الصفحة",
        "الباب",
        "تعليق",
        "تاريخ الإضافة الهجري",
        "تاريخ الإضافة الميلادي",
    ]

    newfile_path = os.path.join(
        os.path.abspath(os.path.dirname(__file__)), "__tmp__.txt"
    )
    with open(filename, encoding="utf-8") as file:
        outfile = open(newfile_path, "w", encoding="utf-8")
        lines = file.readlines()
        card = ""
        field = ""
        cur_fld = 0
        cur_src_fld_name = ""
        for ln, line in enumerate(lines):
            line = line.replace("\u200F", "").replace('"', '""')
            line = html.escape(line, quote=False)

            match = re.match("([^:]*)(:)?(.*)", line)
            delim = match[2]
            src_fld_name = match[1].strip()
            src_fld_content = match[3]

            if delim:
                n_field = "تدوينة رقم"
                if src_fld_name.startswith(n_field):

                    # last field of card
                    if card:
                        card += f'"{process_field(cur_src_fld_name, field)}"\t'
                    # if card has a number of fields less than the number of dawwen fields,
                    # make sure to take account of the missing fields anyway,
                    # so that we get the right mapping automatically
                    if card:
                        while cur_fld < len(fields):
                            card += '""\t'
                            cur_fld += 1
                    cur_fld = 0
                    field = ""
                    if card:
                        # replace last \t with \n and dump card
                        card = card[:-1] + "\n"
                        outfile.write(card)
                    card = ""

                    # first field of next card
                    idx = src_fld_name.index(n_field) + len(n_field) + 1
                    n = int(src_fld_name[idx:])
                    card = f'"{str(n)}"\t'
                    field = ""
                    cur_src_fld_name = src_fld_name
                elif src_fld_name in fields:
                    # got a new field
                    # write previous field first
                    if field:
                        card += f'"{process_field(cur_src_fld_name, field)}"\t'

                    # write missing fields in file
                    while cur_fld < fields.index(src_fld_name):
                        card += '""\t'
                        cur_fld += 1
                    cur_fld += 1

                    # write first line of new field content
                    field = f"{src_fld_content}\n"

                    cur_src_fld_name = src_fld_name
                else:
                    field += f"{line}\n"
            else:
                field += f"{line}\n"
        # ensure last card gets written
        if card:
            card += f'"{process_field(cur_src_fld_name, field)}"\t'
            card = card[:-1] + "\n"
            outfile.write(card)
        outfile.close()
    return newfile_path


def auto_import(importer, model, deck):

    deck["mid"] = model["id"]
    model["did"] = deck["id"]
    mw.col.decks.select(deck["id"])
    mw.col.models.setCurrent(model)
    importer.model = model

    importer.initMapping()
    importer.importMode = 0  # update mode
    importer.allowHTML = True
    mw.col.models.save(importer.model, updateReqs=False)

    mw.progress.start()
    mw.checkpoint(_("Import"))

    def on_done(future: Future):
        mw.progress.finish()
        try:
            future.result()
        except UnicodeDecodeError:
            showUnicodeWarning()
            return
        except Exception as e:
            msg = tr(TR.IMPORTING_FAILED_DEBUG_INFO) + "\n"
            err = repr(str(e))
            if "1-character string" in err:
                msg += err
            elif "invalidTempFolder" in err:
                msg += mw.errorHandler.tempFolderMsg()
            else:
                msg += traceback.format_exc()
            showText(msg)
            return
        else:
            txt = _("Importing complete.") + "\n"
            if importer.log:
                txt += "\n".join(importer.log)
            # fixme: the main window gets minimized when this dialog is closed
            showText(txt)
            mw.reset()
            return

    mw.taskman.run_in_background(importer.run, on_done)


def on_import():
    filt = ";;".join([x[0] for x in importing.Importers])
    file = getFile(mw, _("Import"), None, key="import", filter=filt)
    if not file:
        return
    file = str(file)

    head, ext = os.path.splitext(file)
    ext = ext.lower()
    if ext == ".anki":
        showInfo(
            _(
                ".anki files are from a very old version of Anki. You can import them with Anki 2.0, available on the Anki website."
            )
        )
        return
    elif ext == ".anki2":
        showInfo(
            _(
                ".anki2 files are not directly importable - please import the .apkg or .zip file you have received instead."
            )
        )
        return

    file = transform_file(file)

    importer = TextImporter(mw.col, file)
    mw.progress.start(immediate=True)
    try:
        importer.open()
        mw.progress.finish()

        model = mw.col.models.byName("dawwen")
        did = mw.col.decks.id("dawwen")
        if did and model:
            auto_import(importer, model, mw.col.decks.get(did))
        else:
            diag = ImportDialog(mw, importer)
    except UnicodeDecodeError:
        mw.progress.finish()
        showUnicodeWarning()
        return
    except Exception as e:
        mw.progress.finish()
        msg = repr(str(e))
        if msg == "'unknownFormat'":
            showWarning(_("Unknown file format."))
        else:
            msg = tr(TR.IMPORTING_FAILED_DEBUG_INFO) + "\n"
            msg += str(traceback.format_exc())
            showText(msg)
        return
    finally:
        importer.close()


def make_model():

    qfmt = """<div class="front alert">
{{العنوان}}
</div>"""

    afmt = """{{FrontSide}}

<div class="alert back">
{{النص}}
</div>
{{الصورة}}
{{#Extra}}
<div class="alert extra">
{{Extra}}
</div>
{{/Extra}}"""

    css = """.card {
    font-family: MyFont, sans-serif;
	font-size: 23px; /*هذا الرقم خاص بتغيير حجم الخط*/
	max-width: 620px;
	background-color: #fffff9;
	direction: rtl;
	margin: 5px auto;
	text-align: justify; /*لتوسيط النصوص غير الكلمة بعد النقطتين إلى center*/
	padding: 0 5px;
	line-height: 1.8em;
}

.card.nightMode { 
    background: #555;
    color:#eee;
}

.alert {
    position: relative;
    padding: 15px;
    margin-bottom:5px;
    border-radius: .25rem;
}

.front  {
    color: #004085;
    text-align: center;
background: #cce5ff;
}

.nightMode .front {
    background: #476d7c;
	color: #fff;
}

.back {
    color: #155724;
    background: #d4edda;
}

.nightMode .back {
	background: #254b62;
	color: #fff;
}

.extra {
    color: #856404;
    background: #fff3cd;
}

.nightMode .extra {
	background: #1d3e53;
	color: #fff;
}

@font-face {
	font-family: MyFont;
	font-weight: 500;
	src: url('_Sh_LoutsSh.ttf'); 
}

@font-face {
	font-family: MyFont;
	font-weight: 700;
	src: url('_Sh_LoutsShB.ttf'); 
}
/*Start of style added by resize image add-on. Don't edit directly or the edition will be lost. Edit via the add-on configuration */
.mobile .card img {height:unset  !important; width:unset  !important;}
/*End of style added by resize image add-on*/"""

    fields = [
        "رقم التدوينة",
        "العنوان",
        "النص",
        "اسم الصورة",
        "الصورة",
        "التخصص",
        "العلم",
        "المؤلف",
        "الكتاب",
        "الطبعة",
        "الصفحة",
        "الباب",
        "التعليق",
        "تاريخ الإضافة الهجري",
        "تاريخ الإضافة الميلادي",
    ]
    nt = mw.col.models.new("dawwen")
    mw.col.models.ensureNameUnique(nt)
    for fldname in fields:
        field = mw.col.models.new_field(fldname)
        field["rtl"] = True
        mw.col.models.add_field(nt, field)
    tmpl = mw.col.models.new_template("Card 1")
    tmpl["qfmt"] = qfmt
    tmpl["afmt"] = afmt
    nt["css"] = css
    mw.col.models.add_template(nt, tmpl)
    mw.col.models.add(nt)

    config = mw.addonManager.getConfig(__name__)
    config["first_run"] = 0
    mw.addonManager.writeConfig(__name__, config)

    showInfo(f"تم إنشاء نوع ملحوظة باسم ”{nt['name']}“")


def dawwen_menu():
    config = mw.addonManager.getConfig(__name__)
    if config["first_run"]:
        showInfo(
            "هذه المرة الأولى التي تستعمل فيها هذه الإضافة؛ سيتم إنشاء نوع ملحوظة جديد لاستيراد تدوينات تطبيق دوّن."
        )
        make_model()
    on_import()


import_action = QAction("استيراد", mw)
import_action.triggered.connect(dawwen_menu)
create_model_action = QAction("أنشئ نوع ملحوظة دوّن", mw)
create_model_action.triggered.connect(make_model)
mw.dawwen_submenu = QMenu("مستورد دوّن", mw)
mw.dawwen_submenu.addAction(import_action)
mw.dawwen_submenu.addAction(create_model_action)
mw.form.menuTools.addMenu(mw.dawwen_submenu)
