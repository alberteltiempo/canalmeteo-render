#!/usr/bin/env python3
"""
11_backtest_ky.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Prueba del índice contra cierres REALES: Kentucky, invierno 2024-25.

Verdad: los calendarios enmendados que cada distrito presenta al Departamento
de Educación de Kentucky (KDE), con la fecha exacta de cada «Weather Day».
  fuentes/cierres_ky/amended_2425.xlsx
Pronóstico: el del NBM de la tarde anterior (ciclo de las 23 UTC, ~6 PM ET),
sacado del archivo de NOAA en AWS, con el mismo código que la web (05 y 07).

Límite conocido: los días de clase a distancia por nieve (NTI) NO vienen
fechados; esas mañanas constan como «hubo clase». Por eso el resultado se da
también solo con los distritos que usaron 3 días NTI o menos.

Salida:  salida/backtest/ky_2425.csv        una fila por distrito, mañana y antelación
         salida/backtest/ky_2425_resumen.json  tabla de fiabilidad (lo que lee la web)

Uso:
  11_backtest_ky.py            lanza todos los ciclos que falten y resume
  11_backtest_ky.py --resumen  solo recalcula el resumen
"""
import json
import re
import subprocess
import sys
import unicodedata
from datetime import date, datetime, timedelta

import openpyxl
import pandas as pd

import nbm_comun as nc

PY = str(nc.BASE / 'venv' / 'bin' / 'python3')
SCR = nc.BASE / 'scripts'
SAL = nc.BASE / 'salida' / 'backtest'
INICIO, FIN = date(2024, 12, 1), date(2025, 3, 14)
CICLO = 23
NO_LECTIVO = ['Professional Development Days', 'Holiday Days', 'Planning Days', 'Fall Break Days', 'Winter Break Days',
              'Spring Break Days', 'Other Break Days', 'Illness Days', 'District Wide Disaster Days']


def log(msg):
    print(msg, flush=True)


def fechas(celda):
    out = set()
    for m in re.findall(r'(\d{2})/(\d{2})/(\d{2,4})', str(celda or '')):
        a = int(m[2]) + (2000 if len(m[2]) == 2 else 0)
        try:
            out.add(date(a, int(m[0]), int(m[1])))
        except ValueError:
            pass
    return out


def clave(s):
    s = unicodedata.normalize('NFD', s.lower())
    s = ''.join(c for c in s if c.isalnum() or c == ' ')
    # En nuestra tabla los «Independent» van sin la coletilla (Anchorage Independent → Anchorage)
    for q in (' public schools', ' schools', ' school district', ' independent', ' ind'):
        if s.endswith(q):
            s = s[:-len(q)]
    return ' '.join(s.split())


def lee_verdad():
    ws = openpyxl.load_workbook(nc.BASE / 'fuentes' / 'cierres_ky' / 'amended_2425.xlsx', read_only=True, data_only=True).worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    cab = [str(c or '').strip() for c in filas[0]]
    col = {c: i for i, c in enumerate(cab)}
    nti = next((i for i, c in enumerate(cab) if 'NTI' in c.upper() and 'USED' in c.upper()), None)
    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})
    ky = {clave(n): i for i, n in zip(d.loc[d['estado'] == 'KY', 'leaid'], d.loc[d['estado'] == 'KY', 'nombre'])}
    verdad, sin = {}, []
    for f in filas[1:]:
        if not f or not f[col['District Name']]:
            continue
        nombre = str(f[col['District Name']]).strip()
        leaid = ky.get(clave(nombre))
        if not leaid:
            sin.append(nombre)
            continue

        def dia(c):
            try:
                return datetime.strptime(str(f[col[c]]).strip(), '%m/%d/%Y').date()
            except (ValueError, TypeError):
                return None
        no = set()
        for c in NO_LECTIVO:
            if c in col:
                no |= fechas(f[col[c]])
        try:
            n_nti = int(float(f[nti])) if nti is not None and f[nti] not in (None, '') else None
        except (TypeError, ValueError):
            n_nti = None
        verdad[leaid] = dict(nombre=nombre, cierres=fechas(f[col['Weather Days']]), no_lectivo=no,
                             primero=dia('Students First Day'), ultimo=dia('Students Last Day'), nti=n_nti)
    log(f'KDE: {len(verdad)} distritos casados con su LEAID · sin casar: {len(sin)} {sin[:8]}')
    n = pd.Series([v['nti'] for v in verdad.values()], dtype='float')
    log(f'  días NTI usados por distrito: mediana {n.median():.0f} · con 0: {(n == 0).sum()} · con 3 o menos: {(n <= 3).sum()} · sin dato: {n.isna().sum()}')
    log(f'  cierres por el tiempo fechados entre {INICIO} y {FIN}: '
        f'{sum(len([x for x in v["cierres"] if INICIO <= x <= FIN]) for v in verdad.values())}')
    return verdad


