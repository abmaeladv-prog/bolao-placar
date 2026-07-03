# -*- coding: utf-8 -*-
"""
Atualizador automatico de placar - Bolao Copa 2026
---------------------------------------------------
Le os jogos no Firebase (doc bolao/matches), busca o placar da Copa na
API publica da ESPN (gratis, SEM chave) e grava scoreA/scoreB/live de
volta no Firebase.

- No horario de inicio de cada jogo, marca 0x0 ao vivo (mesmo antes do
  primeiro gol), e vai atualizando conforme os gols saem.
- Nao mexe em jogo ja finalizado (respeita ajuste manual do organizador).
- Nao precisa instalar nada nem ter chave.

Uso:
    python atualizar_placar.py           # roda uma vez (grava no Firebase)
    python atualizar_placar.py --dry     # simula, mostra o que faria, NAO grava
    python atualizar_placar.py --force   # ignora o filtro "so em dia de jogo"
"""

import sys, json, unicodedata, urllib.request, urllib.error, os
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# =========================== CONFIGURACAO ===========================
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
FIREBASE_PROJECT = "bolao-copa-2026-ae070"
FIREBASE_WEB_KEY = "AIzaSyDj8dJg6FgVXcdANyizRO4rBDwJX6YvIOs"

# De-para: nome do time NA ESPN (ingles) -> nome no seu bolao (portugues).
# A comparacao ignora maiusculas e acentos. Cobre os principais paises.
TEAM_MAP = {
    "England": "Inglaterra", "Scotland": "Escocia", "Wales": "Pais de Gales",
    "Northern Ireland": "Irlanda do Norte", "Ireland": "Irlanda",
    "France": "Franca", "Spain": "Espanha", "Germany": "Alemanha",
    "Portugal": "Portugal", "Italy": "Italia", "Netherlands": "Holanda",
    "Belgium": "Belgica", "Croatia": "Croacia", "Switzerland": "Suica",
    "Austria": "Austria", "Poland": "Polonia", "Denmark": "Dinamarca",
    "Sweden": "Suecia", "Norway": "Noruega", "Ukraine": "Ucrania",
    "Serbia": "Servia", "Czechia": "Tchequia", "Czech Republic": "Tchequia",
    "Turkiye": "Turquia", "Turkey": "Turquia", "Greece": "Grecia",
    "Hungary": "Hungria", "Romania": "Romenia", "Russia": "Russia",
    "Slovenia": "Eslovenia", "Slovakia": "Eslovaquia", "Finland": "Finlandia",
    "Iceland": "Islandia", "Georgia": "Georgia", "Albania": "Albania",
    "Brazil": "Brasil", "Argentina": "Argentina", "Uruguay": "Uruguai",
    "Colombia": "Colombia", "Chile": "Chile", "Peru": "Peru",
    "Ecuador": "Equador", "Paraguay": "Paraguai", "Bolivia": "Bolivia",
    "Venezuela": "Venezuela", "United States": "EUA", "USA": "EUA",
    "Mexico": "Mexico", "Canada": "Canada", "Costa Rica": "Costa Rica",
    "Panama": "Panama", "Honduras": "Honduras", "Jamaica": "Jamaica",
    "Curacao": "Curacao", "Guatemala": "Guatemala", "Haiti": "Haiti",
    "Morocco": "Marrocos", "Senegal": "Senegal", "Tunisia": "Tunisia",
    "Algeria": "Argelia", "Egypt": "Egito", "Nigeria": "Nigeria",
    "Cameroon": "Camaroes", "Ghana": "Gana", "Ivory Coast": "Costa do Marfim",
    "Cote d'Ivoire": "Costa do Marfim", "Mali": "Mali", "South Africa": "Africa do Sul",
    "Cape Verde": "Cabo Verde", "Congo DR": "RD Congo", "DR Congo": "RD Congo",
    "Angola": "Angola", "Burkina Faso": "Burkina Faso", "Guinea": "Guine",
    "Equatorial Guinea": "Guine Equatorial", "Gabon": "Gabao", "Benin": "Benin",
    "Zambia": "Zambia", "Uganda": "Uganda", "Tanzania": "Tanzania",
    "Kenya": "Quenia", "Namibia": "Namibia", "Mozambique": "Mocambique",
    "Japan": "Japao", "South Korea": "Coreia do Sul", "Korea Republic": "Coreia do Sul",
    "Iran": "Ira", "Iraq": "Iraque", "Saudi Arabia": "Arabia Saudita",
    "Qatar": "Catar", "United Arab Emirates": "Emirados Arabes", "UAE": "Emirados Arabes",
    "Australia": "Australia", "New Zealand": "Nova Zelandia",
    "Uzbekistan": "Uzbequistao", "Jordan": "Jordania", "Bahrain": "Bahrein",
    "China": "China", "China PR": "China", "Indonesia": "Indonesia",
    "Bosnia-Herzegovina": "Bosnia", "Bosnia and Herzegovina": "Bosnia",
    "Israel": "Israel", "Kosovo": "Kosovo", "Montenegro": "Montenegro",
    "North Macedonia": "Macedonia do Norte", "Luxembourg": "Luxemburgo",
    "New Caledonia": "Nova Caledonia", "Suriname": "Suriname",
}

