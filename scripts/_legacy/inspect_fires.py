#!/usr/bin/env python3
import json
import sys

# Leer archivo
with open('/opt/canalmeteo/data/fires/raw/raw_fires_20260106_1745.geojson', 'r') as f:
    data = json.load(f)

print(f"Total features: {len(data.get('features', []))}\n")

if data.get('features'):
    # Ver primer feature
    first = data['features'][0]
    props = first.get('properties', {})
    
    print("="*80)
    print("TODOS LOS CAMPOS DEL PRIMER FEATURE:")
    print("="*80)
    for key in sorted(props.keys()):
        value = props[key]
        print(f"{key:45s} = {str(value)[:70]}")
    
    print("\n" + "="*80)
    print("CAMPOS QUE CONTIENEN 'ACRE', 'AREA', 'SIZE':")
    print("="*80)
    for key in props.keys():
        if any(word in key.lower() for word in ['acre', 'area', 'size']):
            print(f"{key:45s} = {props[key]}")
    
    print("\n" + "="*80)
    print("PRIMEROS 20 INCENDIOS - VALORES DE TAMAÑO:")
    print("="*80)
    for i, feature in enumerate(data['features'][:20]):
        props = feature.get('properties', {})
        
        # Buscar cualquier campo con acres/area/size
        size_info = []
        for key, value in props.items():
            if any(word in key.lower() for word in ['acre', 'area', 'size']) and value:
                size_info.append(f"{key}={value}")
        
        name = props.get('IncidentName') or props.get('attr_IncidentName') or props.get('poly_IncidentName') or 'Unknown'
        print(f"{i+1:3d}. {str(name)[:40]:40s} | {', '.join(size_info) if size_info else 'NO SIZE FIELD'}")
