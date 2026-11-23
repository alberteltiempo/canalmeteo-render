#!/usr/bin/env python3
"""
15_calibra_estados.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Ajusta la curva cociente → probabilidad con los cierres REALES de dos estados
y deja las tablas de fiabilidad que enseña la página de aciertos. Sustituye a
12_calibra.py (que solo usaba Kentucky).

  Kentucky 2024-25         salida/backtest/ky_2425.csv  (11_backtest_ky.py)
                           solo los distritos con 3 días NTI o menos: en los
                           demás, la clase a distancia no tiene fecha
  Carolina del Sur         salida/backtest/sc.csv       (14_backtest_sc.py)
  2021-22 a 2025-26        verdad: fuentes/cierres_sc/cierres_sc.csv; cuenta
                           como «sin clase presencial» el cierre y el eLearning

Curva: monótona, sin forma impuesta (isotónica sobre ln x), una sola para las
tres antelaciones y los dos estados. Se evalúa FUERA DE MUESTRA dejando fuera
grupos de distritos, y además cada estado con una curva hecha solo con el otro.

Días de clase en Carolina del Sur: los informes no traen el calendario, así que
se toman los laborables no festivos del 1-dic al 15-mar, sin el 20-dic a 5-ene.

Salida:  fijos/calibracion.json
         salida/backtest/ky_2425_resumen.json, sc_resumen.json
"""
import importlib.util
import json
import sys
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold

import nbm_comun as nc


def _mod(nombre):
    s = importlib.util.spec_from_file_location(nombre, nc.BASE / 'scripts' / f'{nombre}.py')
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


bt = _mod('11_backtest_ky')
ex = _mod('05_extrae_nbm')

SAL = nc.BASE / 'salida' / 'backtest'
X_MIN = 0.02
REJILLA = [0.02, 0.04, 0.06, 0.1, 0.2, 0.4, 0.7, 1.0, 1.25, 1.5, 1.8, 2.2, 3.0, 4.0]
LREJ = np.log(REJILLA)
TECHO = 0.9
PASOS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]


def log(msg):
    print(msg, flush=True)


def curva(lx, y):
    m = IsotonicRegression(y_min=0, y_max=1, out_of_bounds='clip').fit(lx, y)
    return np.minimum(np.maximum.accumulate(m.predict(LREJ)), TECHO)


def paso(p):
    q = np.minimum(np.round(p * 10) * 10, 90)
    return np.where(p >= 0.095, q, 0).astype(int)


def tabla(pct, y):
    return [dict(pct=int(s), mananas=int((pct == s).sum()), cerraron=int(y[pct == s].sum()), de_100=round(100 * float(y[pct == s].mean()), 1))
            for s in PASOS if (pct == s).sum()]


def brier(p, y):
    return round(float(((np.clip(p, 0, TECHO) - y) ** 2).mean()), 4)


def prepara(x):
    x['f'] = pd.to_datetime(x['fecha']).dt.date
    x['fc'] = pd.to_datetime(x['ciclo'].str[:8]).dt.date
    x['ant'] = [(a - b).days for a, b in zip(x['f'], x['fc'])]     # 1 = la tarde anterior
    x = x[x['ant'].between(1, 3)].copy()
    x['x'] = np.sqrt(x['r_nieve'] ** 2 + x['r_hielo'] ** 2 + x['r_frio'] ** 2)
    x['lx'] = np.log(np.maximum(x['x'], X_MIN))
    return x


def kentucky():
    verdad = bt.lee_verdad()
    x = prepara(pd.read_csv(SAL / 'ky_2425.csv', dtype={'leaid': str}, low_memory=False))
    v = x['leaid'].map(verdad)
    x['y'] = [int(f in q['cierres']) for q, f in zip(v, x['f'])]
    lect = [((q['primero'] is None or f >= q['primero']) and (q['ultimo'] is None or f <= q['ultimo']) and f not in q['no_lectivo']) or f in q['cierres']
            for q, f in zip(v, x['f'])]
    x['nti'] = [q['nti'] for q in v]
    x['invierno'] = '2024-25'
    x = x[lect]
    return x[x['nti'] <= 3].copy(), x


