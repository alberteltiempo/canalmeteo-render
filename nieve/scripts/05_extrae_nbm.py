#!/usr/bin/env python3
"""
05_extrae_nbm.py — ¿Hay clases? (Canal Meteo TV)
────────────────────────────────────────────────────────────────────────
Pronóstico del NBM por distrito escolar (medido donde están sus escuelas), hora a hora y resumido por mañana de
clase en hora local. Guarda en disco, no publica nada.

Qué lee del NBM (AWS, por rango de bytes): nieve (ASNOW), hielo (FICEAC),
sensación térmica (APTMP), temperatura, viento, racha y nieve en el suelo (SNOD).

Resolución del NBM: hora a hora hasta +48 h; después, temperatura y viento cada
3 h y nieve/hielo en tramos de 6 h. Aquí todo se lleva a una serie horaria: los
tramos de 6 h se reparten por igual entre sus horas y lo instantáneo se interpola.

Salida (nieve/trabajo):
  trabajo/nbm_<fecha>_<ciclo>.npz       series horarias por distrito
  trabajo/dias_<fecha>_<ciclo>.csv     una fila por distrito y mañana de clase

Ventanas de cada mañana de clase (hora local del distrito):
  noche   18:00 de la víspera → 07:00     clase  07:00 → 15:00
  bus     06:00 → 08:00                   suelo  nieve en el suelo a las 06:00
  tarde   12:00 → 18:00 de la víspera

Uso:
  /opt/canalmeteo/nieve/venv/bin/python3 05_extrae_nbm.py [--fecha AAAAMMDD --ciclo HH] [--dias 3]
"""
import argparse
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import nbm_comun as nc

# nombre: (variable NBM, nivel, tipo, estadísticos por distrito)
CAMPOS = {
    'nieve':  ('ASNOW',  'surface',            'acum', ('media', 'max')),
    'hielo':  ('FICEAC', 'surface',            'acum', ('media', 'max')),
    'sens':   ('APTMP',  '2 m above ground',   'inst', ('media', 'min')),
    'temp':   ('TMP',    '2 m above ground',   'inst', ('media',)),
    'viento': ('WIND',   '10 m above ground',  'inst', ('media',)),
    'racha':  ('GUST',   '10 m above ground',  'inst', ('media', 'max')),
    'suelo':  ('SNOD',   'surface',            'inst', ('media',)),
}
HORARIO_HASTA = 48          # el NBM da acumulados de 1 h hasta aquí
M_A_IN, MM_A_IN, MS_A_MPH = 39.3701, 1 / 25.4, 2.23694
PROCESOS = 12

_P = None


def log(msg):
    print(msg, flush=True)


def _pesos():
    global _P
    if _P is None:
        _P = nc.Pesos(nc.FIJOS / 'pesos_escuelas.npz')  # donde están las escuelas
    return _P


def _una_hora(arg):
    """Descarga y resume una hora de pronóstico. Devuelve [(nombre, a, b, {estad: vector})]."""
    fecha, ciclo, fh = arg
    recs = [r for r in nc.indice(fecha, ciclo, fh) if r['det']]
    pedir = []
    for nombre, (var, nivel, tipo, _) in CAMPOS.items():
        for r in recs:
            if r['var'] != var or r['nivel'] != nivel:
                continue
            if tipo == 'inst' and r['tr'] == f'{fh} hour fcst':
                pedir.append((nombre, fh, fh, r))
            elif tipo == 'acum':
                m = re.match(r'(\d+)-(\d+) hour acc fcst$', r['tr'])
                if not m:
                    continue
                a, b = int(m.group(1)), int(m.group(2))
                # 1 h siempre; los tramos de 6 h solo donde ya no hay horarios
                if b - a == 1 or (b - a == 6 and b > HORARIO_HASTA):
                    pedir.append((nombre, a, b, r))
    with ThreadPoolExecutor(8) as ex:
        msgs = list(ex.map(lambda q: nc.rango(fecha, ciclo, fh, q[3]['off'], q[3]['fin']), pedir))
    p = _pesos()
    out = []
    for (nombre, a, b, _), msg in zip(pedir, msgs):
        campo, rej = nc.decodifica(msg)
        p.comprueba(rej)
        est = {}
        for e in CAMPOS[nombre][3]:
            est[e] = {'media': p.media, 'max': p.maximo, 'min': p.minimo}[e](campo)
        out.append((nombre, a, b, est))
    return fh, out


def serie_acum(tramos, hmax, n):
    """Tramos (a, b, vector) → matriz [hmax+1, n] con lo acumulado en cada hora (h-1, h]."""
    s = np.full((hmax + 1, n), np.nan, dtype='float32')
    for a, b, v in sorted(tramos, key=lambda t: t[1] - t[0]):
        if b > hmax:
            continue
        if b - a == 1:
            s[b] = v
        else:
            # Tramo largo: lo que quede tras las horas ya rellenas, a partes iguales
            trozo = s[a + 1:b + 1]
            falta = np.isnan(trozo)
            resto = np.clip(v - np.nansum(trozo, axis=0), 0, None) / np.maximum(falta.sum(axis=0), 1)
            s[a + 1:b + 1] = np.where(falta, resto, trozo)
    return s


