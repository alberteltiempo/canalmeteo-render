#!/usr/bin/env python3
"""
14_backtest_sc.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Prueba del índice contra cierres REALES: Carolina del Sur, inviernos 2021-22 a
2025-26 (los que tienen archivo del NBM y datos en los informes del estado).

Verdad: fuentes/cierres_sc/cierres_sc.csv (13_cierres_sc.py), de los «Annual
Report on Missed School Days» del Departamento de Educación de Carolina del Sur.
A diferencia de Kentucky, aquí las jornadas a distancia SÍ tienen fecha: una
mañana cuenta como «sin clase presencial» si el distrito tiene ese día una fila
por el tiempo, sea cierre o eLearning.

Pronóstico: NBM de la tarde anterior (ciclo de las 23 UTC) del archivo de NOAA,
con el mismo código que la web (05 y 07). Solo se guardan los cocientes; la
curva se ajusta después.

Salida:  salida/backtest/sc.csv   una fila por distrito, mañana y ciclo
Uso:     14_backtest_sc.py [2021-22 2022-23 …]     (sin argumentos: los cinco)
"""
import subprocess
import sys
from datetime import date, timedelta

import pandas as pd

import nbm_comun as nc

PY = str(nc.BASE / 'venv' / 'bin' / 'python3')
SCR = nc.BASE / 'scripts'
SAL = nc.BASE / 'salida' / 'backtest'
CICLO = 23
INVIERNOS = ['2025-26', '2024-25', '2023-24', '2022-23', '2021-22']


def log(msg):
    print(msg, flush=True)


def main():
    SAL.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})
    sc = set(d.loc[d['estado'] == 'SC', 'leaid'])
    salida = SAL / 'sc.csv'
    hechos = set(pd.read_csv(salida, usecols=['ciclo'])['ciclo']) if salida.exists() else set()
    for inv in (sys.argv[1:] or INVIERNOS):
        a = int(inv[:4])
        dia, fin = date(a, 12, 1), date(a + 1, 3, 15)
        log(f'=== invierno {inv}')
        while dia <= fin:
            ciclo = f'{dia:%Y%m%d}_{CICLO:02d}'
            dia += timedelta(days=1)
            if ciclo in hechos:
                continue
            r = subprocess.run(['nice', '-n', '12', PY, str(SCR / '05_extrae_nbm.py'), '--fecha', ciclo[:8], '--ciclo', str(CICLO), '--dias', '3'],
                               cwd=SCR, capture_output=True, text=True)
            dias = nc.BASE / 'trabajo' / f'dias_{ciclo}.csv'
            if r.returncode or not dias.exists():
                log(f'{ciclo}: sin datos del NBM ({(r.stderr or r.stdout).strip()[-100:]})')
                continue
            subprocess.run([PY, str(SCR / '07_indice.py'), '--prueba', '--ciclo', ciclo], cwd=SCR, capture_output=True, text=True)
            ind = nc.BASE / 'salida' / 'prueba' / f'indice_{ciclo}.csv'
            if ind.exists():
                x = pd.read_csv(ind, dtype={'leaid': str}, low_memory=False)
                x = x[x['leaid'].isin(sc)].copy()
                x['ciclo'] = ciclo
                x['invierno'] = inv
                x.to_csv(salida, mode='a', header=not salida.exists(), index=False)
                log(f'{ciclo}: {len(x)} filas · x máx {((x.r_nieve ** 2 + x.r_hielo ** 2 + x.r_frio ** 2) ** 0.5).max():.2f}')
                ind.unlink()
            for f in (dias, nc.BASE / 'trabajo' / f'nbm_{ciclo}.npz'):
                f.unlink(missing_ok=True)
    log('FIN')
    return 0


if __name__ == '__main__':
    sys.exit(main())
