#!/usr/bin/env python3
"""
13_cierres_sc.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Cierres REALES de Carolina del Sur, por distrito y fecha, 2020-21 … 2025-26.

Fuente: el «Annual Report on Missed School Days» que el Departamento de
Educación de Carolina del Sur (SCDE) entrega cada año a la Asamblea (§59-1-425).
  fuentes/cierres_sc/sc_2021.pdf … sc_2526.pdf
Cada informe es una tabla larga: un distrito por fila y, dentro de cada celda,
un párrafo por fecha (no hay filetes entre fechas, solo entre distritos).

Cómo se lee:
  · columnas: de los filetes verticales de la página; su papel (fecha, motivo,
    n.º de escuelas) sale del texto de la cabecera, que se repite en cada página
    (si falta, vale la de la página anterior);
  · distritos: los filetes horizontales que cruzan la columna «District» (más
    los bordes del sombreado de celda, porque algún filete no está dibujado);
    un bloque sin nombre al empezar página continúa el distrito anterior;
  · fechas ↔ motivos: los motivos se trocean por su texto (cada uno empieza por
    Weather, Road, Covid, Other, Health, Facility… y acaba en eLearning, Closed
    o makeup) y se casan con las fechas por orden; la posición vertical solo
    sirve de comprobación, porque la alineación cambia de un año a otro.

Límites conocidos:
  · 2020-21 solo trae días PERDIDOS (aún no se informaba del eLearning) y no da
    el número de escuelas; la columna «Days Made Up» (fechas de recuperación)
    no se lee.
  · Las erratas del propio informe se dejan como están, salvo el año de una
    fecha que cae fuera del curso (se corrige y se avisa).
  · Distritos sin límite territorial (chárter, escuelas del Gobernador, etc.):
    leaid vacío. Los distritos ya fusionados llevan el leaid del distrito
    actual que cubre su territorio (se listan al final como «a criterio»).

Salida:  fuentes/cierres_sc/cierres_sc.csv   una fila por distrito y fecha
         curso, distrito_pdf, leaid, fecha, motivo, tiempo, elearning, escuelas

Uso:
  13_cierres_sc.py              lee los seis PDF, escribe el CSV y resume
  13_cierres_sc.py --verifica   además: recuento contra el texto bruto y tormentas
  13_cierres_sc.py --muestra 12 además: 12 filas por curso junto al texto bruto
"""
import re
import sys
from collections import Counter, OrderedDict, defaultdict
from datetime import date
from pathlib import Path

import pandas as pd
import pdfplumber

BASE = Path('/opt/canalmeteo/nieve')
FUE = BASE / 'fuentes' / 'cierres_sc'
SALIDA = FUE / 'cierres_sc.csv'
CURSOS = [('2020-21', 'sc_2021.pdf'), ('2021-22', 'sc_2122.pdf'), ('2022-23', 'sc_2223.pdf'),
          ('2023-24', 'sc_2324.pdf'), ('2024-25', 'sc_2425.pdf'), ('2025-26', 'sc_2526.pdf')]

RE_FECHA = re.compile(r'(\d{1,2})/+(\d{1,2})/+(\d{2,4})(?!\d)')
RE_FECHA_BRUTA = re.compile(r'\d{1,2}\s?/+\s?\d{1,2}\s?/+\s?\d{2,4}')
# Palabras con las que empieza un motivo, y con las que termina
INICIOS = {'weather', 'road', 'covid', 'power', 'water', 'other', 'health', 'facility',
           'environmental', 'honored', 'inclement', 'hurricane', 'snow', 'winter', 'flooding', 'tornado'}
RE_FINAL = re.compile(r'(learning|closed|makeup)$', re.I)
RE_TIEMPO = re.compile(r'weather|snow|\bice\b|icy|winter|storm|road|hurricane|tropical|flood|tornado', re.I)
RE_SIN_LIMITE = re.compile(r"charter|gov(ernor)?\W*s?\b.*sch|deaf|juvenile|limestone|erskine|wil lou|palmetto unified", re.I)

AVISOS = []


def aviso(curso, txt):
    AVISOS.append((curso, txt))


def agrupa(vals, tol):
    """Medias de los grupos de valores que distan menos de `tol`."""
    out = []
    for v in sorted(vals):
        if out and v - out[-1][-1] <= tol:
            out[-1].append(v)
        else:
            out.append([v])
    return [sum(g) / len(g) for g in out]


# ───────────────────────── geometría de la página ─────────────────────────

