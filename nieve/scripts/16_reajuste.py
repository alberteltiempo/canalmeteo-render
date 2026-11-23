#!/usr/bin/env python3
"""
16_reajuste.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Reajusta CÓMO SE COMPARAN CLIMAS DISTINTOS. La prueba de Carolina del Sur
enseñó que la tolerancia de partida (0,8 + 0,55·√N pulgadas, N = nieve anual)
es demasiado generosa donde casi nunca nieva: allí se cierra con mucho menos.

Qué se ajusta, con Kentucky 2024-25 (distritos con 3 NTI o menos) y Carolina
del Sur 2021-22 a 2025-26 a la vez:
    tolerancia a la nieve   T(N) = T12 · ((N + n0) / (12 + n0)) ^ k
    hielo                   cuenta como RHO veces su espesor en nieve
    nieve reciente          la prevista para los tres días anteriores, si la noche sigue helando, con peso WS
    frío                    peso WC sobre el cociente de frío de partida
y, encima, una sola curva monótona  x → probabilidad.

T12 (la tolerancia en un clima como el de Kentucky) no se ajusta: la absorbe
la curva. Cada combinación se puntúa FUERA DE MUESTRA (validación cruzada por
distrito) con el acierto de cada estado frente a decir siempre su media, y se
elige la mejor media de los dos estados, que pesan lo mismo aunque Carolina
del Sur tenga muchas más mañanas.

Por encima de N = 20 in no hay datos (ningún estado nevado probado): ahí la
tolerancia sigue creciendo con la raíz, que es un SUPUESTO, y se mantiene la
rebaja de las probabilidades bajas.

Salida (solo con --guardar):  fijos/calibracion.json  con «tolerancia» y la curva
                              salida/backtest/ky_2425_resumen.json, sc_resumen.json
"""
import importlib.util
import itertools
import json
import sys
from datetime import datetime, timezone

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


ce = _mod('15_calibra_estados')
SAL = nc.BASE / 'salida' / 'backtest'
T12, N_REF, N_TOPE = 2.7, 12.0, 20.0     # T12: tolerancia de partida en N = 12 (0,8 + 0,55·√12)
REJILLA = [0.02, 0.04, 0.06, 0.1, 0.15, 0.2, 0.3, 0.4, 0.55, 0.7, 0.85, 1.0, 1.25, 1.5, 1.8, 2.2, 3.0, 4.0]
LREJ = np.log(REJILLA)
TECHO = 0.9


def log(msg):
    print(msg, flush=True)


def tolerancia(N, k, n0):
    """Pulgadas de nieve efectiva que marcan x = 1. Hasta N_TOPE, potencia k; por encima, raíz (supuesto)."""
    N = np.asarray(N, dtype='float64')
    base = T12 * ((np.minimum(N, N_TOPE) + n0) / (N_REF + n0)) ** k
    return base * np.sqrt((np.maximum(N, N_TOPE) + n0) / (N_TOPE + n0))


def frio_extremo(sens, N):
    """Regla aparte para el frío extremo, SIN ajustar con datos (Kentucky y Carolina del Sur casi nunca llegan):
    50 % cuando la sensación a la hora del autobús baja al umbral habitual de cierre, de −15 °F donde nieva
    poco a −35 °F donde nieva mucho. Se combina con la curva: p = 1 − (1 − p_curva)·(1 − p_frío)."""
    umbral = -15.0 - 20.0 * np.clip((np.asarray(N, dtype='float64') - 15.0) / 30.0, 0, 1)
    s = np.where(np.isfinite(sens), sens, 60.0)
    return 1.0 / (1.0 + np.exp((s - umbral) / 4.0))


def cociente(d, k, n0, rho, wc, ws=0.0):
    t = tolerancia(d['nieve_anual_in'].to_numpy(), k, n0)
    rs = d['S'].to_numpy() / t
    ri = d['hielo_in'].to_numpy() * rho / t
    rg = ws * d['previa'].to_numpy() / t            # nieve reciente que sigue en el suelo (ver datos())
    return np.sqrt(rs ** 2 + ri ** 2 + rg ** 2 + (wc * d['r_frio'].to_numpy()) ** 2)


def curva(lx, y, w):
    m = IsotonicRegression(y_min=0, y_max=1, out_of_bounds='clip').fit(lx, y, sample_weight=w)
    return np.minimum(np.maximum.accumulate(m.predict(LREJ)), TECHO)


def fuera_de_muestra(d, x, w, folds):
    lx, y = np.log(np.maximum(x, 0.02)), d['y'].to_numpy()
    oof = np.zeros(len(d))
    for tr, te in folds:
        oof[te] = np.interp(lx[te], LREJ, curva(lx[tr], y[tr], w[tr]))
    return oof


