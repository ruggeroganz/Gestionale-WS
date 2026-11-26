"""Lettura e compilazione del modulo di brief del produttore (file Word con campi modulo).

Il modello è un .docx fatto di tabelle con «controlli contenuto» (testo, casella di
spunta, menu a tendina, data) e qualche cella vuota da riempire a mano. Qui si
ricava l'elenco dei campi, con un'etichetta dedotta dal testo vicino, e si scrive
nel file solo ciò che è stato compilato: il resto del modello resta intatto.
"""
import copy
import io
import zipfile
from dataclasses import dataclass, field

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
NS = {"w": W, "w14": W14}
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENTO = "word/document.xml"
SPUNTATO, VUOTO = "☒", "☐"


class BriefError(Exception):
    pass


def _w(tag):
    return f"{{{W}}}{tag}"


def _w14(tag):
    return f"{{{W14}}}{tag}"


@dataclass
class Campo:
    chiave: str
    tipo: str  # testo, casella, menu, data, cella
    etichetta: str
    sezione: str = ""
    gruppo: str = ""
    opzioni: list = field(default_factory=list)
    valore: object = ""
    el: object = None


def _apri(dati):
    try:
        archivio = zipfile.ZipFile(io.BytesIO(dati))
        return archivio, etree.fromstring(archivio.read(DOCUMENTO))
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as e:
        raise BriefError("Il modello del brief non è un file Word (.docx) valido.") from e


def _antenato(el, tag, entro=None):
    for a in el.iterancestors():
        if a.tag == tag:
            return a
        if a is entro:
            return None
    return None


def _testo_proprio(el, controlli):
    """Testo dell'elemento escluso quello dentro i controlli."""
    paragrafi = []
    for p in el.iter(_w("p")):
        testo = "".join(t.text or "" for t in p.iter(_w("t")) if not any(a in controlli for a in t.iterancestors()))
        if testo.strip():
            paragrafi.append(" ".join(testo.split()))
    return " ".join(paragrafi)


def _celle(riga):
    return [c for c in riga.iter(_w("tc")) if _antenato(c, _w("tr")) is riga]


def _tipo(sdt):
    pr = sdt.find(_w("sdtPr"))
    if pr is None:
        return "testo"
    if pr.find("w14:checkbox", NS) is not None:
        return "casella"
    if pr.find("w:dropDownList", NS) is not None or pr.find("w:comboBox", NS) is not None:
        return "menu"
    if pr.find("w:date", NS) is not None:
        return "data"
    return "testo"


def _contenuto(sdt):
    c = sdt.find(_w("sdtContent"))
    return "".join(t.text or "" for t in c.iter(_w("t"))) if c is not None else ""


def analizza(dati):
    """Elenco dei campi compilabili del modello, in ordine di documento."""
    _, radice = _apri(dati)
    return _campi(radice)