def bloques_pagina(pg):
    """Devuelve (xs, bloques) o None si la página no tiene tabla.
    Cada bloque: (y0, y1, [líneas de cada columna]); línea = (y, texto)."""
    vert = [r for r in pg.rects if r['x1'] - r['x0'] < 2.5 and r['bottom'] - r['top'] > 10]
    if len(vert) < 8:
        return None
    xs = agrupa([r['x0'] for r in vert], 3)
    if len(xs) < 7:
        return None
    arriba = min(r['top'] for r in vert)
    abajo = max(r['bottom'] for r in vert)
    ys = [arriba, abajo]
    for r in pg.rects:
        alto, ancho = r['bottom'] - r['top'], r['x1'] - r['x0']
        if ancho < 20:
            continue
        if alto < 2.5 and r['x0'] <= xs[0] + 4 and r['x1'] >= xs[1] - 4:
            ys.append(r['top'])          # filete que cruza la columna del distrito
        elif alto > 3 and r['x0'] <= xs[0] + 2.5 and r['x1'] >= xs[1] - 2.5:
            ys += [r['top'], r['bottom']]  # sombreado de la celda entera
    ys = agrupa(ys, 2.5)
    palabras = pg.extract_words(x_tolerance=1.5, y_tolerance=2)
    bloques = []
    for a, b in zip(ys, ys[1:]):
        if b - a < 6:
            continue
        cols = [[] for _ in xs[:-1]]
        for w in palabras:
            yc = (w['top'] + w['bottom']) / 2
            if not (a - 1 <= yc <= b + 1):
                continue
            xc = (w['x0'] + w['x1']) / 2
            for i in range(len(xs) - 1):
                if xs[i] <= xc < xs[i + 1]:
                    cols[i].append(w)
        lineas = []
        for c in cols:
            d = OrderedDict()
            for w in sorted(c, key=lambda w: (w['top'], w['x0'])):
                k = next((k for k in d if abs(k - w['top']) < 3), w['top'])
                d.setdefault(k, []).append(w)
            lineas.append([(k, ' '.join(w['text'] for w in sorted(v, key=lambda w: w['x0'])))
                           for k, v in d.items()])
        bloques.append((a, b, lineas))
    return xs, bloques


def papeles(cab):
    """Índice de las columnas fecha / motivo / escuelas según el texto de la cabecera."""
    t = [' '.join(x for _, x in col).lower() for col in cab]
    mot = next((i for i, x in enumerate(t) if 'reason' in x), None)
    fec = next((i for i, x in enumerate(t) if 'date' in x), None)
    if fec is None:  # 2020-21: las fechas van en «Days Missed», antes del motivo
        fec = next((i for i, x in enumerate(t) if 'missed' in x and mot is not None and i < mot), None)
    esc = next((i for i, x in enumerate(t) if 'number' in x), None)
    return {'fecha': fec, 'motivo': mot, 'escuelas': esc}


# ───────────────────────── texto de las celdas ─────────────────────────

def une_nombre(lineas):
    s = ''
    for _, t in lineas:
        s = s + t if s.endswith('-') else (s + ' ' + t)
    s = re.sub(r'\s+', ' ', s.replace('’', "'")).strip()
    return s.replace('Williamsbur g', 'Williamsburg')


def primera_palabra(t):
    m = re.match(r'[A-Za-z]+', t.strip())
    return m.group(0).lower() if m else ''


def trocea_motivos(lineas):
    """Parte las líneas de la columna «Reason» en motivos: [y0, y1, [textos], empieza_bien]."""
    segs = []
    for y, t in lineas:
        t = t.strip()
        if not t or t.lower() in ('none', '0'):
            continue
        ini = primera_palabra(t) in INICIOS
        cola = re.fullmatch(r'[\W]*(e?learning|closed|makeup)', t, re.I) is not None
        nuevo = not segs or ini or (RE_FINAL.search(segs[-1][2][-1]) and not cola)
        if nuevo:
            segs.append([y, y, [t], ini])
        else:
            segs[-1][1] = y
            segs[-1][2].append(t)
    return segs


def limpia_motivo(textos):
    s = ' '.join(textos)
    s = re.sub(r'\s*[–—-]+\s*', ' - ', s)
    s = re.sub(r'&\s*', '& ', s)
    s = re.sub(r'\s+', ' ', s).strip(' -')
    s = re.sub(r'- Learning$', '- eLearning', s)  # errata «Learning» del informe 2021-22
    return s


