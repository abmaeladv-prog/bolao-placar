# -*- coding: utf-8 -*-
"""
Backup automatico do Bolao Copa 2026
-------------------------------------
Le tudo do Firebase (meta, jogos, participantes, comprovantes) e salva um
arquivo JSON no MESMO formato do "Exportar backup" do app - ou seja, da para
RE-IMPORTAR direto em Jogos -> Configuracoes -> Importar backup.

- Nao precisa instalar nada (so a biblioteca padrao do Python 3).
- Guarda os ultimos N backups na pasta 'backups' (apaga os mais antigos).

Uso:
    python backup_bolao.py                 # backup completo (com comprovantes)
    python backup_bolao.py --no-receipts   # backup leve (sem as imagens)
    python backup_bolao.py --keep 30       # quantos backups manter (padrao 30)
"""

import sys, os, json, time, urllib.request, urllib.parse
from datetime import datetime

FIREBASE_PROJECT = "bolao-copa-2026-ae070"
FIREBASE_WEB_KEY = "AIzaSyDj8dJg6FgVXcdANyizRO4rBDwJX6YvIOs"
BASE = "https://firestore.googleapis.com/v1/projects/%s/databases/(default)/documents/" % FIREBASE_PROJECT

PASTA = os.path.dirname(os.path.abspath(__file__))
DIR_BACKUP = os.path.join(PASTA, "backups")

NO_RECEIPTS = "--no-receipts" in sys.argv
KEEP = 30
if "--keep" in sys.argv:
    try:
        KEEP = int(sys.argv[sys.argv.index("--keep") + 1])
    except Exception:
        pass


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "bolao-backup"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fs_decode(field):
    if not isinstance(field, dict) or not field:
        return None
    k = next(iter(field)); v = field[k]
    if k == "nullValue": return None
    if k == "booleanValue": return bool(v)
    if k == "integerValue":
        try: return int(v)
        except Exception: return v
    if k == "doubleValue": return float(v)
    if k == "stringValue": return v
    if k == "timestampValue": return v
    if k == "arrayValue":
        return [fs_decode(x) for x in (v.get("values", []) if isinstance(v, dict) else [])]
    if k == "mapValue":
        return {kk: fs_decode(vv) for kk, vv in (v.get("fields", {}) if isinstance(v, dict) else {}).items()}
    return v


def doc_to_obj(doc):
    return {kk: fs_decode(vv) for kk, vv in (doc.get("fields", {}) or {}).items()}


def get_doc(path):
    d = http_json(BASE + path + "?key=" + FIREBASE_WEB_KEY)
    return doc_to_obj(d)


def get_collection(name):
    """Retorna lista de (id, obj) da colecao, paginando."""
    out = []
    token = None
    while True:
        url = BASE + name + "?pageSize=300&key=" + FIREBASE_WEB_KEY
        if token:
            url += "&pageToken=" + urllib.parse.quote(token)
        d = http_json(url)
        for doc in d.get("documents", []) or []:
            did = doc["name"].split("/")[-1]
            out.append((did, doc_to_obj(doc)))
        token = d.get("nextPageToken")
        if not token:
            break
    return out


def main():
    try:
        meta = get_doc("bolao/meta")
        matches_doc = get_doc("bolao/matches")
        matches = matches_doc.get("list", []) if isinstance(matches_doc, dict) else []
        participants = [obj for (_id, obj) in get_collection("participants")]
        receipts = {}
        if not NO_RECEIPTS:
            for rid, robj in get_collection("receipts"):
                # o app guarda o comprovante como string (campo 'url')
                receipts[rid] = robj.get("url", robj)
    except Exception as ex:
        print("ERRO ao ler o Firebase:", ex)
        return 1

    backup = {
        "app": "bolao-copa-2026",
        "version": 1,
        "exportedAt": int(time.time() * 1000),
        "meta": meta,
        "matches": matches,
        "participants": participants,
        "receipts": receipts,
    }

    os.makedirs(DIR_BACKUP, exist_ok=True)
    nome = "bolao-backup-%s%s.json" % (
        datetime.now().strftime("%Y-%m-%d_%H%M"),
        "" if not NO_RECEIPTS else "-leve",
    )
    caminho = os.path.join(DIR_BACKUP, nome)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(backup, f, ensure_ascii=False)

    tam = os.path.getsize(caminho)
    print("OK: backup salvo em %s (%d participantes, %d comprovantes, %.0f KB)" % (
        caminho, len(participants), len(receipts), tam / 1024.0))

    # manter apenas os ultimos KEEP backups (mesmo tipo)
    try:
        arqs = sorted([a for a in os.listdir(DIR_BACKUP) if a.startswith("bolao-backup-") and a.endswith(".json")])
        # separa por tipo (leve x completo) para nao um apagar o outro
        completos = [a for a in arqs if "-leve" not in a]
        leves = [a for a in arqs if "-leve" in a]
        for grupo in (completos, leves):
            for velho in grupo[:-KEEP]:
                try: os.remove(os.path.join(DIR_BACKUP, velho))
                except Exception: pass
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
