#!/usr/bin/env python3
"""
12_calibra.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Ajusta la curva que convierte el cociente del índice (nieve, hielo y frío frente
a lo normal en el distrito) en probabilidad, con los cierres REALES de Kentucky
del invierno 2024-25 (salida/backtest/ky_2425.csv, de 11_backtest_ky.py).

Curva: monótona y sin forma impuesta (regresión isotónica sobre ln x), una por
sola para las tres antelaciones (por separado hay muy pocos cierres y bailan).
Se guarda como una tabla de puntos (x → p) que 07_indice.py interpola.

Lo que enseñó Kentucky: con cualquier señal de invierno, por pequeña que sea,
cierra en torno a 1 de cada 10 distritos; a partir de x ≈ 1,3-1,5 se salta a
2 de cada 3. La fórmula de partida daba casi cero a las señales pequeñas y
demasiado a las medianas.

Solo se ajusta con los distritos que usaron 3 jornadas a distancia (NTI) o menos:
en los demás, muchas mañanas sin clase presencial constan como «hubo clase».

Honestidad de la prueba: la tabla de fiabilidad se calcula FUERA DE MUESTRA,
dejando fuera cada vez un grupo de distritos (validación cruzada por distrito).

Salida:  fijos/calibracion.json                 {antelación: {x: […], p: […]}}  → 07_indice.py
         salida/backtest/ky_2425_resumen.json   lo que enseña la página de aciertos
"""
import importlib.util
import json
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import GroupKFold

import nbm_comun as nc

spec = importlib.util.spec_from_file_location('bt', nc.BASE / 'scripts' / '11_backtest_ky.py')
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

SAL = nc.BASE / 'salida' / 'backtest'
X_MIN = 0.02
REJILLA = [0.02, 0.04, 0.06, 0.1, 0.2, 0.4, 0.7, 1.0, 1.25, 1.5, 1.8, 2.2, 3.0, 4.0]
TECHO = 0.9
PASOS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90]


def log(msg):
    print(msg, flush=True)


def iso(lx, y):
    return IsotonicRegression(y_min=0, y_max=1, out_of_bounds='clip').fit(lx, y)


def paso(p):
    """Como en la web: de 10 en 10, techo 90; por debajo de 10 % va al grupo «<10 %» (0)."""
    q = np.minimum(np.round(p * 10) * 10, 90)
    return np.where(p >= 0.095, q, 0).astype(int)


def tabla(pct, y):
    out = []
    for s in PASOS:
        m = pct == s
        if m.sum():
            out.append(dict(pct=int(s), mananas=int(m.sum()), cerraron=int(y[m].sum()), de_100=round(100 * float(y[m].mean()), 1)))
    return out


def brier(p, y):
    return round(float(((np.clip(p, 0.0, TECHO) - y) ** 2).mean()), 4)