MINUTOS_ANTES = 5          # comeca a olhar a partir de 5 min antes do inicio
JANELA_JOGO_HORAS = 3      # forca 0x0 ao vivo ate 3h apos o inicio (se sem dados)
# ====================================================================

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_LOG = os.path.join(PASTA, "log_placar.txt")
DRY = "--dry" in sys.argv
FORCE = "--force" in sys.argv


def log(msg):
    linha = "[%s] %s" % (datetime.now().strftime("%d/%m %H:%M:%S"), msg)
    print(linha)
    try:
        with open(ARQ_LOG, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except Exception:
        pass


def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.upper().split())


def fs_encode(v):
    if v is None:
        return {"nullValue": None}
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, list):
        return {"arrayValue": {"values": [fs_encode(x) for x in v]}}
    if isinstance(v, dict):
        return {"mapValue": {"fields": {k: fs_encode(x) for k, x in v.items()}}}
    return {"stringValue": str(v)}


def fs_decode(field):
    if not isinstance(field, dict) or not field:
        return None
    k = next(iter(field))
    val = field[k]
    if k == "nullValue":
        return None
    if k == "booleanValue":
        return bool(val)
    if k == "integerValue":
        try:
            return int(val)
        except Exception:
            return val
    if k == "doubleValue":
        return float(val)
    if k == "stringValue":
        return val
    if k == "arrayValue":
        return [fs_decode(x) for x in (val.get("values", []) if isinstance(val, dict) else [])]
    if k == "mapValue":
        return {kk: fs_decode(vv) for kk, vv in (val.get("fields", {}) if isinstance(val, dict) else {}).items()}
    return val


def http_json(url, headers=None, method="GET", body=None):
    hdrs = {"User-Agent": "Mozilla/5.0 (bolao-placar)"}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


FS_URL = ("https://firestore.googleapis.com/v1/projects/%s/databases/(default)"
          "/documents/bolao/matches?key=%s") % (FIREBASE_PROJECT, FIREBASE_WEB_KEY)


def ler_jogos():
    doc = http_json(FS_URL)
    fields = doc.get("fields", {})
    return fs_decode(fields.get("list", {"arrayValue": {"values": []}})) or []


def gravar_jogos(lista):
    url = FS_URL + "&updateMask.fieldPaths=list"
    http_json(url, method="PATCH", body={"fields": {"list": fs_encode(lista)}})


SUMMARY_URL = ESPN_URL.replace("scoreboard", "summary") + "?event="


def buscar_espn():
    dados = http_json(ESPN_URL)
    jogos = []
    for ev in dados.get("events", []) or []:
        try:
            comp = ev["competitions"][0]
            cs = comp["competitors"]
            home = next(c for c in cs if c.get("homeAway") == "home")
            away = next(c for c in cs if c.get("homeAway") == "away")
            st = (ev.get("status") or {}).get("type", {})
            jogos.append({
                "id": ev.get("id"),
                "home": home["team"]["displayName"],
                "away": away["team"]["displayName"],
                "home_id": (home.get("team") or {}).get("id"),
                "away_id": (away.get("team") or {}).get("id"),
                "gh": home.get("score"),
                "ga": away.get("score"),
                "state": st.get("state"),
                "name": st.get("name", ""),
                "detail": st.get("shortDetail", ""),
            })
        except Exception:
            continue
    return jogos


def eh_prorrogacao(name, detail):
    """True se o jogo passou do tempo normal (prorrogacao/penaltis)."""
    n = (name or "").upper()
    d = (detail or "").upper()
    if "OVERTIME" in n or "EXTRA" in n or "SHOOTOUT" in n or "PENALT" in n:
        return True
    if "PENS" in d or "AET" in d or d.strip() == "ET":
        return True
    return False


def placar_tempo_normal(event_id, home_id, away_id):
    """Placar do fim do TEMPO NORMAL + acrescimos: conta so os gols dos
    periodos 1 e 2 (ignora prorrogacao e penaltis), via keyEvents do summary."""
    try:
        sm = http_json(SUMMARY_URL + str(event_id))
    except Exception:
        return None, None
    gh = ga = 0
    for k in sm.get("keyEvents", []) or []:
        if not k.get("scoringPlay"):
            continue
        per = (k.get("period") or {}).get("number")
        if per is None or per > 2:
            continue  # periodo 1 = 1o tempo, 2 = 2o tempo; 3+ = prorrogacao/penaltis
        tid = str((k.get("team") or {}).get("id") or "")
        if tid == str(home_id):
            gh += 1
        elif tid == str(away_id):
            ga += 1
    return gh, ga


