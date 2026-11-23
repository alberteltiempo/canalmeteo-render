#!/usr/bin/env python3
"""
19_reajuste_tres.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Primera prueba con un estado NEVADO. Añade Illinois (2021-22 a 2025-26, 849
distritos, nieve anual de 10 a 40 in) a Kentucky y Carolina del Sur y contesta:

  1. ¿Cómo lo hace en Illinois el cálculo que está HOY en producción? Illinois
     no entró en su ajuste, así que es una prueba limpia. Con y sin la rebaja
     de las probabilidades bajas y con y sin la regla de frío extremo.
  2. ¿Cuánto se cierra de verdad por frío, sin nieve? (la regla de frío extremo
     estaba sin ajustar)
  3. ¿Qué parámetros salen mejor con los tres estados? Incluye el que antes era
     un supuesto: cómo crece la tolerancia por encima de 20 in de nieve anual
     (exponente K2; en producción es raíz, 0,5).
  4. Cada estado con una curva hecha solo con los otros dos.

NO toca producción: solo imprime. (El guardado se hará aparte, con permiso.)

Uso:  19_reajuste_tres.py [--rapido]
"""
import importlib.util
import itertools
import json
import sys

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

import nbm_comun as nc


def _mod(nombre):
    s = importlib.util.spec_from_file_location(nombre, nc.BASE / 'scripts' / f'{nombre}.py')
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


r16 = _mod('16_reajuste')
ce = r16.ce
ESTADOS = ('KY', 'SC', 'IL')
T12, N_REF, N_TOPE = r16.T12, r16.N_REF, r16.N_TOPE
LREJ = r16.LREJ
PROD = dict(k=1.0, n0=2.0, rho=20.0, wc=0.25, ws=0.3, k2=0.5)


def log(msg):
    print(msg, flush=True)


def tolerancia(N, k, n0, k2):
    N = np.asarray(N, dtype='float64')
    return T12 * ((np.minimum(N, N_TOPE) + n0) / (N_REF + n0)) ** k * ((np.maximum(N, N_TOPE) + n0) / (N_TOPE + n0)) ** k2


def cociente(d, k, n0, rho, wc, ws, k2):
    t = tolerancia(d['nieve_anual_in'].to_numpy(), k, n0, k2)
    return np.sqrt((d['S'].to_numpy() / t) ** 2 + (d['hielo_in'].to_numpy() * rho / t) ** 2 + (ws * d['previa'].to_numpy() / t) ** 2
                   + (wc * d['frio0'].to_numpy()) ** 2)


def merito(p, d, m=None):
    """1 − Brier / Brier de decir siempre la media del estado (0 = no aporta nada), por estado."""
    out = {}
    for est in ESTADOS:
        q = (d['estado'] == est).to_numpy() if m is None else ((d['estado'] == est).to_numpy() & m)
        y = d['y'].to_numpy()[q]
        out[est] = 1 - float(((p[q] - y) ** 2).mean()) / float(((y.mean() - y) ** 2).mean())
    return out


def datos():
    ky, _ = ce.kentucky()
    sc = ce.carolina()
    il = ce.illinois()
    rel = pd.read_csv(nc.FIJOS / 'relieve.csv', dtype={'leaid': str})[['leaid', 'rugosidad_m']]
    cols = ['leaid', 'fecha', 'ciclo', 'ant', 'y', 'invierno', 'nieve_tarde_in', 'nieve_noche_in', 'nieve_clase_in', 'hielo_in',
            'nieve_anual_in', 'sens_bus_f', 'temp_min_noche_f']
    d = pd.concat([ky[cols].assign(estado='KY'), sc[cols].assign(estado='SC'), il[cols].assign(estado='IL')], ignore_index=True)
    d = d.merge(rel, on='leaid', how='left')
    d['S'] = (d['nieve_noche_in'].fillna(0) + 0.6 * d['nieve_clase_in'].fillna(0) + 0.4 * d['nieve_tarde_in'].fillna(0)) \
        * (1 + 0.25 * np.minimum(d['rugosidad_m'].fillna(0) / 100.0, 1))
    d['hielo_in'] = d['hielo_in'].fillna(0)
    # Cociente de frío de partida, recalculado (el de il.csv ya viene multiplicado por el peso de producción)
    umbral = np.clip(10.0 - 4.5 * np.sqrt(d['nieve_anual_in']), -35, 10)
    d['frio0'] = np.clip((umbral + 15.0 - d['sens_bus_f']) / 15.0, 0, None).fillna(0)
    # Nieve reciente, igual que en 16_reajuste.py (sin mirar al futuro)
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
    return d