def lee_fechas(lineas, curso, distrito):
    out = []
    for y, t in lineas:
        s = t.replace(' ', '')
        ms = list(RE_FECHA.finditer(s))
        resto = RE_FECHA.sub('', s).strip(',;')
        if resto and resto.lower() not in ('none', '0'):
            aviso(curso, 'columna de fecha con texto que no es fecha: «%s» (%s)' % (t, distrito))
        for m in ms:
            out.append((y, m))
    return out


def a_fecha(m, curso, distrito):
    """Fecha del curso (1-jul … 30-jun). Si el año escrito no cuadra (errata del informe:
    «8/31/2024» en el curso 2023-24, «3/3/2033», «8/31/203») se deduce del mes, siempre que
    el resultado sea día lectivo; si no, se descarta. Todo queda en los avisos."""
    mes, dia, an = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if len(m.group(3)) == 2:
        an += 2000
    a0 = int(curso[:4])
    ini, fin = date(a0, 7, 1), date(a0 + 1, 6, 30)
    try:
        f = date(an, mes, dia)
    except ValueError:
        f = None
    if f and ini <= f <= fin:
        if f.weekday() >= 5:
            aviso(curso, 'fecha en fin de semana %s (%s), se deja' % (m.group(0), distrito))
        return f
    try:
        g = date(a0 if mes >= 7 else a0 + 1, mes, dia)
    except ValueError:
        g = None
    if g and g.weekday() < 5:
        aviso(curso, 'fecha fuera de curso %s → corregida a %s (%s)' % (m.group(0), g.isoformat(), distrito))
        return g
    aviso(curso, 'fecha fuera de curso %s SIN corregir (daría fin de semana o fecha imposible), '
                 'se descarta (%s)' % (m.group(0), distrito))
    return None


# ───────────────────────── lectura de un informe ─────────────────────────

def vuelca(curso, ac, filas, info):
    """Casa fechas y motivos de un distrito entero (todas sus páginas) y añade las filas.
    Las celdas se parten cada una por su lado al cambiar de página, así que el orden
    dentro del distrito manda más que la altura dentro de la página."""
    if not ac:
        return
    distrito, fechas, motivos, esc = ac['nombre'], ac['fechas'], ac['motivos'], ac['esc']
    if not fechas:
        if motivos:
            info['sin_fecha'].append('%s (pág. %d): %s' % (distrito, ac['pag'] + 1, ' / '.join(ac['otros']) or 'sin texto'))
        return
    for k, (pag, y, m) in enumerate(fechas):
        f = a_fecha(m, curso, distrito)
        if len(motivos) == len(fechas):
            mo = motivos[k]
            if mo[0] == pag and not (mo[1] - 9 <= y <= mo[2] + 9):
                aviso(curso, 'pág. %d %s: %s casa por orden con «%s» pero no por altura (revisar)'
                      % (pag + 1, distrito, m.group(0), limpia_motivo(mo[3])))
        elif len(motivos) == 1:
            mo = motivos[0]
        elif motivos:
            def lejos(s):
                if s[0] != pag:
                    return 1e6
                return 0 if s[1] - 2 <= y <= s[2] + 2 else min(abs(s[1] - y), abs(s[2] - y))
            mo = min(motivos, key=lejos)
            aviso(curso, 'pág. %d %s: %d fechas y %d motivos; %s casada por altura con «%s»'
                  % (pag + 1, distrito, len(fechas), len(motivos), m.group(0), limpia_motivo(mo[3])))
        else:
            mo = None
            aviso(curso, 'pág. %d %s: fecha %s sin motivo' % (pag + 1, distrito, m.group(0)))
        if len(esc) == len(fechas):
            ne = esc[k][2]
        else:
            cerca = [e for e in esc if e[0] == pag and abs(e[1] - y) < 16]
            ne = min(cerca, key=lambda e: abs(e[1] - y))[2] if cerca else ''
        if f is None:
            continue
        motivo = limpia_motivo(mo[3]) if mo else ''
        filas.append({'curso': curso, 'distrito_pdf': distrito, 'leaid': '', 'fecha': f.isoformat(),
                      'motivo': motivo, 'tiempo': int(bool(RE_TIEMPO.search(motivo))),
                      'elearning': int('learning' in motivo.lower()), 'escuelas': ne, '_pag': pag})


