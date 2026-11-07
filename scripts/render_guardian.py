#!/usr/bin/env python3
"""
render_guardian.py — Canal Meteo TV (nimbus-03, 13/09/2026)
───────────────────────────────────────────────────────────
Vigilante de renders de Remotion colgados. Cron cada 5 min.

El 13/09 un render del trópico se atascó en un fotograma (delayRender de la fuente
que no terminaba) y Remotion abrió una pareja de Chrome por minuto durante 2 h:
276 procesos, 70 GB, RAM y swap llenos. Como `node` y sus Chrome heredan el lock
global de la GPU (/tmp/canalmeteo-render.lock), ningún otro vídeo ni captura pudo
renderizar. El timeout de nhc_check solo mató el bash y dejó el resto huérfano.

Reglas:
  · `remotion render|still` vivo más de LIMITE_RENDER_S → se mata su árbol entero
    (Puppeteer lanza Chrome en otro grupo de procesos: se recorre por ppid) y el
    render.sh que lo lanzó.
  · chrome-headless-shell de Remotion sin ningún `node` en su ascendencia y con más
    de LIMITE_HUERFANO_S → se mata.
Nunca toca procesos que no sean de /opt/canalmeteo/remotion.
"""
import os
import signal
import subprocess
import time

LIMITE_RENDER_S = 35 * 60      # un render normal tarda 2-8 min; nhc_check corta a los 30
LIMITE_HUERFANO_S = 10 * 60
RAIZ = '/opt/canalmeteo/remotion/'


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}] {msg}", flush=True)


def procesos():
    out = subprocess.run(['ps', '-eo', 'pid=,ppid=,etimes=,args='],
                         capture_output=True, text=True).stdout
    tabla = {}
    for linea in out.splitlines():
        partes = linea.split(None, 3)
        if len(partes) < 4:
            continue
        pid, ppid, et, args = int(partes[0]), int(partes[1]), int(partes[2]), partes[3]
        tabla[pid] = {'ppid': ppid, 'etimes': et, 'args': args}
    return tabla


def descendientes(tabla, raiz):
    hijos = {}
    for pid, p in tabla.items():
        hijos.setdefault(p['ppid'], []).append(pid)
    vistos, pila = [], [raiz]
    while pila:
        pid = pila.pop()
        for h in hijos.get(pid, []):
            if h not in vistos:
                vistos.append(h)
                pila.append(h)
    return vistos


def matar(pids, motivo):
    pids = [p for p in pids if p != os.getpid()]
    if not pids:
        return
    log(f"{motivo}: SIGTERM a {len(pids)} procesos")
    for p in pids:
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(10)
    vivos = []
    for p in pids:
        try:
            os.kill(p, 0)
            vivos.append(p)
        except ProcessLookupError:
            pass
    for p in vivos:
        try:
            os.kill(p, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if vivos:
        log(f"  SIGKILL a {len(vivos)} que seguían vivos")


def main():
    tabla = procesos()
    actuado = False
    # 1) renders/stills de Remotion que se pasan de tiempo
    for pid, p in list(tabla.items()):
        a = p['args']
        if 'node' not in a.split(' ', 1)[0] or 'remotion' not in a:
            continue
        if not (' render ' in f' {a} ' or ' still ' in f' {a} '):
            continue
        if p['etimes'] < LIMITE_RENDER_S:
            continue
        cwd = ''
        try:
            cwd = os.readlink(f'/proc/{pid}/cwd')
        except OSError:
            pass
        if not cwd.startswith(RAIZ):
            continue
        arbol = descendientes(tabla, pid)
        # el render.sh (o script) que lo lanzó, si es de Remotion
        padre = tabla.get(p['ppid'], {})
        extra = [p['ppid']] if RAIZ in padre.get('args', '') else []
        matar(extra + [pid] + arbol,
              f"render colgado {p['etimes']//60} min en {cwd} ({a[:90]})")
        actuado = True
    if actuado:
        tabla = procesos()
    # 2) Chrome de Remotion huérfanos (sin node en la ascendencia)
    huerfanos = []
    for pid, p in tabla.items():
        if 'chrome-headless-shell' not in p['args'] or RAIZ not in p['args']:
            continue
        if p['etimes'] < LIMITE_HUERFANO_S:
            continue
        q, con_node = p['ppid'], False
        for _ in range(10):
            if q <= 1 or q not in tabla:
                break
            if 'node' in tabla[q]['args'].split(' ', 1)[0]:
                con_node = True
                break
            q = tabla[q]['ppid']
        if not con_node:
            huerfanos.append(pid)
    if huerfanos:
        matar(huerfanos, 'Chrome de Remotion huérfanos')


if __name__ == '__main__':
    main()
