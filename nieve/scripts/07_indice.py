#!/usr/bin/env python3
"""
07_indice.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Índice de probabilidad de que NO haya clases presenciales. BETA: las constantes
de abajo son un punto de partida razonado, todavía SIN calibrar con cierres
reales. Guarda en disco; no publica nada.

Tres preguntas por distrito y mañana:
  1. Nieve  ¿cuánta cae para lo que allí es normal? (tolerancia según la nieve
            anual 1991-2020; en terreno abrupto cuesta más mover los autobuses)
  2. Hielo  la lluvia helada cierra con muy poco, y con menos aún en el sur
  3. Frío   sensación térmica a la hora del autobús, frente a lo habitual allí
Además suma un poco si hay un aviso de invierno del NWS vigente esa mañana.

Cada pregunta da un cociente; se combinan en uno (x) y se pasan a porcentaje con
la curva ajustada con cierres reales (fijos/calibracion.json, de 12_calibra.py:
Kentucky 2024-25). Sin ese fichero se usa la fórmula de partida.

Entrada:  trabajo/dias_<ciclo>.csv (05), trabajo/avisos.csv (05b),
          fijos/clima_nieve.csv, relieve.csv, escuelas.csv, distritos.csv
Salida:   archivo/<AAAAMM>/indice_<ciclo>.csv.gz   todo, una fila por distrito y mañana
          salida/actual/<AAAA-MM-DD>.json          lo que leerá la web, un fichero por mañana
          salida/actual/manifest.json
          salida/actual/resumen.json               recuentos y distritos más altos (caja de la web y L-bar)
          (con --prueba todo va a salida/prueba y no se usan avisos)

Solo entran los distritos con escuelas (12.980).

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 07_indice.py [--ciclo AAAAMMDD_HH] [--prueba]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import nbm_comun as nc

sys.path.insert(0, str(nc.BASE / 'scripts'))
EVENTOS = __import__('05b_avisos').EVENTOS

# ── Constantes del índice (sin calibrar) ────────────────────────────
PESO_CLASE = 0.6        # la nieve en horario de clase cuenta menos que la de la noche
PESO_TARDE = 0.4        # la de la tarde anterior, menos: da tiempo a limpiar
TOL_BASE, TOL_RAIZ = 0.8, 0.55      # tolerancia (in) = 0,8 + 0,55·√(nieve anual)
RELIEVE_MAX = 0.25      # hasta +25 % de impacto en terreno muy abrupto (rugosidad ≥ 100 m)
HIELO_BASE, HIELO_RAIZ = 0.05, 0.02  # tolerancia al hielo (in)
FRIO_BASE, FRIO_RAIZ = 10.0, 4.5    # sensación (°F) que cierra = 10 − 4,5·√(nieve anual), entre −35 y 10
FRIO_MARGEN = 15.0      # el frío empieza a contar 15 °F antes de ese umbral
PENDIENTE = 2.5         # cociente 0,5 → 15 %, 1 → 50 %, 2 → 85 %
PRUDENCIA = {1: 1.0, 2: 0.8, 3: 0.6}   # por día de antelación
TECHO = 90              # nunca 100 %
ETIQUETAS = [(70, 'Muy probable'), (50, 'Probable'), (30, 'Posible'), (10, 'Poco probable'), (0, 'Muy improbable')]
# Curva ajustada con cierres reales de Kentucky y Carolina del Sur. Allí, una señal pequeña de invierno
# ya cierra a parte de los distritos. Eso NO está comprobado donde nieva mucho, y sería falso (en
# Búfalo cae algo casi cada día): las probabilidades bajas y medias se rebajan según la nieve anual.
_CAL = nc.FIJOS / 'calibracion.json'
CAL = json.loads(_CAL.read_text(encoding='utf-8')) if _CAL.exists() else None
NIEVE_REF = 20.0        # in/año: hasta aquí la curva se aplica tal cual (Kentucky tiene 5-20)
REBAJA_MIN = 0.25       # donde más nieva, las señales pequeñas valen la cuarta parte


def prob_ajustada(x, ant, anual):
    """x (cociente) → probabilidad (0-1) con la curva de calibracion.json."""
    p = np.zeros(len(x))
    for a in (1, 2, 3):
        c, m = CAL['antelacion'][str(a)], (ant == a)
        p[m] = np.interp(np.log(np.maximum(x[m], CAL['x_min'])), np.log(c['x']), c['p'])
    f = np.clip(NIEVE_REF / np.maximum(anual, 0.1), REBAJA_MIN, 1.0)
    w = np.clip((p - 0.45) / 0.25, 0, 1)      # por encima del 70 % ya no se rebaja nada
    return p * (f + (1 - f) * w)


def frio_extremo(sens, N):
    """Regla aparte para el frío extremo, SIN ajustar con datos (los dos estados probados casi nunca llegan):
    50 % cuando la sensación a la hora del autobús baja al umbral habitual de cierre, de −15 °F donde nieva
    poco a −35 °F donde nieva mucho. Se combina con la curva: p = 1 − (1 − p_curva)·(1 − p_frío)."""
    umbral = -15.0 - 20.0 * np.clip((np.asarray(N, dtype='float64') - 15.0) / 30.0, 0, 1)
    s = np.where(np.isfinite(sens), sens, 60.0)
    return 1.0 / (1.0 + np.exp((s - umbral) / 4.0))


RECIENTES = nc.BASE / 'trabajo' / 'nieve_dias.csv'     # lo previsto para cada mañana ya pasada (últimos días)
PESOS_RECIENTE = ((1, 1.0), (2, 0.7), (3, 0.4))


def nieve_reciente(r, fc, guardar):
    """Nieve prevista para los tres días anteriores a cada mañana, con menos peso cuanto más atrás y solo si la
    noche sigue helando. Un día que ya pasó sale de lo que se pronosticó para él (trabajo/nieve_dias.csv, que
    este mismo programa va guardando); uno que aún no ha llegado, de este mismo ciclo. Los días sin clase
    (fines de semana) no tienen fila, así que su nieve no se ve."""
    r['f'] = pd.to_datetime(r['fecha'])
    dias_ant = (r['f'] - pd.Timestamp(fc)).dt.days
    pasado = pd.read_csv(RECIENTES, dtype={'leaid': str}, parse_dates=['f']) if RECIENTES.exists() else pd.DataFrame({'leaid': pd.Series(dtype='str'), 'f': pd.Series(dtype='datetime64[ns]'), 'S1': pd.Series(dtype='float64')})
    mismo = r[['leaid', 'f', 'S1']].drop_duplicates(['leaid', 'f'])
    previa = np.zeros(len(r))
    for j, peso in PESOS_RECIENTE:
        a = pasado.assign(f=pasado['f'] + pd.Timedelta(days=j)).rename(columns={'S1': 'pa'})[['leaid', 'f', 'pa']]
        b = mismo.assign(f=mismo['f'] + pd.Timedelta(days=j)).rename(columns={'S1': 'pb'})
        m = r[['leaid', 'f']].merge(a, on=['leaid', 'f'], how='left').merge(b, on=['leaid', 'f'], how='left')
        previa += peso * np.where(dias_ant.to_numpy() <= j, pd.to_numeric(m['pa'], errors='coerce').fillna(0).to_numpy(dtype='float64'),
                                  pd.to_numeric(m['pb'], errors='coerce').fillna(0).to_numpy(dtype='float64'))
    if guardar:
        # Se guarda lo previsto para las mañanas a un día o menos (el pronóstico más reciente de cada una)
        nuevo = r.loc[dias_ant <= 1, ['leaid', 'f', 'S1']]
        todo = pd.concat([pasado[~pasado['f'].isin(nuevo['f'].unique())], nuevo], ignore_index=True)
        todo = todo[todo['f'] >= pd.Timestamp(fc) - pd.Timedelta(days=6)]
        todo.assign(S1=todo['S1'].round(3)).to_csv(RECIENTES, index=False)
    del r['f']
    return previa * np.clip((34 - r['temp_min_noche_f'].fillna(40).to_numpy()) / 8.0, 0, 1)


# Lo que lee la web de cada distrito, en este orden
CAMPOS = ['pct', 'nieve_noche_in', 'nieve_clase_in', 'hielo_in', 'sens_bus_f', 'temp_min_noche_f', 'racha_max_mph', 'dia']


def log(msg):
    print(msg, flush=True)


def fmt(x, dec=1):
    return f'{x:.{dec}f}'.replace('.', ',')


def motivo(f):
    """Frase de plantilla con el factor que más pesa."""
    if f['pct'] < 10:
        return ''
    cola = ('; ' + f['aviso'][0].lower() + f['aviso'][1:] + ' del NWS') if f['aviso'] else ''
    if f['p_frio'] >= 0.3:
        return f'Sensación térmica de {f["sens_bus_f"]:.0f} °F a la hora del autobús' + cola
    k = max(('nieve', 'hielo', 'frio', 'reciente'), key=lambda c: f[f'r_{c}'])
    if k == 'reciente':
        return 'Nieve de los días anteriores y noche bajo cero' + cola
    if k == 'nieve' and f['nieve_noche_in'] < 0.05 and f['nieve_clase_in'] < 0.05:
        return 'Algo de nieve la tarde anterior' + ('; ' + f['aviso'][0].lower() + f['aviso'][1:] + ' del NWS' if f['aviso'] else '')
    if max(f['r_nieve'], f['r_hielo'], f['r_frio'], f['r_reciente']) < 0.15 and f['aviso']:
        return f'{f["aviso"]} del NWS'
    if k == 'nieve':
        t = f'{fmt(f["nieve_noche_in"])} in de nieve antes de las 7:00'
        if f['nieve_clase_in'] >= 0.5:
            t += f' y {fmt(f["nieve_clase_in"])} in en horario de clase'
        if f['nieve_anual_in'] < 10:
            t += '; zona poco habituada a la nieve'
    elif k == 'hielo':
        t = f'{fmt(f["hielo_in"], 2)} in de lluvia helada'
    else:
        t = f'Sensación térmica de {f["sens_bus_f"]:.0f} °F a la hora del autobús'
    if f['aviso']:
        t += f'; {f["aviso"][0].lower()}{f["aviso"][1:]} del NWS'
    return t


def avisos_por_manana(r):
    """Aviso de más peso vigente entre las 18:00 de la víspera y las 15:00 de cada mañana."""
    r['aviso'], r['r_aviso'] = '', 0.0
    ruta = nc.BASE / 'trabajo' / 'avisos.csv'
    if not ruta.exists():
        return r
    av = pd.read_csv(ruta, dtype={'leaid': str})
    if not len(av):
        return r
    for c in ('desde', 'hasta'):
        av[c] = pd.to_datetime(av[c], utc=True)
    v0, v1 = {}, {}
    for (tz, fecha) in r[['tz', 'fecha']].drop_duplicates().itertuples(index=False):
        d = datetime.strptime(fecha, '%Y-%m-%d').replace(tzinfo=ZoneInfo(tz))
        v0[(tz, fecha)] = (d - timedelta(hours=6)).astimezone(timezone.utc)
        v1[(tz, fecha)] = (d + timedelta(hours=15)).astimezone(timezone.utc)
    clave = list(zip(r['tz'], r['fecha']))
    m = r[['leaid', 'fecha']].assign(v0=pd.to_datetime([v0[k] for k in clave], utc=True),
                                     v1=pd.to_datetime([v1[k] for k in clave], utc=True)).merge(av, on='leaid')
    m = m[(m['desde'].isna() | (m['desde'] < m['v1'])) & (m['hasta'].isna() | (m['hasta'] > m['v0']))]
    if not len(m):
        return r
    m['peso'] = m['evento'].map(EVENTOS)
    m = m.sort_values('peso', ascending=False).drop_duplicates(['leaid', 'fecha']).set_index(['leaid', 'fecha'])
    idx = pd.MultiIndex.from_frame(r[['leaid', 'fecha']])
    r['aviso'] = m['evento_es'].reindex(idx).fillna('').to_numpy()
    r['r_aviso'] = m['peso'].reindex(idx).fillna(0).to_numpy()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ciclo')
    ap.add_argument('--prueba', action='store_true')
    a = ap.parse_args()
    trab = nc.BASE / 'trabajo'
    ruta = trab / f'dias_{a.ciclo}.csv' if a.ciclo else sorted(trab.glob('dias_*.csv'))[-1]
    ciclo = ruta.stem.replace('dias_', '')

    r = pd.read_csv(ruta, dtype={'leaid': str})
    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})[['leaid', 'nombre', 'estado', 'tz']]
    esc = pd.read_csv(nc.FIJOS / 'escuelas.csv', dtype={'leaid': str})[['leaid', 'n_escuelas', 'rural_pct']]
    r = r.merge(pd.read_csv(nc.FIJOS / 'clima_nieve.csv', dtype={'leaid': str}), on='leaid') \
         .merge(pd.read_csv(nc.FIJOS / 'relieve.csv', dtype={'leaid': str}), on='leaid').merge(d, on='leaid').merge(esc, on='leaid')
    r = r[r['n_escuelas'] > 0].reset_index(drop=True)
    raiz = np.sqrt(r['nieve_anual_in'])

    # Lo que se enseña va con un decimal; el motivo debe decir lo mismo que la ficha
    for c in ('nieve_tarde_in', 'nieve_noche_in', 'nieve_clase_in'):
        r[c] = r[c].round(1)

    # 1. Nieve
    nieve = r['nieve_noche_in'].fillna(0) + PESO_CLASE * r['nieve_clase_in'].fillna(0) + PESO_TARDE * r['nieve_tarde_in'].fillna(0)
    r['tol_nieve_in'] = (TOL_BASE + TOL_RAIZ * raiz).round(1)
    r['r_nieve'] = nieve / r['tol_nieve_in'] * (1 + RELIEVE_MAX * np.minimum(r['rugosidad_m'] / 100.0, 1))
    # 2. Hielo
    r['hielo_in'] = (r['hielo_noche_in'].fillna(0) + PESO_CLASE * r['hielo_clase_in'].fillna(0)).round(2)
    r['r_hielo'] = r['hielo_in'] / (HIELO_BASE + HIELO_RAIZ * raiz)
    # 3. Frío
    umbral = np.clip(FRIO_BASE - FRIO_RAIZ * raiz, -35, 10)
    r['r_frio'] = np.clip((umbral + FRIO_MARGEN - r['sens_bus_f']) / FRIO_MARGEN, 0, None).fillna(0)
    # Tolerancia reajustada con cierres reales de dos estados (16_reajuste.py): crece casi en proporción a la
    # nieve anual hasta 20 in y, por encima, con la raíz (supuesto: no hay ningún estado nevado probado).
    if CAL and 'tolerancia' in CAL:
        tp, N = CAL['tolerancia'], r['nieve_anual_in'].to_numpy(dtype='float64')
        T = tp['t12'] * ((np.minimum(N, tp['n_tope']) + tp['n0']) / (tp['n_ref'] + tp['n0'])) ** tp['k'] \
            * np.sqrt((np.maximum(N, tp['n_tope']) + tp['n0']) / (tp['n_tope'] + tp['n0']))
        r['tol_nieve_in'] = np.round(T, 1)
        r['r_nieve'] = nieve * (1 + RELIEVE_MAX * np.minimum(r['rugosidad_m'] / 100.0, 1)) / T
        r['r_hielo'] = r['hielo_in'] * tp['hielo'] / T
        r['r_frio'] = r['r_frio'] * tp['frio']
        r['S1'] = nieve * (1 + RELIEVE_MAX * np.minimum(r['rugosidad_m'] / 100.0, 1)) + 10 * r['hielo_in']
        fc0 = datetime.strptime(ciclo[:8], '%Y%m%d').date()
        r['nieve_reciente_in'] = np.round(nieve_reciente(r, fc0, not a.prueba), 2)
        r['r_reciente'] = tp.get('reciente', 0) * r['nieve_reciente_in'] / T
    else:
        r['nieve_reciente_in'], r['r_reciente'] = 0.0, 0.0
    # Avisos del NWS
    if a.prueba:
        r['aviso'], r['r_aviso'] = '', 0.0
    else:
        r = avisos_por_manana(r)

    x = np.sqrt(r['r_nieve'] ** 2 + r['r_hielo'] ** 2 + r['r_frio'] ** 2 + r['r_reciente'] ** 2) + r['r_aviso']
    if CAL:
        # Antelación en días naturales entre el ciclo del NBM y la mañana (1 = la tarde anterior)
        fc = datetime.strptime(ciclo[:8], '%Y%m%d').date()
        r['ant'] = [min(max((datetime.strptime(f, '%Y-%m-%d').date() - fc).days, 1), 3) for f in r['fecha']]
        pc = prob_ajustada(x.to_numpy(), r['ant'].to_numpy(), r['nieve_anual_in'].to_numpy())
        r['p_frio'] = frio_extremo(r['sens_bus_f'].to_numpy(dtype='float64'), r['nieve_anual_in'].to_numpy()) if 'tolerancia' in CAL else 0.0
        p = pd.Series((1 - (1 - pc) * (1 - r['p_frio'])) * 100, index=r.index)
    else:
        p = x ** PENDIENTE / (1 + x ** PENDIENTE) * r['dia'].map(PRUDENCIA) * 100
        r['p_frio'] = 0.0
    r['pct_fino'] = p.round(1)
    # De 10 en 10; por debajo de 10 queda 5 («menos del 10 %») o 0
    r['pct'] = np.where(p >= 9.5, np.minimum(np.round(p / 10) * 10, TECHO), np.where(p >= 3, 5, 0)).astype(int)
    r['etiqueta'] = r['pct'].map(lambda v: next(e for u, e in ETIQUETAS if v >= u))
    r['motivo'] = r.apply(motivo, axis=1)
    r[['r_nieve', 'r_hielo', 'r_frio', 'r_reciente', 'p_frio']] = r[['r_nieve', 'r_hielo', 'r_frio', 'r_reciente', 'p_frio']].round(2)

    hecho = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    cols = ['leaid', 'dia', 'fecha', 'pct', 'etiqueta', 'motivo', 'aviso', 'pct_fino', 'r_nieve', 'r_hielo', 'r_frio', 'r_reciente', 'p_frio', 'r_aviso',
            'tol_nieve_in', 'nieve_anual_in', 'nieve_reciente_in', 'nieve_tarde_in', 'nieve_noche_in', 'nieve_clase_in', 'hielo_in',
            'sens_bus_f', 'temp_min_noche_f', 'racha_max_mph', 'suelo_in', 'cobertura_noche', 'detalle']
    if a.prueba:
        sal = nc.BASE / 'salida' / 'prueba'
        sal.mkdir(parents=True, exist_ok=True)
        r[cols].to_csv(sal / f'indice_{ciclo}.csv', index=False)
    else:
        arch = nc.BASE / 'archivo' / ciclo[:6]
        arch.mkdir(parents=True, exist_ok=True)
        r[cols].assign(hecho=hecho).to_csv(arch / f'indice_{ciclo}.csv.gz', index=False)
        sal = nc.BASE / 'salida' / 'actual'
        sal.mkdir(parents=True, exist_ok=True)

    # Un fichero por mañana (la misma fecha puede ser «día 1» en una zona horaria y «día 2» en otra)
    fechas = []
    for fecha, g in r.groupby('fecha'):
        if len(g) < 0.5 * r['leaid'].nunique():
            continue  # fecha que solo toca a unas pocas zonas horarias
        num = g[CAMPOS].round(1).astype(object).where(g[CAMPOS].notna(), None)
        doc = {
            'meta': dict(fecha=fecha, hecho=hecho, ciclo_nbm=ciclo, modo='beta', campos=CAMPOS, distritos=len(g),
                         reparto={str(v): int(n) for v, n in g['pct'].value_counts().sort_index().items()}),
            'd': dict(zip(g['leaid'], num.values.tolist())),
            'm': {i: t for i, t in zip(g['leaid'], g['motivo']) if t},
            'a': {i: t for i, t in zip(g['leaid'], g['aviso']) if t},
        }
        (sal / f'{fecha}.json').write_text(json.dumps(doc, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
        fechas.append(fecha)
    if not a.prueba:
        (sal / 'manifest.json').write_text(json.dumps(dict(hecho=hecho, ciclo_nbm=ciclo, modo='beta', fechas=fechas)), encoding='utf-8')
        for f in sal.glob('20*.json'):
            if f.stem not in fechas:
                f.unlink()
        # Resumen ligero (2-3 kB) para la caja de www.canalmeteo.tv y la L-bar: recuentos, estados y distritos más altos
        res = []
        for fecha in fechas:
            g = r[r['fecha'] == fecha]
            est = g[g['pct'] >= 30].groupby('estado').size().sort_values(ascending=False).head(8)
            alto = g[g['pct'] >= 10].sort_values(['pct', 'n_escuelas'], ascending=False).head(18)
            res.append(dict(fecha=fecha, distritos=int(len(g)), n10=int((g['pct'] >= 10).sum()), n30=int((g['pct'] >= 30).sum()),
                            n50=int((g['pct'] >= 50).sum()), estados=[[k, int(v)] for k, v in est.items()],
                            top=[[a, b, c, int(d_)] for a, b, c, d_ in zip(alto['leaid'], alto['nombre'], alto['estado'], alto['pct'])]))
        (sal / 'resumen.json').write_text(json.dumps(dict(hecho=hecho, ciclo_nbm=ciclo, modo='beta', dias=res), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    log(f'── Índice beta · ciclo {ciclo} · {r["leaid"].nunique()} distritos · {hecho} ──')
    for fecha, g in r.groupby('fecha'):
        rep = g['pct'].value_counts().sort_index()
        log(f'{fecha} ({len(g)}): ' + ', '.join(f'{v} %: {n}' for v, n in rep.items()) + f' · con aviso: {(g["aviso"] != "").sum()}')
        top = g[g['pct'] >= 10].nlargest(5, 'pct_fino')
        for _, f in top.iterrows():
            log(f'    {f["pct"]:3d} %  {f["nombre"]}, {f["estado"]} — {f["motivo"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