def merito(oof, d):
    """Acierto por estado: 1 − Brier / Brier de decir siempre la media del estado (0 = no aporta nada)."""
    out = {}
    for est in ('KY', 'SC'):
        m = (d['estado'] == est).to_numpy()
        y = d['y'].to_numpy()[m]
        out[est] = 1 - float(((oof[m] - y) ** 2).mean()) / float(((y.mean() - y) ** 2).mean())
    return out


def datos():
    ky, ky_todos = ce.kentucky()
    sc = ce.carolina()
    rel = pd.read_csv(nc.FIJOS / 'relieve.csv', dtype={'leaid': str})[['leaid', 'rugosidad_m']]
    cols = ['leaid', 'fecha', 'ciclo', 'ant', 'y', 'invierno', 'nieve_tarde_in', 'nieve_noche_in', 'nieve_clase_in', 'hielo_in', 'r_frio',
            'nieve_anual_in', 'sens_bus_f', 'pct', 'temp_min_noche_f']
    d = pd.concat([ky[cols].assign(estado='KY'), sc[cols].assign(estado='SC')], ignore_index=True).merge(rel, on='leaid', how='left')
    # Nieve efectiva como en 07_indice.py: noche + 0,6·clase + 0,4·tarde, y hasta +25 % por relieve
    d['S'] = (d['nieve_noche_in'].fillna(0) + 0.6 * d['nieve_clase_in'].fillna(0) + 0.4 * d['nieve_tarde_in'].fillna(0)) \
        * (1 + 0.25 * np.minimum(d['rugosidad_m'].fillna(0) / 100.0, 1))
    d['hielo_in'] = d['hielo_in'].fillna(0)
    d['r_frio'] = d['r_frio'].fillna(0)
    # Nieve reciente: la prevista (la tarde anterior de cada día) para los tres días anteriores, con menos peso
    # cuanto más atrás, y solo si la noche sigue helando (por encima de 34 °F de mínima ya no cuenta).
    # El archivo del NBM de estos inviernos no trae la nieve en el suelo (SNOD), así que se reconstruye así.
    # Límite: los días sin clase (fines de semana) no tienen fila y su nieve no se ve.
    # Sin mirar al futuro: un día anterior que ya pasó (j ≥ antelación) se toma de lo que se pronosticó la
    # tarde antes de ese día; uno que aún no ha llegado (j < antelación), del mismo ciclo de la fila.
    d['S1'] = d['S'] + 10 * d['hielo_in']
    d['f'] = pd.to_datetime(d['fecha'])
    pasado = d[d['ant'] == 1][['leaid', 'f', 'S1']].drop_duplicates(['leaid', 'f'])
    mismo = d[['leaid', 'ciclo', 'f', 'S1']].drop_duplicates(['leaid', 'ciclo', 'f'])
    d['previa'] = 0.0
    for j, peso in ((1, 1.0), (2, 0.7), (3, 0.4)):
        a = pasado.assign(f=pasado['f'] + pd.Timedelta(days=j)).rename(columns={'S1': 'pa'})
        b = mismo.assign(f=mismo['f'] + pd.Timedelta(days=j)).rename(columns={'S1': 'pb'})
        d = d.merge(a, on=['leaid', 'f'], how='left').merge(b, on=['leaid', 'ciclo', 'f'], how='left')
        d['previa'] += peso * np.where(d['ant'] <= j, d['pa'].fillna(0), d['pb'].fillna(0))
        d = d.drop(columns=['pa', 'pb'])
    d['previa'] *= np.clip((34 - d['temp_min_noche_f'].fillna(40)) / 8.0, 0, 1)
    return d, ky_todos


