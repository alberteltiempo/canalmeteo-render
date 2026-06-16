"""
Visibilidad de planetas brillantes para 2026.
Datos de in-the-sky.org / Stellarium.
Cada planeta tiene un 'mejor_momento' (mes-rango) y 'visible_en' (mañana/tarde/noche).
Solo los planetas visibles a simple vista: Mercurio, Venus, Marte, Júpiter, Saturno.
"""

# Por mes (1-12), cuáles planetas son fácilmente visibles desde lat ~30°N y cuándo
# 'momento' = 'amanecer' | 'atardecer' | 'noche' | 'madrugada'
# 'magnitud' aproximada (más bajo = más brillante; -4 muy brillante, +2 apenas visible)

VISIBILIDAD_2026 = {
    1: [  # Enero 2026
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -4.4, 'descripcion': 'Mirar al este'},
        {'planeta': 'Marte', 'momento': 'noche', 'magnitud': 1.2, 'descripcion': 'Toda la noche'},
        {'planeta': 'Júpiter', 'momento': 'atardecer', 'magnitud': -2.1, 'descripcion': 'Mirar al oeste'},
    ],
    2: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -4.3, 'descripcion': 'Mirar al este'},
        {'planeta': 'Marte', 'momento': 'noche', 'magnitud': 1.0, 'descripcion': 'Toda la noche'},
        {'planeta': 'Júpiter', 'momento': 'atardecer', 'magnitud': -2.0, 'descripcion': 'Bajo al oeste'},
    ],
    3: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -4.1, 'descripcion': 'Mirar al este'},
        {'planeta': 'Marte', 'momento': 'noche', 'magnitud': 0.7, 'descripcion': 'Alto en el cielo'},
    ],
    4: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -4.0, 'descripcion': 'Mirar al este'},
        {'planeta': 'Marte', 'momento': 'atardecer', 'magnitud': 0.5, 'descripcion': 'Mirar al sur'},
        {'planeta': 'Saturno', 'momento': 'amanecer', 'magnitud': 1.0, 'descripcion': 'Bajo al este'},
    ],
    5: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -3.9, 'descripcion': 'Mirar al este'},
        {'planeta': 'Marte', 'momento': 'atardecer', 'magnitud': 0.5, 'descripcion': 'Mirar al oeste'},
        {'planeta': 'Saturno', 'momento': 'madrugada', 'magnitud': 0.9, 'descripcion': 'Mirar al sureste'},
        {'planeta': 'Júpiter', 'momento': 'amanecer', 'magnitud': -2.0, 'descripcion': 'Mirar al este'},
    ],
    6: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -3.9, 'descripcion': 'Mirar al este'},
        {'planeta': 'Saturno', 'momento': 'madrugada', 'magnitud': 0.7, 'descripcion': 'Mirar al sur'},
        {'planeta': 'Júpiter', 'momento': 'amanecer', 'magnitud': -2.0, 'descripcion': 'Mirar al este'},
        {'planeta': 'Mercurio', 'momento': 'atardecer', 'magnitud': 0.0, 'descripcion': 'Mejor visión del año'},
    ],
    7: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -3.9, 'descripcion': 'Mirar al este'},
        {'planeta': 'Saturno', 'momento': 'noche', 'magnitud': 0.5, 'descripcion': 'Sale tras medianoche'},
        {'planeta': 'Júpiter', 'momento': 'madrugada', 'magnitud': -2.1, 'descripcion': 'Mirar al este'},
    ],
    8: [
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -3.9, 'descripcion': 'Mirar al este'},
        {'planeta': 'Saturno', 'momento': 'noche', 'magnitud': 0.4, 'descripcion': 'Casi toda la noche'},
        {'planeta': 'Júpiter', 'momento': 'madrugada', 'magnitud': -2.2, 'descripcion': 'Mirar al este'},
    ],
    9: [
        {'planeta': 'Saturno', 'momento': 'noche', 'magnitud': 0.3, 'descripcion': 'Máximo brillo'},
        {'planeta': 'Júpiter', 'momento': 'madrugada', 'magnitud': -2.4, 'descripcion': 'Desde la medianoche'},
        {'planeta': 'Venus', 'momento': 'amanecer', 'magnitud': -3.9, 'descripcion': 'Bajo al este'},
    ],
    10: [
        {'planeta': 'Saturno', 'momento': 'noche', 'magnitud': 0.5, 'descripcion': 'Casi toda la noche'},
        {'planeta': 'Júpiter', 'momento': 'noche', 'magnitud': -2.5, 'descripcion': 'Mirar al este'},
        {'planeta': 'Mercurio', 'momento': 'atardecer', 'magnitud': 0.0, 'descripcion': 'Bajo al oeste'},
    ],
    11: [
        {'planeta': 'Saturno', 'momento': 'atardecer', 'magnitud': 0.7, 'descripcion': 'Mirar al sur'},
        {'planeta': 'Júpiter', 'momento': 'noche', 'magnitud': -2.6, 'descripcion': 'Máximo brillo'},
        {'planeta': 'Mercurio', 'momento': 'atardecer', 'magnitud': 0.2, 'descripcion': 'Bajo al oeste'},
    ],
    12: [
        {'planeta': 'Saturno', 'momento': 'atardecer', 'magnitud': 0.9, 'descripcion': 'Mirar al suroeste'},
        {'planeta': 'Júpiter', 'momento': 'noche', 'magnitud': -2.6, 'descripcion': 'Toda la noche'},
        {'planeta': 'Marte', 'momento': 'amanecer', 'magnitud': 1.5, 'descripcion': 'Mirar al este'},
    ],
}

def obtener_visibilidad(mes):
    """Devuelve la lista de planetas visibles este mes."""
    return VISIBILIDAD_2026.get(mes, [])

if __name__ == '__main__':
    # Test
    from datetime import datetime
    mes = datetime.now().month
    print(f"=== PLANETAS VISIBLES EN MES {mes} ===")
    for p in obtener_visibilidad(mes):
        print(f"  {p['planeta']:10} ({p['momento']:10}) mag {p['magnitud']:+.1f}  -  {p['descripcion']}")