def serie_inst(muestras, hmax, n):
    """Muestras (h, vector) → matriz [hmax+1, n] interpolada en el tiempo."""
    s = np.full((hmax + 1, n), np.nan, dtype='float32')
    ms = sorted((h, v) for h, v in muestras if h <= hmax)
    for (h0, v0), (h1, v1) in zip(ms, ms[1:]):
        for h in range(h0, h1 + 1):
            f = (h - h0) / (h1 - h0)
            s[h] = v0 * (1 - f) + v1 * f
    return s


def festivo(d):
    """Días sin clase en casi todos los distritos: Acción de Gracias (jueves y viernes), del 24 de
    diciembre al 1 de enero y el día de Martin Luther King. Cada distrito tiene además su propio
    calendario (vacaciones más largas, días de formación), que aquí no se conoce."""
    if d.month == 11 and ((d.weekday() == 3 and 22 <= d.day <= 28) or (d.weekday() == 4 and 23 <= d.day <= 29)):
        return True
    if (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day == 1):
        return True
    return d.month == 1 and d.weekday() == 0 and 15 <= d.day <= 21


def mananas(inicio, tz, dias):
    """Próximas mañanas de clase (lunes a viernes no festivos) cuyas 07:00 locales aún no han llegado."""
    z = ZoneInfo(tz)
    d = inicio.astimezone(z).date()
    out = []
    while len(out) < dias:
        m7 = datetime(d.year, d.month, d.day, 7, tzinfo=z)
        if d.weekday() < 5 and not festivo(d) and m7 > inicio:
            out.append(d)
        d += timedelta(days=1)
    return out


