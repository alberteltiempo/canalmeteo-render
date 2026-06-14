import React from "react";
import { ScenePlaceholder } from "../components/ScenePlaceholder";
import { ActiveStorms } from "../types";

// FASE 1: placeholder.
// FASE SIGUIENTE: dibujar genesis.areas con bins NHC <40 / 40-60 / >60
// (#ffd24a / #ff8c00 / #e53935) + perturbaciones.
export const GenesisAreas: React.FC<{ data: ActiveStorms }> = ({ data }) => {
  const n = data.genesis?.areas?.length ?? 0;
  return (
    <ScenePlaceholder
      topic="ZONAS DE DESARROLLO"
      title="Áreas a vigilar"
      subtitle={n ? `${n} área(s) con potencial de desarrollo` : "Cuenca atlántica y Pacífico este"}
    />
  );
};
