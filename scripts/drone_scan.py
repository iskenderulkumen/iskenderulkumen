"""
Katkı haritasını tarayan drone animasyonu üretir.

Ne yapar?
  1) GitHub'dan son 1 yılın katkı verisini çeker (her gün kaç katkı yapılmış).
  2) Bu veriden bir SVG çizer: 53 hafta x 7 gün = kutucuklar.
  3) Bir drone kutucukların üzerinden satır satır, zikzak çizerek geçer.
     Üzerinden geçtiği kutucuk, o günkü katkı yoğunluğuna göre neon renkle yanar.

Çalıştırma:
  GITHUB_TOKEN=... python3 scripts/drone_scan.py <kullanici_adi> <cikti.svg>

Sadece Python'un kendi kütüphanelerini kullanır, ek kurulum gerekmez.
"""

import json
import os
import sys
import urllib.request
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# AYARLAR: boyutlar, renkler, süreler
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 800, 200
GRID_X, GRID_Y = 44, 62      # ızgaranın sol üst köşesi
CELL, PITCH = 11, 14         # kutucuk boyu ve bir kutucuktan diğerine mesafe

ROW_TIME = 3.0               # drone'un bir satırı geçme süresi (sn)
STEP_TIME = 0.35             # bir alt satıra inme süresi (sn)
HOLD_TIME = 4.0              # tarama bitince sonucun ekranda kalma süresi (sn)

# GitHub'ın verdiği yoğunluk seviyesi → neon renk
LEVEL_COLORS = {
    "NONE": None,
    "FIRST_QUARTILE": "#3b0a63",
    "SECOND_QUARTILE": "#7b2ff7",
    "THIRD_QUARTILE": "#c026d3",
    "FOURTH_QUARTILE": "#ff2bd6",
}
EMPTY_COLOR = "#1a0b2e"
MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