def tabla(p, y, pasos=(0, 10, 20, 30, 40, 50, 60, 70, 80, 90)):
    q = ce.paso(p)
    return ' | '.join(f'{s or "<10"}: {100 * y[q == s].mean():.0f} de 100 ({(q == s).sum()})' for s in pasos if (q == s).sum())


def main():
    d = datos()
    y, N = d['y'].to_numpy(), d['nieve_anual_in'].to_numpy()
    il = (d['estado'] == 'IL').to_numpy()
    for est in ESTADOS:
        g = d[d['estado'] == est]
        log(f'{est}: {len(g)} mañanas-pronóstico, {g["leaid"].nunique()} distritos, {g["ciclo"].nunique()} ciclos, sin clase {100 * g["y"].mean():.2f} % · '
            f'nieve anual {g["nieve_anual_in"].quantile(0.05):.0f}-{g["nieve_anual_in"].quantile(0.95):.0f} in')
    for inv, g in d[il & (d['ant'] == 1)].groupby('invierno'):
        log(f'   IL {inv}: {len(g)} mañanas, {int(g["y"].sum())} sin clase')

    # ── 1. Producción de hoy, en Illinois (que no entró en su ajuste)
    cal = json.loads((nc.FIJOS / 'calibracion.json').read_text())
    c = cal['antelacion']['1']
    xp = cociente(d, **PROD)
    p0 = np.interp(np.log(np.maximum(xp, cal['x_min'])), np.log(c['x']), c['p'])
    f = np.clip(20.0 / np.maximum(N, 0.1), 0.25, 1.0)
    p_reb = p0 * (f + (1 - f) * np.clip((p0 - 0.45) / 0.25, 0, 1))
    pf = r16.frio_extremo(d['sens_bus_f'].to_numpy(), N)
    variantes = {'curva sola': p0, 'curva + rebaja': p_reb, 'curva + frío extremo': 1 - (1 - p0) * (1 - pf),
                 'PRODUCCIÓN (rebaja + frío extremo)': 1 - (1 - p_reb) * (1 - pf)}
    log('\n1. PRODUCCIÓN DE HOY EN ILLINOIS (mérito; 0 = no aporta, 1 = perfecto)')
    for nombre, p in variantes.items():
        log(f'   {nombre}: ' + ' · '.join(f'antelación {a}: {merito(p, d, (d["ant"] == a).to_numpy())["IL"]:+.3f}' for a in (1, 2, 3)))
    pp = variantes['PRODUCCIÓN (rebaja + frío extremo)']
    for a in (1, 2, 3):
        m = il & (d['ant'] == a).to_numpy()
        log(f'   fiabilidad, antelación {a}: {tabla(pp[m], y[m])}')
    m = il & (d['ant'] == 1).to_numpy()
    q = ce.paso(pp[m])
    log(f'   de los {int(y[m].sum())} cierres, tenían 30 % o más: {int(((q >= 30) & (y[m] == 1)).sum())}; 10 % o más: {int(((q >= 10) & (y[m] == 1)).sum())}')
    t = d[m].assign(p=pp[m])
    dias = t.groupby('fecha').agg(distritos=('y', 'size'), cerraron=('y', 'sum'), prevision=('p', 'sum')).sort_values('cerraron', ascending=False)
    log('   los 15 días con más cierres: cerraron / los que esperaba el cálculo (suma de probabilidades)')
    log(dias.head(15).round(0).astype(int).to_string())
    log(f'   falsas alarmas: días con 100 o más cierres esperados y menos de la cuarta parte reales:')
    fa = dias[(dias['prevision'] >= 100) & (dias['cerraron'] < dias['prevision'] / 4)]
    log(fa.round(0).astype(int).to_string() if len(fa) else '   ninguno')

    # ── 2. Frío sin nieve
    log('\n2. FRÍO SIN NIEVE en Illinois (mañanas con poca nieve y hielo previstos, x < 0,15 sin contar el frío; tarde anterior)')
    xs = cociente(d, PROD['k'], PROD['n0'], PROD['rho'], 0.0, PROD['ws'], PROD['k2'])
    m = il & (d['ant'] == 1).to_numpy() & (xs < 0.15)
    s = d['sens_bus_f'].to_numpy()
    for a, b in ((-60, -35), (-35, -30), (-30, -25), (-25, -20), (-20, -15), (-15, -10), (-10, -5), (-5, 0), (0, 10), (10, 60)):
        q = m & (s >= a) & (s < b)
        if q.sum():
            log(f'   sensación de {a} a {b} °F: {q.sum()} mañanas, sin clase {100 * y[q].mean():.0f} de 100 · la regla de hoy decía {100 * pf[q].mean():.0f}')
    for lo, hi in ((0, 20), (20, 30), (30, 60)):
        q = m & (N >= lo) & (N < hi) & (s < -20)
        if q.sum():
            log(f'   con sensación bajo −20 °F y nieve anual de {lo} a {hi} in: {q.sum()} mañanas, sin clase {100 * y[q].mean():.0f} de 100')

    # ── 3. Rejilla con los tres estados
    n = d['estado'].value_counts()
    w = d['estado'].map({e: 1.0 / n[e] for e in n.index}).to_numpy() * len(d) / len(n)      # los tres pesan lo mismo
    folds = list(GroupKFold(n_splits=5).split(d, groups=d['leaid']))

    def prueba(**kw):
        return merito(r16.fuera_de_muestra(d, cociente(d, **kw), w, folds), d)
    m0 = prueba(**PROD)
    log('\n3. AJUSTE CON LOS TRES ESTADOS (mérito fuera de muestra, curva común)')
    log('   parámetros de hoy: ' + ' · '.join(f'{e} {m0[e]:+.3f}' for e in ESTADOS))
    rej = dict(k=(0.7, 1.0), n0=(2.0,), rho=(10.0, 20.0), wc=(0.0, 0.25, 0.5), ws=(0.0, 0.3, 0.6), k2=(0.0, 0.25, 0.5, 0.75, 1.0))
    if '--rapido' in sys.argv:
        rej = dict(k=(1.0,), n0=(2.0,), rho=(20.0,), wc=(0.25,), ws=(0.3,), k2=(0.0, 0.5, 1.0))
    res = []
    for v in itertools.product(*rej.values()):
        kw = dict(zip(rej.keys(), v))
        mm = prueba(**kw)
        res.append({**kw, **mm, 'media': float(np.mean([mm[e] for e in ESTADOS]))})
    t = pd.DataFrame(res).sort_values('media', ascending=False)
    log(t.head(12).round(3).to_string(index=False))
    for cc in rej:
        if len(rej[cc]) > 1:
            g = t.groupby(cc)[['KY', 'SC', 'IL', 'media']].max()
            log(f'   {cc} (mejor mérito con cada valor): ' + ' · '.join(f'{a}→ IL {r.IL:+.3f}, media {r.media:+.3f}' for a, r in g.iterrows()))
    mejor = {cc: float(t.iloc[0][cc]) for cc in rej}
    log(f'   mejor: {mejor}')
    log('   tolerancia (in) por nieve anual, hoy → mejor: ' + ' · '.join(
        f'N={a}: {float(tolerancia(a, PROD["k"], PROD["n0"], PROD["k2"])):.1f}→{float(tolerancia(a, mejor["k"], mejor["n0"], mejor["k2"])):.1f}' for a in (2, 12, 20, 30, 40, 80)))

    # ── 4. Cada estado con la curva de los otros dos, y la rebaja y el frío con la curva nueva
    x = cociente(d, **mejor)
    lx = np.log(np.maximum(x, 0.02))
    log('\n4. CADA ESTADO CON LA CURVA DE LOS OTROS DOS (parámetros mejores)')
    for est in ESTADOS:
        a, b = (d['estado'] != est).to_numpy(), (d['estado'] == est).to_numpy()
        p = np.interp(lx[b], LREJ, r16.curva(lx[a], y[a], w[a]))
        log(f'   {est}: mérito {1 - ((p - y[b]) ** 2).mean() / ((y[b].mean() - y[b]) ** 2).mean():+.3f} · curva solo con {est} (x → %): ' +
            ' · '.join(f'{c0}→{100 * c1:.0f}' for c0, c1 in zip(r16.REJILLA, r16.curva(lx[b], y[b], w[b]))))
    pc = r16.curva(lx, y, w)
    log('   curva común (x → %): ' + ' · '.join(f'{c0}→{100 * c1:.0f}' for c0, c1 in zip(r16.REJILLA, pc)))
    oof = r16.fuera_de_muestra(d, x, w, folds)
    reb = oof * (f + (1 - f) * np.clip((oof - 0.45) / 0.25, 0, 1))
    for nombre, p in (('sin rebaja ni frío', oof), ('con rebaja', reb), ('con frío extremo', 1 - (1 - oof) * (1 - pf))):
        mm = merito(p, d)
        log(f'   {nombre}: ' + ' · '.join(f'{e} {mm[e]:+.3f}' for e in ESTADOS))
    for a in (1, 2, 3):
        m = il & (d['ant'] == a).to_numpy()
        log(f'   IL fiabilidad nueva, antelación {a}: {tabla(oof[m], y[m])}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