def _campi(radice):
    controlli = {s for s in radice.iter(_w("sdt")) if s.find(".//w:sdtContent//w:sdt", NS) is None}
    tabelle = list(radice.iter(_w("tbl")))
    campi = []

    def contesto(cella, riga, tabella):
        celle = _celle(riga)
        # etichetta: le celle di solo testo subito prima, fermandosi al campo precedente
        vicine = []
        for c in reversed(celle[: celle.index(cella)] if cella in celle else []):
            testo = _testo_proprio(c, controlli)
            if not testo or any(s in controlli for s in c.iter(_w("sdt"))) or any(a in controlli for a in c.iterancestors()):
                break
            vicine.insert(0, testo)
        riga_etichetta = " · ".join(vicine)
        righe = [r for r in tabella.iter(_w("tr")) if _antenato(r, _w("tbl")) is tabella]
        sezione = ""
        if len(righe) > 1:
            prime = _celle(righe[0])
            testi = [_testo_proprio(c, controlli) for c in prime]
            if len([t for t in testi if t]) == 1 and not any(s in controlli for c in prime for s in c.iter(_w("sdt"))):
                sezione = next(t for t in testi if t)
        intestazione = ""
        if cella in celle and righe and riga is not righe[0]:
            prime = _celle(righe[0])
            i = celle.index(cella)
            if i < len(prime) and len(prime) == len(celle):
                intestazione = _testo_proprio(prime[i], controlli)
        return riga_etichetta, sezione, intestazione, righe.index(riga) if riga in righe else 0

    for el in radice.iter():
        if el in controlli:
            tipo = _tipo(el)
            # il controllo può stare dentro una cella oppure contenerla (controllo «di cella»)
            cella = _antenato(el, _w("tc"))
            if cella is None:
                cella = el.find(".//w:tc", NS)
            riga = _antenato(cella, _w("tr")) if cella is not None else None
            tabella = _antenato(riga, _w("tbl")) if riga is not None else None
            prima = dopo = riga_etichetta = sezione = intestazione = ""
            n_riga = 0
            if tabella is not None:
                riga_etichetta, sezione, intestazione, n_riga = contesto(cella, riga, tabella)
                if _antenato(el, _w("tc")) is not None:  # testo accanto al controllo, nella stessa cella
                    sequenza = []
                    for x in cella.iter():
                        if x in controlli:
                            sequenza.append(x)
                        elif x.tag == _w("t") and not any(a in controlli for a in x.iterancestors()):
                            sequenza.append(x.text or "")
                    k = next(i for i, x in enumerate(sequenza) if x is el)
                    j = k + 1
                    while j < len(sequenza) and isinstance(sequenza[j], str):
                        dopo += sequenza[j]
                        j += 1
                    j = k - 1
                    while j >= 0 and isinstance(sequenza[j], str):
                        prima = sequenza[j] + prima
                        j -= 1
            prima, dopo = prima.strip(), dopo.strip()
            pr = el.find(_w("sdtPr"))
            segnaposto = pr is not None and pr.find(_w("showingPlcHdr")) is not None
            campo = Campo(chiave="", tipo=tipo, etichetta="", sezione=sezione, el=el)
            if tipo == "casella":
                campo.etichetta = dopo or prima or "Sì"
                campo.gruppo = riga_etichetta or sezione
                campo.valore = _contenuto(el).strip() == SPUNTATO
            else:
                alias = pr.find(_w("alias")) if pr is not None else None
                campo.etichetta = prima or (alias.get(_w("val")) if alias is not None else "") or riga_etichetta
                campo._intestazione = intestazione
                campo._riga = n_riga
                campo._tabella = tabelle.index(tabella) if tabella is not None else -1
                campo.valore = "" if segnaposto else _contenuto(el).strip()
                if tipo == "menu":
                    voci = [i.get(_w("displayText")) or i.get(_w("value")) or "" for i in pr.iter(_w("listItem"))]
                    campo.opzioni = [v for v in voci if v.strip() and not v.lower().startswith(("scegliere", "choose"))]
            campi.append(campo)
        elif el.tag == _w("tc"):
            # cella vuota accanto a un'etichetta: si compila scrivendoci direttamente
            riga = _antenato(el, _w("tr"))
            tabella = _antenato(riga, _w("tbl")) if riga is not None else None
            if tabella is None or any(a in controlli for a in el.iterancestors()):
                continue
            if any(True for _ in el.iter(_w("sdt"))) or "".join(t.text or "" for t in el.iter(_w("t"))).strip():
                continue
            if el.find("w:tcPr/w:vMerge", NS) is not None:
                continue
            celle = _celle(riga)
            i = celle.index(el)
            if i == 0 or not _testo_proprio(celle[i - 1], controlli) or any(True for _ in celle[i - 1].iter(_w("sdt"))):
                continue
            riga_etichetta, sezione, _, _ = contesto(el, riga, tabella)
            campi.append(Campo(chiave="", tipo="cella", etichetta=riga_etichetta, sezione=sezione, el=el))

    # righe «menu + nota» affiancate a un elenco di caselle (es. i test): prendono il nome della casella
    per_tabella = {}
    for c in campi:
        if c.tipo not in ("casella", "cella") and not c.etichetta:
            per_tabella.setdefault(getattr(c, "_tabella", -1), []).append(c)
    for n_tabella, senza in per_tabella.items():
        if n_tabella < 0:
            continue
        caselle = [c.etichetta for c in campi if c.tipo == "casella" and _antenato(c.el, _w("tbl")) is tabelle[n_tabella]]
        righe = sorted({c._riga for c in senza})
        for c in senza:
            k = righe.index(c._riga)
            intestazione = getattr(c, "_intestazione", "")
            if k < len(caselle) and len(righe) == len(caselle):
                c.etichetta = " · ".join(x for x in (caselle[k], intestazione) if x)
            else:
                c.etichetta = intestazione
    for n, c in enumerate(campi):
        c.chiave = f"c{n}"
        if not c.etichetta:
            c.etichetta = f"Campo {n + 1}"
    return campi


