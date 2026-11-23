#!/usr/bin/env python3
"""
18_backtest_estado.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Prueba del índice contra cierres reales, para cualquier estado: recalcula lo
que el NBM preveía la tarde anterior (ciclo de las 23 UTC) de cada día de los
inviernos 2021-22 a 2025-26, con el mismo código que la web (05 y 07).

Es 14_backtest_sc.py generalizado. Guarda las filas del estado pedido y,
además, el índice completo de cada ciclo (todos los distritos), para no tener
que volver a bajar el archivo del NBM cuando llegue la verdad de otro estado.

Salida:  salida/backtest/<estado>.csv              una fila por distrito, mañana y ciclo
         salida/backtest/todo/indice_<ciclo>.csv.gz   todos los distritos
Uso:     18_backtest_estado.py IL [2021-22 2022-23 …]     (sin inviernos: los cinco)
"""
import subprocess
import sys
from datetime import date, timedelta

import pandas as pd

import nbm_comun as nc

PY = str(nc.BASE / 'venv' / 'bin' / 'python3')
SCR = nc.BASE / 'scripts'
SAL = nc.BASE / 'salida' / 'backtest'
TODO = SAL / 'todo'
CICLO = 23
INVIERNOS = ['2025-26', '2024-25', '2023-24', '2022-23', '2021-22']


def log(msg):
    print(msg, flush=True)


def main():
    est = sys.argv[1].upper()
    TODO.mkdir(parents=True, exist_ok=True)
    d = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})
    ids = set(d.loc[d['estado'] == est, 'leaid'])
    salida = SAL / f'{est.lower()}.csv'
    hechos = set(pd.read_csv(salida, usecols=['ciclo'])['ciclo']) if salida.exists() else set()
    for inv in (sys.argv[2:] or INVIERNOS):
        a = int(inv[:4])
        dia, fin = date(a, 12, 1), date(a + 1, 3, 15)
        log(f'=== invierno {inv}')
        while dia <= fin:
            ciclo = f'{dia:%Y%m%d}_{CICLO:02d}'
            dia += timedelta(days=1)
            if ciclo in hechos:
                continue
            guardado = TODO / f'indice_{ciclo}.csv.gz'
            if guardado.exists():
                x = pd.read_csv(guardado, dtype={'leaid': str}, low_memory=False)
            else:
                r = subprocess.run(['nice', '-n', '12', PY, str(SCR / '05_extrae_nbm.py'), '--fecha', ciclo[:8], '--ciclo', str(CICLO), '--dias', '3'],
                                   cwd=SCR, capture_output=True, text=True)
                dias = nc.BASE / 'trabajo' / f'dias_{ciclo}.csv'
                if r.returncode or not dias.exists():
                    log(f'{ciclo}: sin datos del NBM ({(r.stderr or r.stdout).strip()[-100:]})')
                    continue
                subprocess.run([PY, str(SCR / '07_indice.py'), '--prueba', '--ciclo', ciclo], cwd=SCR, capture_output=True, text=True)
                ind = nc.BASE / 'salida' / 'prueba' / f'indice_{ciclo}.csv'
                for f in (dias, nc.BASE / 'trabajo' / f'nbm_{ciclo}.npz'):
                    f.unlink(missing_ok=True)
                if not ind.exists():
                    log(f'{ciclo}: el índice no salió')
                    continue
                x = pd.read_csv(ind, dtype={'leaid': str}, low_memory=False)
                x.to_csv(guardado, index=False, compression='gzip')
                ind.unlink()
            x = x[x['leaid'].isin(ids)].copy()
            x['ciclo'] = ciclo
            x['invierno'] = inv
            x.to_csv(salida, mode='a', header=not salida.exists(), index=False)
            log(f'{ciclo}: {len(x)} filas · x máx {((x.r_nieve ** 2 + x.r_hielo ** 2 + x.r_frio ** 2) ** 0.5).max():.2f}')
    log('FIN')
    return 0


if __name__ == '__main__':
    sys.exit(main())