def lee_pdf(curso, ruta):
    filas, info = [], {'paginas': 0, 'paginas_tabla': [], 'sin_fecha': []}
    pdf = pdfplumber.open(ruta)
    info['paginas'] = len(pdf.pages)
    rol, ac = None, None
    for npag, pg in enumerate(pdf.pages):
        r = bloques_pagina(pg)
        if r is None:
            continue
        _, bloques = r
        primero, usada = True, False
        for a, b, lin in bloques:
            c0 = une_nombre(lin[0])
            if c0.startswith('District') and any('Reason' in t for col in lin for _, t in col):
                rol = papeles(lin)
                if len(c0) > 9:
                    aviso(curso, 'pág. %d: cabecera y distrito en el mismo bloque: «%s»' % (npag + 1, c0))
                continue
            if rol is None or rol['fecha'] is None or rol['motivo'] is None:
                continue
            usada = True
            if c0.lower().startswith('total'):
                vuelca(curso, ac, filas, info)
                ac, primero = None, False
                continue
            continua = False
            if c0:
                hay = any(lin[i] for i in range(1, len(lin)))
                if primero and not hay and ac:
                    # solo el final de un nombre partido entre dos páginas
                    aviso(curso, 'pág. %d: nombre partido entre páginas: «%s» + «%s»' % (npag + 1, ac['nombre'], c0))
                    ac['nombre'] += ' ' + c0
                    primero = False
                    continue
                vuelca(curso, ac, filas, info)
                ac = {'nombre': c0, 'pag': npag, 'fechas': [], 'motivos': [], 'esc': [], 'otros': []}
            elif primero and ac:
                continua = True
            elif not any(lin):
                continue
            else:
                aviso(curso, 'pág. %d: bloque sin nombre de distrito en y=%.0f' % (npag + 1, a))
                continue
            primero = False
            ac['fechas'] += [(npag, y, m) for y, m in lee_fechas(lin[rol['fecha']], curso, ac['nombre'])]
            ac['otros'] += [t for _, t in lin[rol['fecha']] if not RE_FECHA.search(t.replace(' ', ''))]
            segs = trocea_motivos(lin[rol['motivo']])
            if continua and segs and not segs[0][3] and ac['motivos']:
                # el final de un motivo que empezó en la página anterior
                ac['motivos'][-1][3].extend(segs[0][2])
                segs = segs[1:]
            ac['motivos'] += [[npag, s[0], s[1], s[2]] for s in segs]
            if rol['escuelas'] is not None:
                ac['esc'] += [(npag, y, int(t.replace(' ', ''))) for y, t in lin[rol['escuelas']]
                              if t.replace(' ', '').isdigit()]
        if usada:
            info['paginas_tabla'].append(npag)
    vuelca(curso, ac, filas, info)
    return filas, info


# ───────────────────────── distrito → LEAID ─────────────────────────