def carolina():
    c = pd.read_csv(nc.BASE / 'fuentes' / 'cierres_sc' / 'cierres_sc.csv', dtype={'leaid': str})
    c = c[(c['tiempo'] == 1) & c['leaid'].notna()]
    sin = set(zip(c['leaid'], c['fecha']))       # cierre o eLearning por el tiempo: sin clase presencial
    x = prepara(pd.read_csv(SAL / 'sc.csv', dtype={'leaid': str}, low_memory=False))
    x['y'] = [int((i, f) in sin) for i, f in zip(x['leaid'], x['fecha'])]

    def lectivo(f):
        if f.weekday() >= 5 or ex.festivo(f):
            return False
        if (f.month == 12 and f.day >= 20) or (f.month == 1 and f.day <= 5):
            return False
        return (f.month == 12) or (f.month in (1, 2)) or (f.month == 3 and f.day <= 15)
    x = x[[lectivo(f) or bool(y) for f, y in zip(x['f'], x['y'])]].copy()
    return x


CODIGOS_IL = {'ED', 'XELD', 'XRLD', 'AOG'}      # emergencia, e-learning, clase a distancia, fuerza mayor


def illinois():
    """Illinois 2021-22 a 2025-26: calendario final de cada distrito, día a día (17_cierres_il.py, consulta
    pública del ISBE). Día de clase: cualquier código que empiece por X (asistencia), más los de cierre.
    Sin clase presencial: día de emergencia, e-learning, clase a distancia o fuerza mayor. El calendario no
    dice el motivo: entra también alguna avería o amenaza, que aquí cuenta como fallo del pronóstico."""
    f = nc.BASE / 'fuentes' / 'cierres_il'
    c = pd.read_csv(f / 'dias.csv', dtype=str).fillna('')
    cr = pd.read_csv(f / 'cruce_il.csv', dtype=str)
    c['rcdts11'] = c['rcdts'].str[:11]
    c = c.merge(cr[['leaid', 'rcdts11']], on='rcdts11')
    c['y'] = c['codigo'].isin(CODIGOS_IL).astype(int)
    c = c[c['codigo'].str.startswith('X') | (c['y'] == 1)]
    c = c.groupby(['leaid', 'fecha'], as_index=False)['y'].max()
    x = prepara(pd.read_csv(SAL / 'il.csv', dtype={'leaid': str}, low_memory=False))
    return x.merge(c, on=['leaid', 'fecha'])


def resumen(nombre, d, oof, p_final, extra):
    """Tablas por antelación con la predicción fuera de muestra."""
    res = dict(estado=nombre, hecho=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), distritos=int(d['leaid'].nunique()),
               ciclos=int(d['ciclo'].nunique()), inviernos=sorted(d['invierno'].unique()), grupos={}, **extra)
    g = {}
    for ant in (1, 2, 3):
        m = (d['ant'] == ant).to_numpy()
        y, po = d['y'].to_numpy()[m], paso(oof[m])
        g[str(ant)] = dict(mananas=int(m.sum()), cierres=int(y.sum()), distritos=int(d.loc[m, 'leaid'].nunique()), pasos=tabla(po, y),
                           brier=brier(oof[m], y), brier_base=brier(np.full(m.sum(), y.mean()), y),
                           cierres_con_10=int(((po >= 10) & (y == 1)).sum()), cierres_con_30=int(((po >= 30) & (y == 1)).sum()))
        log(f'   {nombre} · antelación {ant}: {m.sum()} mañanas, {int(y.sum())} sin clase · Brier {g[str(ant)]["brier"]} (referencia {g[str(ant)]["brier_base"]}) · ' +
            ' | '.join(f'{t["pct"] or "<10"}: {t["de_100"]} ({t["mananas"]})' for t in g[str(ant)]['pasos']))
    res['grupos']['principal'] = g
    # La mañana con más cierres, vista la tarde anterior
    t = d[d['ant'] == 1]
    # La de invierno con más cierres: se descartan los días sin señal de nieve, hielo ni frío (temporales de
    # viento o inundaciones, que este cálculo no intenta prever)
    inv = t.groupby('fecha')['lx'].median()
    cand = t[(t['y'] == 1) & t['fecha'].isin(inv[inv > np.log(0.2)].index)]
    top = (cand if len(cand) else t[t['y'] == 1]).groupby('fecha').size().idxmax()
    z = t[t['fecha'] == top]
    pz = paso(np.interp(z['lx'].to_numpy(), LREJ, p_final))
    res['tormenta'] = dict(fecha=top, distritos=int(len(z)), cerraron=int(z['y'].sum()), con_50=int(((pz >= 50) & (z['y'] == 1)).sum()),
                           con_30=int(((pz >= 30) & (z['y'] == 1)).sum()), abiertos_con_50=int(((pz >= 50) & (z['y'] == 0)).sum()))
    return res


