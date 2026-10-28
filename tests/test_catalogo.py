"""Tests del catálogo de hints por empresa auditora."""

from pathlib import Path

import pytest
import yaml

from comparador.catalogo import (
    EmpresaNoCatalogadaError,
    HintsEmpresa,
    cargar_hints_empresa,
)
from comparador.schemas import EmpresaAuditora

# Lista desplegable 'Tabla de Hallazgos'!F1:F11 de los Excel regulatorios
# (no la hoja Definiciones, que tiene otras grafías).
VOCABULARIO_EXCEL = (
    "Verificación DUF",
    "Verificación ECAP",
    "Ver. Coord. de Protecciones",
    "Ver. 87B/Tpo Máx Despeje Falla",
    "Ver. Acceso, Registro y Sincr.",
    "Prueba Oper. de Protección",
    "Prueba Apert. de Interruptor",
    "Prueba Estabilidad 87T",
    "Prueba Pendiente",
    "Servicios Auxiliares CA-CC",
    "Otros",
)


class TestCargarHintsEmpresa:
    def test_carga_las_tres_empresas(self):
        for empresa in EmpresaAuditora:
            hints = cargar_hints_empresa(empresa)
            assert isinstance(hints, HintsEmpresa)
            assert hints.descripcion_formato.strip()

    def test_ensaut_cubre_las_dos_variantes(self):
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        # Variante A (macro-secciones) y variante B (columna Calificación).
        assert hints.calificacion_por_seccion_visual is True
        assert hints.mapeo_columnas["calificacion"] == ["Calificación"]
        assert hints.mapeo_columnas["clasificacion"] == [
            "Clasificación", "Clasificación del Hallazgo",
        ]
        assert hints.mapeo_columnas["accion_correctiva"] == [
            "Comentario específico", "Acción Correctiva del Hallazgo",
        ]
        assert "Descripción del Hallazgo" in hints.mapeo_columnas["descripcion"]

    def test_ensaut_vocabulario_oficial_literal(self):
        # La unicidad de la Etapa 4 compara la clasificación como texto: el
        # hint debe traer la grafía exacta de la lista desplegable del Excel.
        # Sin colapsar espacios: una etiqueta partida entre líneas del YAML
        # llegaría al prompt con el salto de línea adentro.
        notas = cargar_hints_empresa(EmpresaAuditora.ENSAUT).notas_adicionales
        for etiqueta in VOCABULARIO_EXCEL:
            assert f'"{etiqueta}"' in notas, etiqueta

    def test_reliable_energy_mapeo(self):
        hints = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY)
        assert hints.calificacion_por_seccion_visual is False
        assert hints.mapeo_columnas["descripcion"] == [
            "Conclusión", "Descripción del Hallazgo", "CLASIFICACIÓN DEL HALLAZGO",
        ]
        assert hints.mapeo_columnas["accion_correctiva"] == [
            "Recomendación", "Acción Correctiva del Hallazgo",
            "ACCIÓN CORRECTIVA DEL HALLAZGO",
        ]
        # Su presencia activa el guard de calificación no nula de la Etapa 3.
        assert hints.mapeo_columnas["calificacion"] == [
            "Relevancia Hallazgo", "Calificación", "CALIFICACIÓN",
        ]

    def test_reliable_energy_vocabulario_nuevo(self):
        notas = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY).notas_adicionales
        for etiqueta in (
            "Ver. Tiempo Máx. Actuación",
            "Ver. 87B/Tpo Máx Despeje Falla",
            "Prueba Pendiente",
            "Prueba Oper. de Protección",
        ):
            assert f'"{etiqueta}"' in notas, etiqueta

    def test_reliable_energy_ntsycs_sin_hallazgo_no_se_extrae(self):
        # Tratar "Sin hallazgo" + "No cumple" como hallazgo es decisión
        # pendiente del equipo revisor; además saldría sin calificación y el guard de la
        # Etapa 3 abortaría la corrida.
        notas = cargar_hints_empresa(EmpresaAuditora.RELIABLE_ENERGY).notas_adicionales
        notas_una_linea = " ".join(notas.split())
        assert 'Si la sub-fila dice "Sin hallazgo", no extraigas nada' in notas_una_linea
        assert "terminan en" not in notas_una_linea

    def test_sdi_placeholder_carga_sin_error(self):
        hints = cargar_hints_empresa(EmpresaAuditora.SDI)
        assert "Pendiente" in hints.descripcion_formato
        assert hints.mapeo_columnas == {}

    def test_empresa_ausente_falla_ruidosamente(self, tmp_path: Path):
        ruta = tmp_path / "catalogo_incompleto.yaml"
        ruta.write_text(
            yaml.safe_dump({
                "Ensaut": {
                    "descripcion_formato": "x",
                    "mapeo_columnas": {},
                    "calificacion_por_seccion_visual": False,
                    "identificacion_rele": "x",
                    "notas_adicionales": "x",
                }
            }),
            encoding="utf-8",
        )
        with pytest.raises(EmpresaNoCatalogadaError, match="Sdi"):
            cargar_hints_empresa(EmpresaAuditora.SDI, ruta_catalogo=ruta)

    def test_catalogo_inexistente_falla(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            cargar_hints_empresa(
                EmpresaAuditora.ENSAUT,
                ruta_catalogo=tmp_path / "no_existe.yaml",
            )

    def test_yaml_no_dict_falla_ruidosamente(self, tmp_path: Path):
        ruta = tmp_path / "catalogo_roto.yaml"
        ruta.write_text("- solo\n- una\n- lista\n", encoding="utf-8")
        with pytest.raises(EmpresaNoCatalogadaError):
            cargar_hints_empresa(EmpresaAuditora.ENSAUT, ruta_catalogo=ruta)


class TestEsPlaceholder:
    def _hints(self, descripcion: str, mapeo: dict[str, list[str]]) -> HintsEmpresa:
        return HintsEmpresa(
            descripcion_formato=descripcion,
            mapeo_columnas=mapeo,
            calificacion_por_seccion_visual=False,
            identificacion_rele="x",
            notas_adicionales="x",
        )

    @pytest.mark.parametrize("empresa", list(EmpresaAuditora))
    def test_solo_sdi_es_placeholder(self, empresa: EmpresaAuditora):
        esperado = empresa is EmpresaAuditora.SDI
        assert cargar_hints_empresa(empresa).es_placeholder is esperado

    def test_marcador_pendiente_es_placeholder(self):
        hints = self._hints("[Pendiente de PDF real]", {"descripcion": ["Conclusión"]})
        assert hints.es_placeholder is True

    def test_sin_mapeo_es_placeholder_aunque_reescriban_la_descripcion(self):
        # Un borrador parcial sin mapeo no debe apagar la advertencia.
        hints = self._hints("Formato aún no confirmado", {})
        assert hints.es_placeholder is True


class TestFilasTransversales:
    def test_default_lista_vacia(self):
        hints = HintsEmpresa(
            descripcion_formato="x",
            mapeo_columnas={"descripcion": ["Desc"]},
            calificacion_por_seccion_visual=False,
            identificacion_rele="x",
            notas_adicionales="x",
        )
        assert hints.filas_transversales == []

    def test_ensaut_declara_analisis_de_coordinacion(self):
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        assert any(
            "coordinación" in p or "coordinacion" in p
            for p in hints.filas_transversales
        )

    def test_ensaut_declara_sensibilidad_del_sistema(self):
        # Beta fila 223: "Sensibilidad del sistema de protecciones de la subestación."
        hints = cargar_hints_empresa(EmpresaAuditora.ENSAUT)
        assert "sensibilidad del sistema de protecciones" in hints.filas_transversales