def main():
    verdad = bt.lee_verdad()
    x = pd.read_csv(SAL / 'ky_2425.csv', dtype={'leaid': str}, low_memory=False)
    x['f'] = pd.to_datetime(x['fecha']).dt.date
    x['fc'] = pd.to_datetime(x['ciclo'].str[:8]).dt.date
    # Antelación en días naturales: 1 = la tarde anterior
    x['ant'] = [(a - b).days for a, b in zip(x['f'], x['fc'])]
    v = x['leaid'].map(verdad)
    x['cerro'] = [f in q['cierres'] for q, f in zip(v, x['f'])]
    x['lectivo'] = [((q['primero'] is None or f >= q['primero']) and (q['ultimo'] is None or f <= q['ultimo']) and f not in q['no_lectivo']) or f in q['cierres']
                    for q, f in zip(v, x['f'])]
    x['nti'] = [q['nti'] for q in v]
    x = x[x['lectivo'] & x['ant'].between(1, 3)].copy()
    x['x'] = np.sqrt(x['r_nieve'] ** 2 + x['r_hielo'] ** 2 + x['r_frio'] ** 2)
    x['lx'] = np.log(np.maximum(x['x'], X_MIN))
    x['y'] = x['cerro'].astype(int)
    x['pct_antes'] = np.where(x['pct'] >= 10, x['pct'], 0)

    limpio = x[x['nti'] <= 3]
    log(f'Mañanas de clase: {len(x)} en {x["leaid"].nunique()} distritos · con pocas NTI: {len(limpio)} en {limpio["leaid"].nunique()} distritos')
    cal, res = {}, dict(estado='KY', invierno='2024-25', hecho=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
                        ciclos=int(x['ciclo'].nunique()), distritos=int(x['leaid'].nunique()), distritos_ajuste=int(limpio['leaid'].nunique()),
                        grupos=dict(pocos_nti={}, todos={}))
    lrej = np.log(REJILLA)
    # Una sola curva para las tres antelaciones: con 63 cierres por antelación, las curvas separadas
    # bailan demasiado y sus diferencias son ruido. Juntas dan una curva más firme.
    limpio = limpio.reset_index(drop=True)
    LX, Y = limpio['lx'].to_numpy(), limpio['y'].to_numpy()
    p = np.minimum(np.maximum.accumulate(iso(LX, Y).predict(lrej)), TECHO)
    OOF = np.zeros(len(limpio))
    # Fuera de muestra: cada distrito se predice con una curva que no lo ha visto
    for tr, te in GroupKFold(n_splits=7).split(limpio, groups=limpio['leaid']):
        pk = np.minimum(np.maximum.accumulate(iso(LX[tr], Y[tr]).predict(lrej)), TECHO)
        OOF[te] = np.interp(LX[te], lrej, pk)
    log('curva común (x → %): ' + ' · '.join(f'{a}→{100 * b:.0f}' for a, b in zip(REJILLA, p)))
    for ant in (1, 2, 3):
        sel = (limpio['ant'] == ant).to_numpy()
        d = limpio[sel]
        lx, y, oof = LX[sel], Y[sel], OOF[sel]
        cal[str(ant)] = dict(x=REJILLA, p=[round(float(q), 3) for q in p])
        log(f'── antelación {ant} · {len(d)} mañanas, {int(y.sum())} cierres')
        log(f'   Brier: antes {brier(d["pct"].to_numpy() / 100, y)} · ajustado fuera de muestra {brier(oof, y)} · referencia {brier(np.full(len(d), y.mean()), y)}')
        for etq, pct in (('antes   ', d['pct_antes'].to_numpy()), ('ajustado', paso(oof))):
            log(f'   {etq}: ' + ' | '.join(f'{t["pct"] or "<10"} %: {t["de_100"]} ({t["mananas"]})' for t in tabla(pct, y)))
        po = paso(oof)
        res['grupos']['pocos_nti'][str(ant)] = dict(
            mananas=int(len(d)), cierres=int(y.sum()), distritos=int(d['leaid'].nunique()),
            pasos=tabla(po, y), pasos_antes=tabla(d['pct_antes'].to_numpy(), y),
            brier=brier(oof, y), brier_antes=brier(d['pct'].to_numpy() / 100, y), brier_base=brier(np.full(len(d), y.mean()), y),
            cierres_con_30=int(((po >= 30) & (y == 1)).sum()), cierres_con_10=int(((po >= 10) & (y == 1)).sum()))
        # Todos los distritos con la curva final (150 de ellos no entraron en el ajuste)
        t = x[x['ant'] == ant]
        pt = paso(np.interp(t['lx'].to_numpy(), lrej, p))
        res['grupos']['todos'][str(ant)] = dict(mananas=int(len(t)), cierres=int(t['y'].sum()), distritos=int(t['leaid'].nunique()),
                                                pasos=tabla(pt, t['y'].to_numpy()), cierres_con_30=int(((pt >= 30) & (t['y'] == 1)).sum()),
                                                cierres_con_10=int(((pt >= 10) & (t['y'] == 1)).sum()))
    # La mañana con más cierres, vista la tarde anterior con la curva final
    t = x[x['ant'] == 1]
    top = t[t['cerro']].groupby('fecha').size().idxmax()
    z = t[t['fecha'] == top]
    pz = paso(np.interp(z['lx'].to_numpy(), lrej, cal['1']['p']))
    res['tormenta'] = dict(fecha=top, distritos=int(len(z)), cerraron=int(z['y'].sum()), con_50=int(((pz >= 50) & (z['y'] == 1)).sum()),
                           con_30=int(((pz >= 30) & (z['y'] == 1)).sum()), abiertos_con_50=int(((pz >= 50) & (z['y'] == 0)).sum()))
    log(f'tormenta: {res["tormenta"]}')
    (nc.FIJOS / 'calibracion.json').write_text(json.dumps(dict(origen='Kentucky 2024-25, distritos con 3 NTI o menos', hecho=res['hecho'],
                                                               x_min=X_MIN, antelacion=cal), indent=1), encoding='utf-8')
    (SAL / 'ky_2425_resumen.json').write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding='utf-8')
    return 0


if __name__ == '__main__':
    sys.exit(main())