def main():
    ky, ky_todos = kentucky()
    sc = carolina()
    log(f'Kentucky (limpios): {len(ky)} mañanas, {int(ky["y"].sum())} sin clase, {ky["leaid"].nunique()} distritos')
    log(f'Carolina del Sur: {len(sc)} mañanas, {int(sc["y"].sum())} sin clase, {sc["leaid"].nunique()} distritos')
    for inv, g in sc[sc['ant'] == 1].groupby('invierno'):
        log(f'   SC {inv}: {len(g)} mañanas, {int(g["y"].sum())} sin clase · con x ≥ 1: {int((g["x"] >= 1).sum())}, de ellas sin clase {int(g.loc[g["x"] >= 1, "y"].sum())}')

    cols = ['leaid', 'fecha', 'ciclo', 'ant', 'x', 'lx', 'y', 'invierno']
    todo = pd.concat([ky[cols].assign(estado='KY'), sc[cols].assign(estado='SC')], ignore_index=True)
    LX, Y = todo['lx'].to_numpy(), todo['y'].to_numpy()
    p = curva(LX, Y)
    log('curva común (x → %): ' + ' · '.join(f'{a}→{100 * b:.0f}' for a, b in zip(REJILLA, p)))
    for est in ('KY', 'SC'):
        m = (todo['estado'] == est).to_numpy()
        log(f'curva solo {est} (x → %): ' + ' · '.join(f'{a}→{100 * b:.0f}' for a, b in zip(REJILLA, curva(LX[m], Y[m]))))

    # Fuera de muestra por distrito
    oof = np.zeros(len(todo))
    for tr, te in GroupKFold(n_splits=8).split(todo, groups=todo['leaid']):
        oof[te] = np.interp(LX[te], LREJ, curva(LX[tr], Y[tr]))
    # Prueba cruzada entre estados: cada uno con la curva del otro
    for a, b in (('KY', 'SC'), ('SC', 'KY')):
        ma, mb = (todo['estado'] == a).to_numpy(), (todo['estado'] == b).to_numpy()
        cruz = np.interp(LX[mb], LREJ, curva(LX[ma], Y[ma]))
        log(f'{b} con la curva de {a}: Brier {brier(cruz, Y[mb])} · con la común fuera de muestra {brier(oof[mb], Y[mb])} · referencia {brier(np.full(mb.sum(), Y[mb].mean()), Y[mb])}')

    hecho = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    mk, ms = (todo['estado'] == 'KY').to_numpy(), (todo['estado'] == 'SC').to_numpy()
    rk = resumen('KY', todo[mk].reset_index(drop=True), oof[mk], p, dict(invierno='2024-25', distritos_total=int(ky_todos['leaid'].nunique())))
    rs = resumen('SC', todo[ms].reset_index(drop=True), oof[ms], p, dict(invierno='2021-22 a 2025-26'))
    (SAL / 'ky_2425_resumen.json').write_text(json.dumps(rk, ensure_ascii=False, indent=1), encoding='utf-8')
    (SAL / 'sc_resumen.json').write_text(json.dumps(rs, ensure_ascii=False, indent=1), encoding='utf-8')
    log(f'tormentas: KY {rk["tormenta"]} · SC {rs["tormenta"]}')
    if '--no-guardar' not in sys.argv:
        cal = {str(a): dict(x=REJILLA, p=[round(float(q), 3) for q in p]) for a in (1, 2, 3)}
        (nc.FIJOS / 'calibracion.json').write_text(json.dumps(dict(origen='Kentucky 2024-25 (distritos con 3 NTI o menos) y Carolina del Sur 2021-22 a 2025-26',
                                                                   hecho=hecho, x_min=X_MIN, antelacion=cal), indent=1), encoding='utf-8')
        log('calibracion.json actualizado')
    return 0


if __name__ == '__main__':
    sys.exit(main())