# ---------------------------------------------------------------------------
# 1) VERİYİ ÇEK
# ---------------------------------------------------------------------------
def fetch_weeks(user, token):
    """GitHub GraphQL API'sinden katkı takvimini çeker.

    Dönen değer: haftaların listesi; her hafta 7'ye kadar gün içerir.
    Her gün: {"date": "2026-01-05", "contributionCount": 3, "contributionLevel": "SECOND_QUARTILE"}
    """
    query = """
    query($login: String!) {
      user(login: $login) {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { date contributionCount contributionLevel weekday } }
          }
        }
      }
    }"""
    body = json.dumps({"query": query, "variables": {"login": user}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.load(resp)
    if "errors" in data:
        raise SystemExit(f"GitHub API hatası: {data['errors']}")
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    return cal["weeks"], cal["totalContributions"]


# ---------------------------------------------------------------------------
# 2) ZAMANLAMA: drone hangi kutucuğun üstünden ne zaman geçiyor?
# ---------------------------------------------------------------------------
def row_start(row):
    """Drone'un 'row' numaralı satıra başladığı an (sn)."""
    return row * (ROW_TIME + STEP_TIME)


def pass_time(col, row, n_cols):
    """Drone'un (col, row) kutucuğunun üstünden geçtiği an (sn).

    Çift satırlarda soldan sağa, tek satırlarda sağdan sola gider (zikzak).
    """
    progress = col / (n_cols - 1)          # 0 = en sol, 1 = en sağ
    if row % 2 == 1:
        progress = 1 - progress            # tek satırda yön ters
    return row_start(row) + progress * ROW_TIME


def cell_center(col, row):
    return GRID_X + col * PITCH + CELL / 2, GRID_Y + row * PITCH + CELL / 2


# ---------------------------------------------------------------------------
# 3) SVG'Yİ ÇİZ
# ---------------------------------------------------------------------------
def build_svg(weeks, total, font_b64):
    n_cols = len(weeks)
    scan_end = row_start(6) + ROW_TIME
    dur = scan_end + HOLD_TIME                # tüm döngünün süresi

    def kt(t):
        """Saniyeyi 0-1 arası 'keyTimes' değerine çevirir."""
        return f"{min(max(t / dur, 0), 1):.4f}"

    out = []
    add = out.append

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" font-family="PS, sans-serif">')
    add("<defs>")
    add("<!-- FONT: Exo 2 (The Exo 2 Project Authors, SIL OFL 1.1). Adı değiştirilmiş alt küme. -->")
    add(f'<style>@font-face {{ font-family: "PS"; font-weight: 100 900; '
        f'src: url(data:font/woff;base64,{font_b64}) format("woff"); }}</style>')
    add('<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="2.5" result="b"/>'
        '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>')
    add('<radialGradient id="beam"><stop offset="0" stop-color="#00f0ff" stop-opacity="0.45"/>'
        '<stop offset="1" stop-color="#00f0ff" stop-opacity="0"/></radialGradient>')
    add("</defs>")

    add(f'<rect width="{WIDTH}" height="{HEIGHT}" rx="14" fill="#07010f"/>')

    # Başlık
    add('<text x="20" y="28" fill="#fff" font-size="15" font-weight="700">SURVEY_SCAN</text>')
    add('<text x="132" y="28" fill="#9d4edd" font-size="12">// katkı haritası taranıyor</text>')

    # Ay etiketleri: bir ay ilk kez hangi haftada başlıyorsa oraya yaz
    last_month = None
    for col, week in enumerate(weeks):
        m = date.fromisoformat(week["contributionDays"][0]["date"]).month
        if m != last_month and col < n_cols - 2:
            add(f'<text x="{GRID_X + col * PITCH}" y="{GRID_Y - 8}" fill="#9d4edd" '
                f'font-size="10">{MONTHS[m - 1]}</text>')
        last_month = m

    # Gün etiketleri
    for row, name in ((1, "Pzt"), (3, "Çar"), (5, "Cum")):
        add(f'<text x="{GRID_X - 8}" y="{GRID_Y + row * PITCH + 9}" fill="#9d4edd" '
            f'font-size="9" text-anchor="end">{name}</text>')

    # Kutucuklar
    row_totals = [0] * 7
    for col, week in enumerate(weeks):
        for day in week["contributionDays"]:
            row = day["weekday"]           # 0 = Pazar ... 6 = Cumartesi
            x, y = GRID_X + col * PITCH, GRID_Y + row * PITCH
            # Taban kutucuk: her zaman görünür, koyu
            add(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{EMPTY_COLOR}"/>')

            color = LEVEL_COLORS.get(day["contributionLevel"])
            if not color:
                continue
            row_totals[row] += day["contributionCount"]
            # Renkli kutucuk: drone üstünden geçtiği an belirir, döngü sonunda söner
            t = pass_time(col, row, n_cols)
            glow = ' filter="url(#glow)"' if day["contributionLevel"] == "FOURTH_QUARTILE" else ""
            add(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{color}" '
                f'opacity="0"{glow}><animate attributeName="opacity" values="0;0;1;1;0" '
                f'keyTimes="0;{kt(t)};{kt(t + 0.08)};{kt(dur - 0.4)};1" dur="{dur}s" '
                f'repeatCount="indefinite"/></rect>')

    # Drone'un rotası: her satırın başı ve sonu birer durak
    stops = []  # (zaman, x, y)
    for row in range(7):
        left, y = cell_center(0, row)
        right, _ = cell_center(n_cols - 1, row)
        a, b = (left, right) if row % 2 == 0 else (right, left)
        stops.append((row_start(row), a, y))
        stops.append((row_start(row) + ROW_TIME, b, y))
    # Tarama bitince drone başlangıç noktasına geri döner
    stops.append((dur - 0.4, stops[-1][1], stops[-1][2]))
    stops.append((dur, stops[0][1], stops[0][2]))

    values = ";".join(f"{x:.1f} {y:.1f}" for _, x, y in stops)
    times = ";".join(kt(t) for t, _, _ in stops)

    add("<g>")
    add(f'<animateTransform attributeName="transform" type="translate" values="{values}" '
        f'keyTimes="{times}" dur="{dur}s" repeatCount="indefinite"/>')
    # Kameranın taradığı alan: drone'un altındaki ışık halesi
    add('<circle r="22" fill="url(#beam)"/>')
    # Üstten görünüm quadcopter: X şeklinde kollar + 4 pervane
    add('<g stroke="#00f0ff" stroke-width="1.6" fill="none" filter="url(#glow)">')
    add('<line x1="-9" y1="-9" x2="9" y2="9"/><line x1="-9" y1="9" x2="9" y2="-9"/>')
    for px, py in ((-9, -9), (9, -9), (-9, 9), (9, 9)):
        add(f'<circle cx="{px}" cy="{py}" r="5" stroke="#ff2bd6" stroke-dasharray="6 3">'
            f'<animateTransform attributeName="transform" type="rotate" from="0 {px} {py}" '
            f'to="360 {px} {py}" dur="0.25s" repeatCount="indefinite"/></circle>')
    add('<rect x="-4" y="-4" width="8" height="8" rx="2" fill="#07010f"/>')
    add("</g></g>")

    # Sayaç: her satır bitince taranan katkı sayısı artar
    legend_y = GRID_Y + 7 * PITCH + 22
    running = 0
    for row in range(7):
        running += row_totals[row]
        start = row_start(row) + ROW_TIME
        end = row_start(row + 1) + ROW_TIME if row < 6 else dur - 0.4
        add(f'<text x="{GRID_X}" y="{legend_y}" fill="#00f0ff" font-size="12" opacity="0">'
            f'TARANAN: {running} katkı'
            f'<animate attributeName="opacity" values="0;1;0" keyTimes="0;{kt(start)};{kt(end)}" '
            f'calcMode="discrete" dur="{dur}s" repeatCount="indefinite"/></text>')
    add(f'<text x="{GRID_X}" y="{legend_y}" fill="#ffe600" font-size="12" opacity="0">'
        f'TARAMA SÜRÜYOR...<animate attributeName="opacity" values="0;1;0" '
        f'keyTimes="0;{kt(0.01)};{kt(row_start(0) + ROW_TIME)}" calcMode="discrete" '
        f'dur="{dur}s" repeatCount="indefinite"/></text>')
    add(f'<text x="{WIDTH // 2}" y="{legend_y}" fill="#9d4edd" font-size="11" text-anchor="middle">'
        f'son 1 yıl: {total} katkı</text>')

    # Renk açıklaması (az → çok)
    lx = WIDTH - 44 - 5 * PITCH
    add(f'<text x="{lx - 8}" y="{legend_y}" fill="#9d4edd" font-size="10" text-anchor="end">az</text>')
    for i, c in enumerate([EMPTY_COLOR] + [v for v in LEVEL_COLORS.values() if v]):
        add(f'<rect x="{lx + i * PITCH}" y="{legend_y - 10}" width="{CELL}" height="{CELL}" rx="2" fill="{c}"/>')
    add(f'<text x="{lx + 5 * PITCH + 4}" y="{legend_y}" fill="#9d4edd" font-size="10">çok</text>')

    add("</svg>")
    return "\n".join(out)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Kullanım: python3 drone_scan.py <kullanici_adi> <cikti.svg>")
    user, out_path = sys.argv[1], Path(sys.argv[2])
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN ortam değişkeni gerekli.")

    weeks, total = fetch_weeks(user, token)
    font_b64 = (Path(__file__).parent / "font.b64").read_text().strip()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_svg(weeks, total, font_b64), encoding="utf-8")
    print(f"{out_path} yazıldı ({total} katkı, {len(weeks)} hafta)")


if __name__ == "__main__":
    main()