def main():
    d, _ = datos()
    n = d['estado'].value_counts()
    w = d['estado'].map({e: 1.0 / n[e] for e in n.index}).to_numpy() * len(d) / 2     # los dos estados pesan lo mismo
    folds = list(GroupKFold(n_splits=8).split(d, groups=d['leaid']))
    log(f'Mañanas: KY {n["KY"]}, SC {n["SC"]} · nieve anual mediana: KY {d.loc[d.estado == "KY", "nieve_anual_in"].median():.1f} in, SC {d.loc[d.estado == "SC", "nieve_anual_in"].median():.1f} in')

    # Punto de partida: la tolerancia de producción (raíz) con la curva común
    x0 = np.sqrt((d['S'] / (0.8 + 0.55 * np.sqrt(d['nieve_anual_in']))) ** 2 + (d['hielo_in'] / (0.05 + 0.02 * np.sqrt(d['nieve_anual_in']))) ** 2 + d['r_frio'] ** 2).to_numpy()
    m0 = merito(fuera_de_muestra(d, x0, w, folds), d)
    log(f'De partida (tolerancia con raíz): mérito KY {m0["KY"]:+.3f} · SC {m0["SC"]:+.3f} · media {(m0["KY"] + m0["SC"]) / 2:+.3f}')

    res = []
    for k, n0, rho, wc, ws in itertools.product((0.7, 1.0, 1.15), (1.0, 2.0), (10, 20), (0.0, 0.25, 0.5), (0.0, 0.3, 0.6, 1.0, 1.5)):
        m = merito(fuera_de_muestra(d, cociente(d, k, n0, rho, wc, ws), w, folds), d)
        res.append((k, n0, rho, wc, ws, m['KY'], m['SC'], (m['KY'] + m['SC']) / 2))
    t = pd.DataFrame(res, columns=['k', 'n0', 'rho', 'wc', 'ws', 'KY', 'SC', 'media']).sort_values('media', ascending=False)
    log('Las diez mejores combinaciones (mérito fuera de muestra; 0 = no aporta, más alto es mejor):')
    log(t.head(10).round(3).to_string(index=False))
    log('Efecto de cada parámetro (media del mérito):')
    for c in ('k', 'n0', 'rho', 'wc', 'ws'):
        log(f'  {c}: ' + ' · '.join(f'{a}→{b:+.3f}' for a, b in t.groupby(c)['media'].mean().items()))

    k, n0, rho, wc, ws = (float(v) for v in t.iloc[0][['k', 'n0', 'rho', 'wc', 'ws']])
    if '--fija' in sys.argv:        # --fija k n0 hielo frío : se impone una combinación (la más prudente entre las casi empatadas)
        i = sys.argv.index('--fija')
        k, n0, rho, wc, ws = (float(v) for v in sys.argv[i + 1:i + 6])
        m = merito(fuera_de_muestra(d, cociente(d, k, n0, rho, wc, ws), w, folds), d)
        log(f'Impuesta: mérito KY {m["KY"]:+.3f} · SC {m["SC"]:+.3f} · media {(m["KY"] + m["SC"]) / 2:+.3f}')
    x = cociente(d, k, n0, rho, wc, ws)
    oof = fuera_de_muestra(d, x, w, folds)
    # Las tablas que se publican llevan también la regla de frío extremo, como en producción
    oof = 1 - (1 - oof) * (1 - frio_extremo(d['sens_bus_f'].to_numpy(), d['nieve_anual_in'].to_numpy()))
    mf = merito(oof, d)
    log(f'Con la regla de frío extremo: mérito KY {mf["KY"]:+.3f} · SC {mf["SC"]:+.3f}')
    lx, y = np.log(np.maximum(x, 0.02)), d['y'].to_numpy()
    p = curva(lx, y, w)
    log(f'\nElegida: k = {k}, n0 = {n0}, hielo × {rho:.0f}, frío × {wc}, nieve reciente x {ws}')
    log('  tolerancia (in) por nieve anual: ' + ' · '.join(f'N={a}→{float(tolerancia(a, k, n0)):.1f}' for a in (0, 1, 2, 5, 12, 20, 40, 80)) +
        '   (antes: ' + ' · '.join(f'{0.8 + 0.55 * a ** 0.5:.1f}' for a in (0, 1, 2, 5, 12, 20, 40, 80)) + ')')
    log('  curva (x → %): ' + ' · '.join(f'{a}→{100 * b:.0f}' for a, b in zip(REJILLA, p)))
    d['lx'] = lx
    hecho = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    salidas = {}
    for est, nombre, extra in (('KY', 'ky_2425', dict(invierno='2024-25')), ('SC', 'sc', dict(invierno='2021-22 a 2025-26'))):
        m = (d['estado'] == est).to_numpy()
        ce.LREJ = LREJ
        salidas[nombre] = ce.resumen(est, d[m].reset_index(drop=True), oof[m], p, extra)
    if '--guardar' in sys.argv:
        cal = {str(a): dict(x=REJILLA, p=[round(float(q), 3) for q in p]) for a in (1, 2, 3)}
        (nc.FIJOS / 'calibracion.json').write_text(json.dumps(dict(
            origen='Kentucky 2024-25 (distritos con 3 NTI o menos) y Carolina del Sur 2021-22 a 2025-26', hecho=hecho, x_min=0.02,
            tolerancia=dict(t12=T12, n_ref=N_REF, n_tope=N_TOPE, k=k, n0=n0, hielo=rho, frio=wc, reciente=ws), antelacion=cal), indent=1), encoding='utf-8')
        for nombre, r in salidas.items():
            (SAL / f'{nombre}_resumen.json').write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
        log('calibracion.json y resúmenes guardados')
    return 0


if __name__ == '__main__':
    sys.exit(main())