UNIDADES = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9}
DECENAS = {'ten': 10, 'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50}
# Nombres del informe que no dicen el condado+número de nuestra tabla (a criterio)
ALIAS = [
    (r'lexington and richland|lexington.richland', ('lexington', 5), None),
    (r'rock hill', ('york', 3), None),
    (r'clover', ('york', 2), None),
    (r'fort mill', ('york', 4), None),
    (r'ware shoals', ('greenwood', 51), None),
    (r'blackville', ('barnwell', None), 'Barnwell 19 (Blackville-Hilda), hoy dentro de «Barnwell County»'),
    (r'williston', ('barnwell', None), 'Barnwell 29 (Williston), hoy dentro de «Barnwell County»'),
    (r'florence.*\b4\b', ('florence', 1), 'Florence 4 se integró en Florence 1 en 2022'),
]


def numeros(s):
    """«twenty-nine» → 29, «five» → 5."""
    def sub(m):
        d, u = m.group(1), m.group(2)
        return str(DECENAS.get(d, 0) + UNIDADES.get(u or '', 0)) if d else str(UNIDADES[u])
    pat = r'\b(?:(%s)(?:[- ]+(%s))?|()(%s))\b' % ('|'.join(DECENAS), '|'.join(UNIDADES), '|'.join(UNIDADES))

    def sub2(m):
        if m.group(1):
            return str(DECENAS[m.group(1)] + UNIDADES.get(m.group(2) or '', 0))
        return str(UNIDADES[m.group(4)])
    return re.sub(pat, sub2, s)


def clave_informe(nombre):
    s = numeros(nombre.lower())
    s = re.sub(r'\(.*?\)', ' ', s)
    n = re.search(r'\b(\d{1,2})\b', s)
    base = re.sub(r'\b(the|school|district|of|county|counties|public|schools|sch|consolidated|and|\d+)\b', ' ', s)
    base = re.sub(r'[^a-z ]', ' ', base)
    return re.sub(r'\s+', ' ', base).strip(), (int(n.group(1)) if n else None), s


def casa_leaid(nombres):
    """nombre del informe → (leaid, nota de criterio o None, motivo si no casa)."""
    d = pd.read_csv(BASE / 'fijos' / 'distritos.csv', dtype=str)
    d = d[d.estado == 'SC']
    tabla = {}
    for r in d.itertuples():
        m = re.fullmatch(r'(.+?) (\d+)', r.nombre)
        k = (m.group(1).lower(), int(m.group(2))) if m else (re.sub(r' county$', '', r.nombre.lower()), None)
        tabla[k] = (r.leaid, r.nombre)
    por_base = defaultdict(list)
    for (b, n), v in tabla.items():
        por_base[b].append((n, v))
    out = {}
    for nom in nombres:
        if RE_SIN_LIMITE.search(nom):
            out[nom] = ('', None, 'sin límite territorial')
            continue
        base, n, s = clave_informe(nom)
        nota = None
        k = (base, n)
        for pat, dest, nt in ALIAS:
            if re.search(pat, s):
                k, nota = dest, nt
                break
        if k in tabla:
            out[nom] = (tabla[k][0], (nota + ' → ' + tabla[k][1]) if nota else None, None)
        elif k[1] is not None and (k[0], None) in tabla:
            v = tabla[(k[0], None)]
            out[nom] = (v[0], 'distrito numerado que ya no existe; va al distrito de condado actual → ' + v[1], None)
        elif k[1] is None and len(por_base.get(k[0], [])) == 1:
            v = por_base[k[0]][0][1]
            out[nom] = (v[0], 'el informe no da número; único distrito del condado → ' + v[1], None)
        else:
            out[nom] = ('', None, 'no está en fijos/distritos.csv')
    return out


# ───────────────────────── verificación ─────────────────────────

def texto_bruto(ruta, paginas):
    pdf = pdfplumber.open(ruta)
    return {p: (pdf.pages[p].extract_text() or '') for p in paginas}


def muestra(curso, ruta, filas, n):
    """Imprime n filas junto al texto bruto de su página, primero las de distritos con motivos mezclados."""
    por = defaultdict(list)
    for f in filas:
        por[f['distrito_pdf']].append(f)
    mixtos = [d for d, fs in por.items() if len({x['tiempo'] for x in fs}) > 1]
    elegidas = []
    for d in mixtos[::max(1, len(mixtos) // 4)][:4]:
        elegidas += por[d][:3]
    resto = [f for f in filas if f not in elegidas]
    paso = max(1, len(resto) // max(1, n - len(elegidas)))
    elegidas += resto[paso // 2::paso][:max(0, n - len(elegidas))]
    bruto = texto_bruto(ruta, sorted({f['_pag'] for f in elegidas}))
    print('\n══ Muestra %s ══' % curso)
    for f in elegidas:
        m, d, a = int(f['fecha'][5:7]), int(f['fecha'][8:]), f['fecha'][:4]
        pat = re.compile(r'0?%d\s?/+\s?0?%d\s?/+\s?(%s|%s)' % (m, d, a, a[2:]))
        lin = bruto[f['_pag']].split('\n')
        cand = [i for i, l in enumerate(lin) if pat.search(l)]
        # la enésima aparición de la fecha en la página es la de la enésima fila leída con esa fecha
        mismas = [g for g in filas if g['_pag'] == f['_pag'] and g['fecha'] == f['fecha']]
        j = next(k for k, g in enumerate(mismas) if g is f)
        i = cand[j] if len(cand) == len(mismas) else None
        print('FILA  %s | %s | %s | tiempo=%s elearning=%s escuelas=%s  (pág. %d)' % (
            f['distrito_pdf'], f['fecha'], f['motivo'], f['tiempo'], f['elearning'], f['escuelas'], f['_pag'] + 1))
        if i is None:
            print('   BRUTO: no localizable sin ambigüedad (%d apariciones en la página, %d filas)' % (len(cand), len(mismas)))
        else:
            print('   BRUTO: ' + ' ⏎ '.join(lin[max(0, i - 2):i + 3]))


def main():
    verifica = '--verifica' in sys.argv
    nmues = int(sys.argv[sys.argv.index('--muestra') + 1]) if '--muestra' in sys.argv else 0
    todas, infos = [], {}
    for curso, fich in CURSOS:
        filas, info = lee_pdf(curso, FUE / fich)
        todas += filas
        infos[curso] = (info, filas, FUE / fich)
    mapa = casa_leaid(sorted({f['distrito_pdf'] for f in todas}))
    for f in todas:
        f['leaid'] = mapa[f['distrito_pdf']][0]
    df = pd.DataFrame(todas)
    cols = ['curso', 'distrito_pdf', 'leaid', 'fecha', 'motivo', 'tiempo', 'elearning', 'escuelas']
    df.sort_values(['curso', 'distrito_pdf', 'fecha'], kind='stable')[cols].to_csv(SALIDA, index=False)
    print('Escrito %s: %d filas' % (SALIDA, len(df)))

    print('\n── Resumen por curso ──')
    print('curso    págs tabla filas distritos tiempo elearning  primera     última')
    for curso, _ in CURSOS:
        info, filas, _ = infos[curso]
        s = df[df.curso == curso]
        print('%s %4d %5d %5d %9d %6d %9d  %s  %s' % (
            curso, info['paginas'], len(info['paginas_tabla']), len(s), s.distrito_pdf.nunique(),
            s.tiempo.sum(), s.elearning.sum(), s.fecha.min(), s.fecha.max()))
    dup = df[df.duplicated(['curso', 'distrito_pdf', 'fecha'], keep=False)]
    print('\nFilas con distrito y fecha repetidos (mismo nombre): %d' % len(dup))
    if len(dup):
        print(dup.groupby(['curso', 'distrito_pdf']).size().to_string())
    d2 = df[(df.leaid != '') & df.duplicated(['curso', 'leaid', 'fecha'], keep=False)
            & ~df.duplicated(['curso', 'distrito_pdf', 'fecha'], keep=False)]
    print('Filas de distritos distintos del informe que caen en el mismo leaid y fecha: %d' % len(d2))

    print('\n── Distritos sin fechas (días sin fechar) ──')
    for curso, _ in CURSOS:
        for x in infos[curso][0]['sin_fecha']:
            print('  %s: %s' % (curso, x))

    print('\n── LEAID ──')
    print('Nombres distintos: %d; con leaid: %d' % (len(mapa), sum(1 for v in mapa.values() if v[0])))
    print('Sin leaid:')
    for nom, v in sorted(mapa.items()):
        if not v[0]:
            print('  %-62s %s' % (nom, v[2]))
    print('Casados a criterio:')
    for nom, v in sorted(mapa.items()):
        if v[1]:
            print('  %-50s %s  %s' % (nom, v[0], v[1]))
    sc = pd.read_csv(BASE / 'fijos' / 'distritos.csv', dtype=str)
    sc = sc[sc.estado == 'SC']
    falta = sc[~sc.leaid.isin(set(df.leaid))]
    print('Distritos nuestros de SC sin ninguna fila: %s' % (', '.join(falta.nombre) or 'ninguno'))

    print('\n── Avisos (%d) ──' % len(AVISOS))
    for c, t in AVISOS:
        print('  %s: %s' % (c, t))

    if verifica:
        print('\n── Fechas en el texto bruto frente a filas leídas ──')
        for curso, _ in CURSOS:
            info, filas, ruta = infos[curso]
            bruto = texto_bruto(ruta, info['paginas_tabla'])
            n = sum(len(RE_FECHA_BRUTA.findall(t)) for t in bruto.values())
            # las del pie de página («July 1, 2023») no tienen barras, no cuentan
            print('  %s: %d fechas en el texto, %d filas (%+.1f %%)' % (
                curso, n, len(filas), 100.0 * (len(filas) - n) / max(n, 1)))
        print('\n── Tormentas conocidas: distritos con fila de tiempo ──')
        for f in ('2022-01-18', '2022-01-21', '2025-01-22', '2025-01-23', '2026-01-26'):
            s = df[(df.fecha == f) & (df.tiempo == 1)]
            print('  %s: %3d nombres del informe, %3d leaid distintos (%d eLearning, %d sin clase)' % (
                f, s.distrito_pdf.nunique(), s[s.leaid != ''].leaid.nunique(),
                s[s.elearning == 1].distrito_pdf.nunique(), s[s.elearning == 0].distrito_pdf.nunique()))
    if nmues:
        for curso, _ in CURSOS:
            info, filas, ruta = infos[curso]
            muestra(curso, ruta, filas, nmues)


if __name__ == '__main__':
    main()