def _paragrafo(el):
    contenuto = el.find(_w("sdtContent")) if el.tag == _w("sdt") else el
    p = contenuto.find(".//" + _w("p")) if contenuto is not None else None
    return contenuto, p


def _scrivi_testo(el, testo):
    """Sostituisce il contenuto del controllo (o della cella) con il testo, tenendo il formato del primo tratto."""
    contenuto, p = _paragrafo(el)
    if contenuto is None:
        return
    if el.tag == _w("sdt"):
        pr = el.find(_w("sdtPr"))
        for segnaposto in pr.findall(_w("showingPlcHdr")):
            pr.remove(segnaposto)
    tratti_in = p if p is not None else contenuto
    modello = tratti_in.find(_w("r"))
    formato = copy.deepcopy(modello.find(_w("rPr"))) if modello is not None and modello.find(_w("rPr")) is not None else None
    if formato is not None:
        for stile in formato.findall(_w("rStyle")):  # toglie lo stile grigio del testo segnaposto
            formato.remove(stile)
    for figlio in list(tratti_in):
        if figlio.tag in (_w("r"), _w("hyperlink"), _w("proofErr")):
            tratti_in.remove(figlio)
    if p is not None:  # eventuali paragrafi successivi del segnaposto
        for altro in list(contenuto.iter(_w("p")))[1:]:
            if not any(True for _ in altro.iter(_w("sdt"))) and altro.getparent() is p.getparent():
                altro.getparent().remove(altro)
    tratto = etree.SubElement(tratti_in, _w("r"))
    if formato is not None:
        tratto.append(formato)
    for n, linea in enumerate(str(testo).replace("\r\n", "\n").split("\n")):
        if n:
            etree.SubElement(tratto, _w("br"))
        t = etree.SubElement(tratto, _w("t"))
        t.text = linea
        t.set(XML_SPACE, "preserve")


def _spunta(el, attiva):
    stato = el.find("w:sdtPr/w14:checkbox/w14:checked", NS)
    if stato is not None:
        stato.set(_w14("val"), "1" if attiva else "0")
    for t in el.find(_w("sdtContent")).iter(_w("t")):
        t.text = SPUNTATO if attiva else VUOTO
        break


def compila(dati, valori):
    """Restituisce il .docx con i valori indicati ({chiave: valore}); i campi non indicati restano come nel modello."""
    archivio, radice = _apri(dati)
    for campo in _campi(radice):
        if campo.chiave not in valori:
            continue
        valore = valori[campo.chiave]
        if campo.tipo == "casella":
            if valore:
                _spunta(campo.el, True)
        elif str(valore).strip():
            if campo.tipo == "data":
                data = campo.el.find("w:sdtPr/w:date", NS)
                if data is not None and _w("fullDate") in data.attrib:
                    del data.attrib[_w("fullDate")]
            _scrivi_testo(campo.el, str(valore).strip())
    uscita = io.BytesIO()
    with zipfile.ZipFile(uscita, "w", zipfile.ZIP_DEFLATED) as nuovo:
        for voce in archivio.infolist():
            contenuto = archivio.read(voce.filename)
            if voce.filename == DOCUMENTO:
                contenuto = etree.tostring(radice, xml_declaration=True, encoding="UTF-8", standalone=True)
            nuovo.writestr(voce, contenuto)
    return uscita.getvalue()


def svuota(dati):
    """Riporta un brief già compilato allo stato di modello: testi vuoti, caselle non spuntate."""
    archivio, radice = _apri(dati)
    valori_vuoti = False
    for campo in _campi(radice):
        if campo.tipo == "casella":
            _spunta(campo.el, False)
        elif campo.tipo != "cella" and campo.valore:
            _scrivi_testo(campo.el, " ")
            valori_vuoti = True
    uscita = io.BytesIO()
    with zipfile.ZipFile(uscita, "w", zipfile.ZIP_DEFLATED) as nuovo:
        for voce in archivio.infolist():
            contenuto = archivio.read(voce.filename)
            if voce.filename == DOCUMENTO:
                contenuto = etree.tostring(radice, xml_declaration=True, encoding="UTF-8", standalone=True)
            nuovo.writestr(voce, contenuto)
    return uscita.getvalue()


