# SPDX-License-Identifier: GPL-3.0-or-later
"""Importación de recetas desde URL (spec §3.2, Task 12).

Pipeline:
1. Descarga el HTML con httpx (inyectable en tests; no se scrapea nada que el
   usuario/agente no haya pedido).
2. Extrae JSON-LD con `recipe-scrapers` en modo genérico (`wild_mode`), para
   aceptar cualquier sitio de cocina que publique schema.org/Recipe.
3. Mapea cada ingrediente al catálogo por nombre/alias y convierte medidas
   caseras a la unidad canónica con la tabla de equivalencias (Anexo A).
4. Los ingredientes que no se pueden estructurar **no se inventan**: se
   devuelven y se guardan en `recipe_import_jobs.result_json` con su motivo y
   sugerencias. La receta draft conserva solo lo que quedó estructurado.

Cada importación con `dry_run=False` deja un `recipe_import_job` con estado
`completed` o `failed` (con `error_message`), incluso si la URL es inválida.
"""

import difflib
import re
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from recipe_scrapers import scrape_html
from sqlmodel import Session, select

from app.models import ProductCatalog, RecipeImportJob
from app.models.enums import ImportSourceType, ImportStatus
from app.seed_data.equivalences import (
    PESO_POR_CUCHARADA_G,
    PESO_POR_TAZA_G,
)
from app.services.recipes import IngredienteIn, PasoIn, RecetaIn, RecetaInvalida, crear_receta

USER_AGENT = "MarketSano/0.1 (+https://github.com/danielsalinasgongora/market-sano)"
MAX_HTML_BYTES = 5_000_000
_TIMEOUT_S = 20.0

# Unidad escrita en la receta → (tipo, mililitros/gramos/unidades de una medida).
_UNIDADES: dict[str, tuple[str, float]] = {
    "kg": ("masa", 1000.0), "kilo": ("masa", 1000.0), "kilos": ("masa", 1000.0),
    "g": ("masa", 1.0), "gr": ("masa", 1.0), "grs": ("masa", 1.0),
    "gramo": ("masa", 1.0), "gramos": ("masa", 1.0),
    "l": ("volumen", 1000.0), "lt": ("volumen", 1000.0), "lts": ("volumen", 1000.0),
    "litro": ("volumen", 1000.0), "litros": ("volumen", 1000.0),
    "ml": ("volumen", 1.0), "cc": ("volumen", 1.0),
    "unidad": ("discreta", 1.0), "unidades": ("discreta", 1.0),
    "un": ("discreta", 1.0), "u": ("discreta", 1.0),
    "docena": ("discreta", 12.0), "docenas": ("discreta", 12.0),
    "cucharada": ("cucharada", 15.0), "cucharadas": ("cucharada", 15.0),
    "cda": ("cucharada", 15.0), "cdas": ("cucharada", 15.0),
    "cucharadita": ("cucharadita", 5.0), "cucharaditas": ("cucharadita", 5.0),
    "cdta": ("cucharadita", 5.0), "cdtas": ("cucharadita", 5.0),
    "taza": ("taza", 240.0), "tazas": ("taza", 240.0), "tz": ("taza", 240.0),
    "vaso": ("vaso", 200.0), "vasos": ("vaso", 200.0),
    "pizca": ("pizca", 0.5), "pizcas": ("pizca", 0.5),
}

# Unidades reales que el catálogo no sabe convertir: se marcan como no resueltas.
_UNIDADES_NO_CONVERTIBLES = {
    "diente", "dientes", "rama", "ramas", "hoja", "hojas", "lata", "latas",
    "paquete", "paquetes", "sobre", "sobres", "tarro", "tarros", "chorrito",
    "manojo", "manojos", "puñado", "puñados", "pastilla", "pastillas",
    "sachet", "sachets", "cabeza", "cabezas",
}

_FRACCIONES = {"½": 0.5, "¼": 0.25, "¾": 0.75, "⅓": 1 / 3, "⅔": 2 / 3, "⅛": 0.125}
_FILLER_INICIAL = re.compile(
    r"^(de|del|la|el|los|las|un|una|unos|unas|"
    r"dientes?|ramas?|hojas?|latas?|paquetes?|sobres?|tarros?)\s+",
    re.IGNORECASE,
)
_FILLER_UNIDAD = {"sopera", "soperas", "colamada", "colmada", "colmadas", "rasa", "rasas"}


