python3 << 'EOF'
import numpy as np

# Simular el problema
precip_flag = np.array([-3, -3, 0, 1, 2, 3, 10])
PRECIP_SNOW = [2, 96, -3]

mask_snow = np.isin(precip_flag, PRECIP_SNOW)
print(f"PrecipFlag: {precip_flag}")
print(f"PRECIP_SNOW: {PRECIP_SNOW}")
print(f"Máscara nieve: {mask_snow}")
print(f"-3 detectado como nieve: {mask_snow[0]}")
EOF