def hora_fcst(inicio, z, dia, hora, desfase_dias=0):
    """Hora de pronóstico (entera) de una hora local."""
    d = dia + timedelta(days=desfase_dias)
    t = datetime(d.year, d.month, d.day, hora, tzinfo=z)
    return int(round((t - inicio).total_seconds() / 3600))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--fecha')
    ap.add_argument('--ciclo', type=int)
    ap.add_argument('--dias', type=int, default=3)
    ap.add_argument('--si-nuevo', action='store_true', help='no hace nada si ese ciclo ya se extrajo')
    a = ap.parse_args()

    t0 = time.time()
    if a.fecha and a.ciclo is not None:
        fecha, ciclo, horas = a.fecha, a.ciclo, nc.horas_disponibles(a.fecha, a.ciclo)
    else:
        fecha, ciclo, horas = nc.ultimo_ciclo()
    if a.si_nuevo and (nc.BASE / 'trabajo' / f'dias_{fecha}_{ciclo:02d}.csv').exists():
        log(f'Ciclo NBM {fecha} {ciclo:02d}z ya estaba extraído')
        return 0
    inicio = datetime.strptime(f'{fecha}{ciclo:02d}', '%Y%m%d%H').replace(tzinfo=timezone.utc)
    log(f'Ciclo NBM {fecha} {ciclo:02d}z · {len(horas)} horas publicadas (hasta +{horas[-1]} h)')

    tabla = pd.read_csv(nc.FIJOS / 'distritos.csv', dtype={'leaid': str})
    p = _pesos()
    assert (tabla['leaid'].to_numpy() == p.leaid).all(), 'distritos.csv y pesos_nbm.npz no coinciden'
    n = len(tabla)

    # Hasta dónde hay que leer: las 15:00 del último día en la zona más al oeste
    plan = {tz: mananas(inicio, tz, a.dias) for tz in tabla['tz'].unique()}
    hfin = max(hora_fcst(inicio, ZoneInfo(tz), ds[-1], 15) for tz, ds in plan.items())
    usar = [h for h in horas if h <= hfin]
    usar += [h for h in horas if h > hfin][:2]  # para cerrar el último tramo de 6 h
    hmax = usar[-1]
    log(f'Mañanas de clase (hora del Este): {", ".join(str(d) for d in plan.get("America/New_York", []))}')
    log(f'Leyendo {len(usar)} horas de pronóstico (hasta +{hmax} h) …')

    acum = {k: [] for k, c in CAMPOS.items() if c[2] == 'acum'}
    inst = {k: [] for k, c in CAMPOS.items() if c[2] == 'inst'}
    with ProcessPoolExecutor(PROCESOS) as ex:
        for fh, out in ex.map(_una_hora, [(fecha, ciclo, h) for h in usar]):
            for nombre, ta, tb, est in out:
                (acum if nombre in acum else inst)[nombre].append((ta, tb, est))
    log(f'  leído en {time.time() - t0:.0f} s')

    # Series horarias por distrito, ya en unidades de EE. UU. (in, °F, mph)
    conv = {'nieve': lambda v: v * M_A_IN, 'hielo': lambda v: v * MM_A_IN, 'suelo': lambda v: v * M_A_IN,
            'sens': lambda v: (v - 273.15) * 1.8 + 32, 'temp': lambda v: (v - 273.15) * 1.8 + 32,
            'viento': lambda v: v * MS_A_MPH, 'racha': lambda v: v * MS_A_MPH}
    S = {}
    for nombre, lista in acum.items():
        for e in CAMPOS[nombre][3]:
            S[f'{nombre}_{e}'] = conv[nombre](serie_acum([(ta, tb, est[e]) for ta, tb, est in lista], hmax, n))
    for nombre, lista in inst.items():
        for e in CAMPOS[nombre][3]:
            S[f'{nombre}_{e}'] = conv[nombre](serie_inst([(tb, est[e]) for _, tb, est in lista], hmax, n))
    for k, v in S.items():
        log(f'  {k:13s} horas con dato: {int(np.isfinite(v).any(axis=1).sum()):3d} · máx {np.nanmax(v):8.2f} · mín {np.nanmin(v):8.2f}')

    (nc.BASE / 'trabajo').mkdir(exist_ok=True)
    np.savez_compressed(nc.BASE / 'trabajo' / f'nbm_{fecha}_{ciclo:02d}.npz', leaid=p.leaid,
                        inicio=inicio.isoformat(), **S)

    # Resumen por mañana de clase, zona horaria a zona horaria
    def suma(s, sel, h0, h1):
        """Acumulado en (h0, h1] y parte de la ventana que cubre el pronóstico."""
        hs = np.arange(max(h0 + 1, 1), min(h1, hmax) + 1)
        if len(hs) == 0:
            return np.full(sel.sum(), np.nan), 0.0
        return np.nansum(s[hs][:, sel], axis=0), len(hs) / (h1 - h0)

    def extremo(s, sel, h0, h1, f):
        hs = np.arange(max(h0, 1), min(h1, hmax) + 1)
        if len(hs) == 0:
            return np.full(sel.sum(), np.nan)
        return f(s[hs][:, sel], axis=0)

    filas = []
    for tz, ds in plan.items():
        z = ZoneInfo(tz)
        sel = (tabla['tz'] == tz).to_numpy()
        for k, dia in enumerate(ds, 1):
            h18 = hora_fcst(inicio, z, dia, 18, -1)
            h6, h7, h8, h15 = (hora_fcst(inicio, z, dia, h) for h in (6, 7, 8, 15))
            nn, cob = suma(S['nieve_media'], sel, h18, h7)
            f = pd.DataFrame({
                'leaid': p.leaid[sel], 'dia': k, 'fecha': str(dia),
                'nieve_tarde_in': suma(S['nieve_media'], sel, hora_fcst(inicio, z, dia, 12, -1), h18)[0],
                'nieve_noche_in': nn,
                'nieve_noche_max_in': suma(S['nieve_max'], sel, h18, h7)[0],
                'nieve_clase_in': suma(S['nieve_media'], sel, h7, h15)[0],
                'hielo_noche_in': suma(S['hielo_media'], sel, h18, h7)[0],
                'hielo_clase_in': suma(S['hielo_media'], sel, h7, h15)[0],
                'sens_bus_f': extremo(S['sens_media'], sel, h6, h8, np.nanmin),
                'temp_min_noche_f': extremo(S['temp_media'], sel, h18, h7, np.nanmin),
                'racha_max_mph': extremo(S['racha_max'], sel, h6 - 1, h8 + 1, np.nanmax),
                'suelo_in': S['suelo_media'][h6][sel] if 1 <= h6 <= hmax else np.nan,
                'cobertura_noche': round(cob, 2),
                'detalle': '1 h' if h15 <= HORARIO_HASTA else ('1 h y 6 h' if h18 < HORARIO_HASTA else '6 h'),
            })
            filas.append(f)
    r = pd.concat(filas, ignore_index=True)
    num = r.select_dtypes('number').columns.drop(['dia'])
    r[num] = r[num].round(2)
    sal = nc.BASE / 'trabajo'
    sal.mkdir(parents=True, exist_ok=True)
    ruta = sal / f'dias_{fecha}_{ciclo:02d}.csv'
    r.to_csv(ruta, index=False)

    log('── Resumen ──')
    log(f'  {ruta} · {len(r)} filas · {time.time() - t0:.0f} s en total')
    v = r.merge(tabla[['leaid', 'nombre', 'estado']], on='leaid')
    for k in sorted(v['dia'].unique()):
        d = v[v['dia'] == k]
        log(f'  Día {k} ({d["fecha"].mode()[0]}, detalle {d["detalle"].mode()[0]}): '
            f'con ≥1 in de nieve de noche {int((d["nieve_noche_in"] >= 1).sum())} · '
            f'≥3 in {int((d["nieve_noche_in"] >= 3).sum())} · con hielo ≥0,05 in {int((d["hielo_noche_in"] >= 0.05).sum())} · '
            f'sensación ≤0 °F {int((d["sens_bus_f"] <= 0).sum())} · sin dato de nieve {int(d["nieve_noche_in"].isna().sum())}')
        cols = ['nombre', 'estado', 'nieve_noche_in', 'nieve_clase_in', 'hielo_noche_in', 'sens_bus_f', 'suelo_in']
        log(d.nlargest(6, 'nieve_noche_in')[cols].to_string(index=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