def to_int(x):
    try:
        return int(x)
    except Exception:
        return None


def parse_dt(iso):
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def casar_e_atualizar(jogos, espn, agora):
    idx = {}
    for fx in espn:
        home_pt = TEAM_MAP.get(fx["home"], fx["home"])
        away_pt = TEAM_MAP.get(fx["away"], fx["away"])
        idx[frozenset([norm(home_pt), norm(away_pt)])] = {"fx": fx, "home_norm": norm(home_pt)}

    mudou = False
    for g in jogos:
        # jogo ja finalizado (live False + placar): respeita, nao mexe
        if g.get("live") is False and g.get("scoreA") is not None:
            continue
        chave = frozenset([norm(g.get("teamA")), norm(g.get("teamB"))])
        m = idx.get(chave)
        ini = parse_dt(g.get("dateISO"))
        comecou = ini is not None and agora >= ini
        espn_state = None

        novoA = novoB = None
        ao_vivo = None
        origem = ""
        if m:
            fx = m["fx"]
            espn_state = fx["state"]
            name = fx.get("name", "")
            detail = fx.get("detail", "")
            eh_home = (norm(g.get("teamA")) == m["home_norm"])
            gh, ga = to_int(fx["gh"]), to_int(fx["ga"])

            if eh_prorrogacao(name, detail):
                # passou do tempo normal: ENCERRA no placar dos 90' + acrescimos
                # (conta so gols dos periodos 1 e 2; ignora prorrogacao/penaltis)
                rgh, rga = placar_tempo_normal(fx.get("id"), fx.get("home_id"), fx.get("away_id"))
                if rgh is not None:
                    novoA, novoB = (rgh, rga) if eh_home else (rga, rgh)
                    ao_vivo = False
                    origem = "tempo normal (encerrado; sem prorrogacao)"
                # se o summary falhar, nao mexe (mantem o placar atual)
            elif espn_state == "post" and gh is not None and ga is not None:
                # FT: decidido no tempo normal -> placar da ESPN ja e o do tempo normal
                novoA, novoB = (gh, ga) if eh_home else (ga, gh)
                ao_vivo = False
                origem = detail
            elif espn_state == "in" and gh is not None and ga is not None:
                # tempo normal, ao vivo
                novoA, novoB = (gh, ga) if eh_home else (ga, gh)
                ao_vivo = True
                origem = detail

        # comecou mas ainda sem dados da ESPN (nao achado ou 'pre') -> 0x0 ao vivo
        if novoA is None and comecou and (m is None or espn_state == "pre") \
                and ini is not None and agora <= ini + timedelta(hours=JANELA_JOGO_HORAS):
            novoA, novoB, ao_vivo, origem = 0, 0, True, "inicio"

        if novoA is None:
            continue

        atual = (g.get("scoreA"), g.get("scoreB"), bool(g.get("live")))
        novo = (novoA, novoB, bool(ao_vivo))
        if atual != novo:
            g["scoreA"], g["scoreB"], g["live"] = novo
            mudou = True
            tag = "AO VIVO" if ao_vivo else "ENCERRADO"
            log("  %s x %s -> %d:%d (%s / %s)" % (
                g.get("teamA"), g.get("teamB"), novoA, novoB, origem, tag))
    return mudou


def main():
    try:
        jogos = ler_jogos()
    except Exception as ex:
        log("ERRO ao ler o Firebase: %s" % ex)
        return
    log("Jogos no bolao: %d" % len(jogos))

    hoje = datetime.now().strftime("%Y-%m-%d")
    agora = datetime.now()

    relevantes = []
    for g in jogos:
        d = g.get("dateISO")
        if not d or d[:10] != hoje:
            continue
        ini = parse_dt(d)
        comecou = (ini is None) or (agora >= ini - timedelta(minutes=MINUTOS_ANTES))
        concluido = (g.get("live") is False and g.get("scoreA") is not None)
        if comecou and not concluido:
            relevantes.append(g)

    if not relevantes and not FORCE:
        log("Nenhum jogo do bolao em andamento hoje. Nada a fazer.")
        return

    try:
        espn = buscar_espn()
    except Exception as ex:
        log("ERRO ao consultar a ESPN: %s" % ex)
        return
    log("Jogos retornados pela ESPN: %d" % len(espn))

    mudou = casar_e_atualizar(jogos, espn, agora)
    if not mudou:
        log("Sem mudancas no placar.")
        return

    if DRY:
        log("[DRY] Mudancas detectadas, mas --dry: NAO gravei no Firebase.")
        return

    try:
        gravar_jogos(jogos)
        log("Placar atualizado no Firebase com sucesso.")
    except Exception as ex:
        log("ERRO ao gravar no Firebase: %s" % ex)


if __name__ == "__main__":
    main()