def corre(verdad):
    SAL.mkdir(parents=True, exist_ok=True)
    salida = SAL / 'ky_2425.csv'
    hechos = set(pd.read_csv(salida, usecols=['ciclo'])['ciclo']) if salida.exists() else set()
    d = INICIO
    while d <= FIN:
        ciclo = f'{d:%Y%m%d}_{CICLO:02d}'
        d += timedelta(days=1)
        if ciclo in hechos:
            continue
        r = subprocess.run(['nice', '-n', '12', PY, str(SCR / '05_extrae_nbm.py'), '--fecha', ciclo[:8], '--ciclo', str(CICLO), '--dias', '3'],
                           cwd=SCR, capture_output=True, text=True)
        dias = nc.BASE / 'trabajo' / f'dias_{ciclo}.csv'
        if r.returncode or not dias.exists():
            log(f'{ciclo}: sin datos del NBM ({(r.stderr or r.stdout).strip()[-120:]})')
            continue
        subprocess.run([PY, str(SCR / '07_indice.py'), '--prueba', '--ciclo', ciclo], cwd=SCR, capture_output=True, text=True)
        ind = nc.BASE / 'salida' / 'prueba' / f'indice_{ciclo}.csv'
        if ind.exists():
            x = pd.read_csv(ind, dtype={'leaid': str})
            x = x[x['leaid'].isin(verdad)].copy()
            x['ciclo'] = ciclo
            x.to_csv(salida, mode='a', header=not salida.exists(), index=False)
            log(f'{ciclo}: {len(x)} filas · máx {x["pct"].max()} %')
            ind.unlink()
        for f in (dias, nc.BASE / 'trabajo' / f'nbm_{ciclo}.npz'):
            f.unlink(missing_ok=True)


def resume(verdad):
    x = pd.read_csv(SAL / 'ky_2425.csv', dtype={'leaid': str})
    x['f'] = pd.to_datetime(x['fecha']).dt.date
    v = x['leaid'].map(verdad)
    x['lectivo'] = [(q['primero'] is None or f >= q['primero']) and (q['ultimo'] is None or f <= q['ultimo']) and f not in q['no_lectivo']
                    or f in q['cierres'] for q, f in zip(v, x['f'])]
    x['cerro'] = [f in q['cierres'] for q, f in zip(v, x['f'])]
    x['nti'] = [q['nti'] for q in v]
    x = x[x['lectivo']]
    res = dict(estado='KY', invierno='2024-25', hecho=datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), ciclos=int(x['ciclo'].nunique()),
               distritos=int(x['leaid'].nunique()), grupos={})
    for nombre, sel in (('todos', x), ('pocos_nti', x[x['nti'] <= 3])):
        g = {}
        for dia in (1, 2, 3):
            y = sel[sel['dia'] == dia]
            if not len(y):
                continue
            p = y['pct'].clip(lower=5) / 100.0
            tabla = y.groupby('pct')['cerro'].agg(['size', 'sum']).reset_index()
            g[str(dia)] = dict(
                mananas=int(len(y)), cierres=int(y['cerro'].sum()), distritos=int(y['leaid'].nunique()),
                brier=round(float(((p - y['cerro']) ** 2).mean()), 4),
                brier_base=round(float(((y['cerro'].mean() - y['cerro']) ** 2).mean()), 4),
                pasos=[dict(pct=int(r.pct), mananas=int(r.size), cerraron=int(r.sum), de_100=round(100 * r.sum / r.size, 1)) for r in tabla.itertuples()],
                avisados=int(((y['pct'] >= 50) & y['cerro']).sum()), cierres_con_30=int(((y['pct'] >= 30) & y['cerro']).sum()))
        res['grupos'][nombre] = g
    # El día de más cierres, con la antelación de un día
    y = x[(x['dia'] == 1) & x['cerro']]
    if len(y):
        top = y.groupby('fecha').size().idxmax()
        z = x[(x['dia'] == 1) & (x['fecha'] == top)]
        res['tormenta'] = dict(fecha=top, cerraron=int(z['cerro'].sum()), con_50=int(((z['pct'] >= 50) & z['cerro']).sum()),
                               con_30=int(((z['pct'] >= 30) & z['cerro']).sum()), abiertos_con_50=int(((z['pct'] >= 50) & ~z['cerro']).sum()),
                               distritos=int(len(z)))
    (SAL / 'ky_2425_resumen.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    for nombre, g in res['grupos'].items():
        for dia, q in g.items():
            log(f'── {nombre} · antelación {dia} · {q["mananas"]} mañanas, {q["cierres"]} cierres · Brier {q["brier"]} (referencia {q["brier_base"]})')
            log('   ' + ' | '.join(f'{p["pct"]} %: {p["de_100"]} de 100 ({p["mananas"]})' for p in q['pasos']))
    log(f'tormenta: {res.get("tormenta")}')


def main():
    verdad = lee_verdad()
    if '--resumen' not in sys.argv:
        corre(verdad)
    resume(verdad)
    return 0


if __name__ == '__main__':
    sys.exit(main())