class ImportInvalido(ValueError):
    """La URL/página no permite importar una receta (mensaje accionable)."""


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y sin puntuación (para comparar nombres)."""
    sin_tildes = unicodedata.normalize("NFKD", texto.lower())
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", sin_tildes).strip()


def _validar_url(url: str) -> str:
    limpia = (url or "").strip()
    partes = urlparse(limpia)
    if partes.scheme not in ("http", "https") or not partes.netloc:
        raise ImportInvalido(
            f"URL inválida: {url!r}. Debe empezar con http:// o https:// y apuntar a una receta."
        )
    return limpia


def _descargar(url: str) -> str:
    """Descarga el HTML de la receta (función inyectable en tests)."""
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=_TIMEOUT_S,
            headers={"User-Agent": USER_AGENT},
        ) as cliente:
            respuesta = cliente.get(url)
            respuesta.raise_for_status()
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise ImportInvalido(f"No se pudo descargar {url}: {exc}") from exc
    if len(respuesta.content) > MAX_HTML_BYTES:
        raise ImportInvalido(f"La página de {url} es demasiado grande para importarla.")
    return respuesta.text


def _extraer_cantidad(tokens: list[str]) -> tuple[float | None, int]:
    """Consume tokens numéricos al inicio ('1', '1,5', '1/2', '1 y 1/2', '1-2')."""
    cantidad, i, hay = 0.0, 0, False
    while i < len(tokens):
        token = tokens[i].lower().replace(",", ".")
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            cantidad += float(token)
        elif re.fullmatch(r"\d+/\d+", token):
            numerador, denominador = token.split("/")
            cantidad += float(numerador) / float(denominador)
        elif re.fullmatch(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?", token):
            cantidad += float(token.split("-")[0])  # rango "1-2": el extremo bajo
        elif (
            hay
            and token == "y"
            and i + 1 < len(tokens)
            and re.fullmatch(r"(\d+/\d+|\d+(?:\.\d+)?)", tokens[i + 1].lower())
        ):
            i += 1
            continue
        else:
            break
        hay = True
        i += 1
    return (cantidad if hay else None), i


def _parsear_ingrediente(texto: str) -> tuple[float | None, str | None, str]:
    """(cantidad, unidad normalizada, texto del producto) de una línea libre."""
    limpio = texto.replace("\u00a0", " ").strip()
    for simbolo, valor in _FRACCIONES.items():
        limpio = limpio.replace(simbolo, f" {valor} ")
    limpio = re.sub(r"^[\-•*·\s]+", "", limpio)
    tokens = re.sub(r"\s+", " ", limpio).split()
    cantidad, i = _extraer_cantidad(tokens)

    unidad = None
    if i < len(tokens):
        candidata = _normalizar(tokens[i])
        if candidata in _UNIDADES or candidata in _UNIDADES_NO_CONVERTIBLES:
            unidad = candidata
            i += 1
            if i < len(tokens) and _normalizar(tokens[i]) in _FILLER_UNIDAD:
                i += 1

    return cantidad, unidad, " ".join(tokens[i:]).strip()


def _limpiar_producto(texto: str) -> str:
    """Quita paréntesis, comas y prefijos de cocina ('dientes de…')."""
    limpio = re.sub(r"\([^)]*\)", " ", texto)
    limpio = limpio.split(",")[0]
    for _ in range(4):
        nuevo = _FILLER_INICIAL.sub("", limpio.strip()).strip()
        if nuevo == limpio.strip():
            break
        limpio = nuevo
    return limpio


def _productos_catalogo(session: Session) -> list[ProductCatalog]:
    return list(session.exec(select(ProductCatalog)).all())


def _variantes(nombre: str) -> set[str]:
    """Formas simples de plural/singular en español para comparar nombres."""
    variantes = {nombre}
    if len(nombre) > 3 and nombre.endswith("es"):
        variantes.add(nombre[:-2])
    if len(nombre) > 3 and nombre.endswith("s"):
        variantes.add(nombre[:-1])
    if not nombre.endswith("s"):
        variantes.add(f"{nombre}s")
        variantes.add(f"{nombre}es")
    return variantes


def _buscar_producto(
    texto: str, catalogo: list[ProductCatalog]
) -> tuple[ProductCatalog | None, list[str], str | None]:
    """(producto, sugerencias, motivo). Exige coincidencia exacta o cobertura alta."""
    normalizado = _normalizar(texto)
    if not normalizado:
        return None, [], "no se pudo leer el nombre del producto"
    variantes = _variantes(normalizado)

    for producto in catalogo:
        nombres = {_normalizar(producto.canonical_name)}
        nombres |= {_normalizar(alias) for alias in producto.aliases}
        if nombres & variantes:
            return producto, [], None

    # En español el sustantivo principal va primero: "aceite de girasol" es
    # aceite y "harina leudante" es harina, aunque el nombre exacto no exista.
    prefijos = [
        (len(buscado), producto)
        for producto in catalogo
        for nombre in [producto.canonical_name, *producto.aliases]
        if (buscado := _normalizar(nombre)) and normalizado.startswith(f"{buscado} ")
    ]
    if prefijos:
        prefijos.sort(key=lambda c: c[0], reverse=True)
        return prefijos[0][1], [], None

    candidatos: list[tuple[float, int, ProductCatalog]] = []
    for producto in catalogo:
        for nombre in [producto.canonical_name, *producto.aliases]:
            buscado = _normalizar(nombre)
            if buscado and re.search(rf"\b{re.escape(buscado)}(?:s|es)?\b", normalizado):
                candidatos.append((len(buscado) / len(normalizado), len(buscado), producto))
    if candidatos:
        candidatos.sort(key=lambda c: (c[0], c[1]), reverse=True)
        cobertura, _, producto = candidatos[0]
        if cobertura >= 0.6:
            return producto, [], None
        sugerencias = list(dict.fromkeys(c[2].canonical_name for c in candidatos[:3]))
        return None, sugerencias, f"'{texto}' no coincide con un producto del catálogo"

    por_nombre = {_normalizar(p.canonical_name): p.canonical_name for p in catalogo}
    parecidos = difflib.get_close_matches(normalizado, list(por_nombre), n=3, cutoff=0.75)
    return None, [por_nombre[p] for p in parecidos], (
        f"'{texto}' no está en el catálogo"
    )


def _sugerencias(texto: str, catalogo: list[ProductCatalog]) -> list[str]:
    _, sugerencias, _ = _buscar_producto(texto, catalogo)
    return sugerencias


def _convertir(
    producto: ProductCatalog, cantidad: float, unidad: str | None
) -> tuple[float | None, str | None, str | None]:
    """(cantidad canónica, unidad canónica, motivo si no se puede convertir)."""
    destino = producto.default_unit
    nombre = _normalizar(producto.canonical_name)

    if unidad is None:
        if destino == "unidad":
            return round(cantidad, 2), "unidad", None
        if producto.unit_weight_g:
            return round(cantidad * producto.unit_weight_g, 2), "g", None
        return None, None, (
            f"'{producto.canonical_name}' se mide en {destino}: indica la cantidad en {destino}"
        )

    if unidad in _UNIDADES_NO_CONVERTIBLES:
        return None, None, (
            f"la unidad '{unidad}' no se puede convertir a {destino} en el catálogo"
        )

    tipo, factor = _UNIDADES[unidad]
    valor = cantidad * factor

    if tipo == "masa":
        if destino == "g":
            return round(valor, 2), "g", None
        if destino == "unidad" and producto.unit_weight_g:
            return round(valor / producto.unit_weight_g, 2), "unidad", None
        return None, None, (
            f"'{producto.canonical_name}' se mide en {destino}: no se puede convertir {unidad}"
        )

    if tipo in ("volumen", "taza", "cucharada", "cucharadita", "vaso", "pizca"):
        if destino == "ml":
            return round(valor, 2), "ml", None
        if destino == "g":
            gramos_por_medida = None
            if tipo == "taza":
                gramos_por_medida = PESO_POR_TAZA_G.get(nombre)
            elif tipo == "cucharada":
                gramos_por_medida = PESO_POR_CUCHARADA_G.get(nombre)
            elif tipo == "cucharadita":
                peso_cucharada = PESO_POR_CUCHARADA_G.get(nombre)
                gramos_por_medida = peso_cucharada / 3 if peso_cucharada else None
            if gramos_por_medida:
                return round(cantidad * gramos_por_medida, 2), "g", None
            return None, None, (
                f"no hay equivalencia de {unidad} a gramos para '{producto.canonical_name}'"
            )
        return None, None, (
            f"'{producto.canonical_name}' se mide en {destino}: no se puede convertir {unidad}"
        )

    # discreta (unidad/docena)
    if destino == "unidad":
        return round(valor, 2), "unidad", None
    if producto.unit_weight_g:
        return round(valor * producto.unit_weight_g, 2), "g", None
    return None, None, (
        f"'{producto.canonical_name}' se mide en {destino}: no se puede convertir {unidad}"
    )


def _porciones(texto: Any) -> int:
    if not texto:
        return 4
    coincidencia = re.search(r"\d+", str(texto))
    if not coincidencia:
        return 4
    porciones = int(coincidencia.group())
    return porciones if 1 <= porciones <= 100 else 4


def _minutos(fn: Callable[[], Any]) -> int | None:
    try:
        valor = fn()
    except Exception:  # el scraper no siempre implementa todos los campos
        return None
    if isinstance(valor, (int, float)) and valor > 0:
        return int(valor)
    return None


def _pasos(scraper: Any) -> list[str]:
    try:
        pasos = [p.strip() for p in scraper.instructions_list() if p and p.strip()]
    except Exception:
        pasos = []
    if pasos:
        return pasos
    try:
        texto = scraper.instructions() or ""
    except Exception:
        texto = ""
    return [p.strip() for p in re.split(r"\n+", texto) if p.strip()]


def _campo(fn: Callable[[], Any], default: Any = None) -> Any:
    """Lee un campo opcional del scraper sin romper si el sitio no lo declara."""
    try:
        return fn()
    except Exception:
        return default


def _etiquetas(scraper: Any) -> list[str]:
    etiquetas: set[str] = set()
    crudas = {str(t) for t in (_campo(scraper.keywords, []) or [])}
    for extra in (_campo(scraper.category), _campo(scraper.cuisine)):
        if isinstance(extra, str):
            crudas.add(extra)
        elif isinstance(extra, (list, tuple)):
            crudas |= {str(e) for e in extra}
    for crudo in crudas:
        for etiqueta in re.split(r"[,;]", crudo):
            limpia = etiqueta.strip().lower()
            if limpia:
                etiquetas.add(limpia)
    return sorted(etiquetas)[:12]


def _extraer(html: str, url: str, session: Session) -> dict[str, Any]:
    """HTML → receta estructurada + ingredientes no resueltos (best-effort)."""
    try:
        scraper = scrape_html(html, org_url=url, supported_only=False)
        titulo = (scraper.title() or "").strip()
    except Exception as exc:
        raise ImportInvalido(
            "La página no expone una receta estructurada (JSON-LD schema.org/Recipe). "
            f"Detalle: {exc}"
        ) from exc
    if not titulo:
        raise ImportInvalido("La página no declara el título de una receta.")

    try:
        crudos = [str(i).strip() for i in scraper.ingredients() if str(i).strip()]
    except Exception as exc:
        raise ImportInvalido(f"La receta no declara ingredientes legibles: {exc}") from exc
    if not crudos:
        raise ImportInvalido("La receta no declara ingredientes.")

    catalogo = _productos_catalogo(session)
    resueltos: list[dict[str, Any]] = []
    no_resueltos: list[dict[str, Any]] = []
    for crudo in crudos:
        cantidad, unidad, resto = _parsear_ingrediente(crudo)
        texto_producto = _limpiar_producto(resto)
        if cantidad is None:
            no_resueltos.append({
                "text": crudo,
                "reason": (
                    "sin cantidad (¿'a gusto'?): edítala en la receta o importa con texto "
                    "pegado"
                ),
                "suggestions": _sugerencias(texto_producto, catalogo),
            })
            continue
        producto, sugerencias, motivo = _buscar_producto(texto_producto, catalogo)
        if producto is None:
            no_resueltos.append({
                "text": crudo, "reason": motivo, "suggestions": sugerencias,
            })
            continue
        canonica, unidad_canonica, motivo = _convertir(producto, cantidad, unidad)
        if canonica is None:
            no_resueltos.append({"text": crudo, "reason": motivo, "suggestions": []})
            continue
        resueltos.append({
            "product_id": producto.id,
            "product_name": producto.canonical_name,
            "quantity": canonica,
            "unit": unidad_canonica,
            "raw_text": crudo,
        })

    if not resueltos:
        raise ImportInvalido(
            "Ningún ingrediente se pudo estructurar contra el catálogo. Ajusta los nombres o "
            "agrega los productos con add_product_from_store antes de importar."
        )

    pasos = _pasos(scraper)
    return {
        "title": titulo,
        "description": _campo(scraper.description) or None,
        "base_servings": _porciones(_campo(scraper.yields)),
        "prep_minutes": _minutos(scraper.prep_time),
        "cook_minutes": _minutos(scraper.cook_time),
        "instructions": "\n\n".join(pasos) or None,
        "steps": [{"instruction": paso, "duration_minutes": None} for paso in pasos],
        "tags": _etiquetas(scraper),
        "source_url": url,
        "ingredients": resueltos,
        "unresolved": no_resueltos,
        "is_complete": not no_resueltos,
    }


def _fallar_job(session: Session, job: RecipeImportJob, error: str) -> None:
    job.status = ImportStatus.failed
    job.error_message = error
    job.completed_at = datetime.now(UTC)
    session.add(job)
    session.commit()


def importar_desde_url(
    session: Session,
    household_id: int,
    url: str,
    *,
    dry_run: bool = True,
    created_by: Any = None,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Importa una receta desde URL. `dry_run=True` devuelve la vista previa.

    Con `dry_run=False` siempre queda un `recipe_import_job`: `completed` con el
    resultado o `failed` con `error_message` (URL inválida, sin JSON-LD, etc.).
    """
    job = None
    if not dry_run:
        job = RecipeImportJob(
            household_id=household_id,
            source_type=ImportSourceType.url,
            source_value=(url or "").strip(),
            status=ImportStatus.processing,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

    try:
        limpia = _validar_url(url)
        html = (fetcher or _descargar)(limpia)
        datos = _extraer(html, limpia, session)
        vista: dict[str, Any] = {
            "dry_run": dry_run,
            "job_id": job.id if job else None,
            "recipe_id": None,
            **datos,
        }
        if datos["unresolved"]:
            faltantes = ", ".join(u["text"] for u in datos["unresolved"][:3])
            vista["warning"] = (
                f"{len(datos['unresolved'])} ingrediente(s) no se pudieron estructurar "
                f"({faltantes}); quedaron en el job para revisarlos con add_product_from_store."
            )
        if dry_run:
            return vista

        assert job is not None
        datos_receta = RecetaIn(
            title=datos["title"],
            description=datos["description"],
            base_servings=datos["base_servings"],
            prep_minutes=datos["prep_minutes"],
            cook_minutes=datos["cook_minutes"],
            instructions=datos["instructions"],
            source_url=datos["source_url"],
            ingredients=[
                IngredienteIn(product=i["product_id"], quantity=i["quantity"], unit=i["unit"])
                for i in datos["ingredients"]
            ],
            steps=[PasoIn(**p) for p in datos["steps"]],
            tags=datos["tags"],
        )
        creada = crear_receta(
            session, household_id, datos_receta, dry_run=False, created_by=created_by
        )
        vista["recipe_id"] = creada["recipe_id"]
        job.status = ImportStatus.completed
        job.result_json = vista
        job.completed_at = datetime.now(UTC)
        session.add(job)
        session.commit()
        return vista
    except (ImportInvalido, RecetaInvalida) as exc:
        mensaje = str(exc)
        if job is not None:
            _fallar_job(session, job, mensaje)
        if isinstance(exc, RecetaInvalida):
            raise ImportInvalido(f"No se pudo crear la receta importada: {mensaje}") from exc
        raise
