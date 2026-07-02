# -*- coding: utf-8 -*-
"""
Atualizador automatico de placar - Bolao Copa 2026
---------------------------------------------------
Le os jogos no Firebase (doc bolao/matches), busca o placar da Copa na
API publica da ESPN (gratis, SEM chave) e grava scoreA/scoreB/live de
volta no Firebase. Todos que estiverem com o bolao aberto veem o placar
mudar sozinho.

- Nao precisa instalar nada (usa so a biblioteca padrao do Python 3).
- Nao precisa de chave nem cadastro.
- Roda no PC (Agendador de Tarefas) e/ou na nuvem (GitHub Actions).

Uso:
    python atualizar_placar.py           # roda uma vez (grava no Firebase)
    python atualizar_placar.py --dry     # simula, mostra o que faria, NAO grava
    python atualizar_placar.py --force   # ignora o filtro "so em dia de jogo"
"""

import sys, json, unicodedata, urllib.request, urllib.error, os
from datetime import datetime, timedelta

try:  # acentuacao correta no console do Windows (nao falha se nao houver console)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# =========================== CONFIGURACAO ===========================
# Fonte do placar: API publica da ESPN (Copa do Mundo). Sem chave.
ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"

# Firebase deste bolao (ja preenchido).
FIREBASE_PROJECT = "bolao-copa-2026-ae070"
FIREBASE_WEB_KEY = "AIzaSyDj8dJg6FgVXcdANyizRO4rBDwJX6YvIOs"

# De-para: nome do time NA ESPN -> nome como esta no seu bolao.
# A comparacao ignora maiusculas e acentos ("Belgica" casa com "BELGICA").
# Conforme a Copa avanca e entram times novos, acrescente aqui.
TEAM_MAP = {
    "England": "Inglaterra",
    "Congo DR": "RD Congo",
    "DR Congo": "RD Congo",
    "Belgium": "Belgica",
    "Senegal": "Senegal",
    "United States": "EUA",
    "USA": "EUA",
    "Bosnia-Herzegovina": "Bosnia",
    "Bosnia and Herzegovina": "Bosnia",
    "Brazil": "Brasil",
    "Croatia": "Croacia",
    "France": "Franca",
    "Spain": "Espanha",
    "Germany": "Alemanha",
    "Netherlands": "Holanda",
    "South Korea": "Coreia do Sul",
    "Saudi Arabia": "Arabia Saudita",
    "Morocco": "Marrocos",
    "Switzerland": "Suica",
    "Turkiye": "Turquia",
    "Turkey": "Turquia",
    "Ivory Coast": "Costa do Marfim",
}

# So chama a fonte a partir de X minutos antes do inicio do jogo.
MINUTOS_ANTES = 5
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
    """Maiusculas, sem acento, sem espacos extras - para comparar nomes."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.upper().split())


# ---------- Firestore REST: codificar/decodificar ----------
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


# ---------- HTTP ----------
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


# ---------- Firebase ----------
FS_URL = ("https://firestore.googleapis.com/v1/projects/%s/databases/(default)"
          "/documents/bolao/matches?key=%s") % (FIREBASE_PROJECT, FIREBASE_WEB_KEY)


def ler_jogos():
    doc = http_json(FS_URL)
    fields = doc.get("fields", {})
    return fs_decode(fields.get("list", {"arrayValue": {"values": []}})) or []


def gravar_jogos(lista):
    url = FS_URL + "&updateMask.fieldPaths=list"
    http_json(url, method="PATCH", body={"fields": {"list": fs_encode(lista)}})


# ---------- ESPN ----------
def buscar_espn():
    """Retorna lista de jogos: {home, away, gh, ga, state, detail}."""
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
                "home": home["team"]["displayName"],
                "away": away["team"]["displayName"],
                "gh": home.get("score"),
                "ga": away.get("score"),
                "state": st.get("state"),          # pre / in / post
                "detail": st.get("shortDetail", ""),
            })
        except Exception:
            continue
    return jogos


def to_int(x):
    try:
        return int(x)
    except Exception:
        return None


def casar_e_atualizar(jogos, espn):
    """Atualiza scoreA/scoreB/live dos jogos do bolao que casam com a ESPN."""
    idx = {}
    for fx in espn:
        home_pt = TEAM_MAP.get(fx["home"], fx["home"])
        away_pt = TEAM_MAP.get(fx["away"], fx["away"])
        chave = frozenset([norm(home_pt), norm(away_pt)])
        idx[chave] = {"fx": fx, "home_norm": norm(home_pt)}

    mudou = False
    for g in jogos:
        # Respeita jogo ja finalizado: uma vez encerrado (live False + placar
        # preenchido), o script NAO sobrescreve. Assim, se o organizador ajustar
        # (ex.: contar so o tempo normal numa prorrogacao), o ajuste permanece.
        if g.get("live") is False and g.get("scoreA") is not None:
            continue
        chave = frozenset([norm(g.get("teamA")), norm(g.get("teamB"))])
        m = idx.get(chave)
        if not m:
            continue
        fx = m["fx"]
        state = fx["state"]
        if state == "pre":
            continue  # nao comecou
        gh, ga = to_int(fx["gh"]), to_int(fx["ga"])
        if gh is None or ga is None:
            continue

        # descobre qual lado corresponde ao teamA do bolao
        if norm(g.get("teamA")) == m["home_norm"]:
            novoA, novoB = gh, ga
        else:
            novoA, novoB = ga, gh

        ao_vivo = (state == "in")   # 'post' = encerrado
        atual = (g.get("scoreA"), g.get("scoreB"), bool(g.get("live")))
        novo = (novoA, novoB, ao_vivo)
        if atual != novo:
            g["scoreA"], g["scoreB"], g["live"] = novo
            mudou = True
            tag = "AO VIVO" if ao_vivo else "ENCERRADO"
            log("  %s x %s -> %d:%d (%s / %s)" % (
                g.get("teamA"), g.get("teamB"), novoA, novoB, fx["detail"], tag))
    return mudou


def parse_dt(iso):
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def main():
    try:
        jogos = ler_jogos()
    except Exception as ex:
        log("ERRO ao ler o Firebase: %s" % ex)
        return
    log("Jogos no bolao: %d" % len(jogos))

    hoje = datetime.now().strftime("%Y-%m-%d")
    agora = datetime.now()

    # jogos de HOJE que ja comecaram (ou vao comecar em minutos) e ainda nao
    # estao concluidos (concluido = live False com placar preenchido).
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

    mudou = casar_e_atualizar(jogos, espn)
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