def sezioni(campi):
    """Raggruppa i campi per sezione del modulo, e le caselle consecutive dello stesso gruppo."""
    out = []
    for c in campi:
        nome = c.sezione
        if not out or out[-1]["nome"] != nome:
            out.append({"nome": nome, "voci": []})
        voci = out[-1]["voci"]
        if c.tipo == "casella":
            if voci and voci[-1]["tipo"] == "caselle" and voci[-1]["gruppo"] == c.gruppo:
                voci[-1]["caselle"].append(c)
            else:
                voci.append({"tipo": "caselle", "gruppo": c.gruppo, "caselle": [c]})
        else:
            voci.append({"tipo": "campo", "campo": c})
    return out


# --------------------------------------------------------------------------
# Modello dimostrativo (per i dati demo e i test): stessi tipi di campo di un modulo reale
# --------------------------------------------------------------------------
def modello_dimostrativo():
    segnaposto = "Fare clic o toccare qui per immettere il testo."

    def cella(xml, extra=""):
        return f"<w:tc><w:tcPr>{extra}</w:tcPr>{xml}</w:tc>"

    def testo(t):
        return f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>"

    def controllo(pr, contenuto, vuoto=True):
        return (
            f"<w:sdt><w:sdtPr>{pr}{'<w:showingPlcHdr/>' if vuoto else ''}</w:sdtPr>"
            f"<w:sdtContent>{contenuto}</w:sdtContent></w:sdt>"
        )

    def campo_testo():
        return cella(controllo("<w:text/>", f'<w:p><w:r><w:rPr><w:rStyle w:val="Testosegnaposto"/></w:rPr><w:t>{segnaposto}</w:t></w:r></w:p>'))

    def campo_data():
        return cella(controllo('<w:date><w:dateFormat w:val="dd/MM/yyyy"/></w:date>', testo("Fare clic per immettere una data.")))

    def menu(opzioni):
        voci = '<w:listItem w:value="Scegliere un elemento."/>' + "".join(f'<w:listItem w:displayText="{o}" w:value="{o}"/>' for o in opzioni)
        return cella(controllo(f"<w:dropDownList>{voci}</w:dropDownList>", testo("Scegliere un elemento.")))

    def caselle(nomi, extra=""):
        tratti = "".join(
            controllo('<w14:checkbox><w14:checked w14:val="0"/></w14:checkbox>', f"<w:r><w:t>{VUOTO}</w:t></w:r>", vuoto=False)
            + f'<w:r><w:t xml:space="preserve"> {n} </w:t></w:r>'
            for n in nomi
        )
        return cella(f"<w:p>{tratti}</w:p>", extra)

    def tabella(*righe):
        return "<w:tbl>" + "".join(f"<w:tr>{''.join(r)}</w:tr>" for r in righe) + "</w:tbl><w:p/>"

    e = lambda t: cella(testo(t))  # noqa: E731
    corpo = (
        testo("CUSTOMER BRIEF")
        + tabella([e("KAM"), menu(["ROSSI", "BIANCHI"]), e("DATE"), campo_data()])
        + tabella([e("CUSTOMER"), campo_testo()])
        + tabella([e("IF NEW")], [e("DESCRIPTION"), campo_testo()], [e("PROJECT NAME"), campo_testo()])
        + tabella([e("LAUNCH DATE"), campo_data(), e("TARGET PRICE*"), cella("<w:p/>")])
        + tabella([e("MARKET"), campo_testo(), e("MOQ"), campo_testo()])
        + tabella([e("SECONDARY PACK"), caselle(["LEAFLET", "LABEL", "FOLDING BOX"])])
        + tabella(
            [e("TEST"), e("BF/Customer"), e("NOTE")],
            [caselle(["STABILITY TEST", "PATCH TEST"], '<w:vMerge w:val="restart"/>'), menu(["PRODUTTORE", "CLIENTE"]), campo_testo()],
            [cella("<w:p/>", "<w:vMerge/>"), menu(["PRODUTTORE", "CLIENTE"]), campo_testo()],
        )
    )
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:w14="{W14}"><w:body>{corpo}<w:sectPr/></w:body></w:document>'
    )
    tipi = (
        '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    )
    relazioni = (
        '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    )
    uscita = io.BytesIO()
    with zipfile.ZipFile(uscita, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", tipi)
        z.writestr("_rels/.rels", relazioni)
        z.writestr(DOCUMENTO, documento)
    return uscita.getvalue()
