# SPDX-License-Identifier: GPL-3.0-or-later
"""Matches curados catálogo ↔ cadena, del spike T8 (docs/connectors/spike-2026-11.md).

Formato: (canonical_name, store_url, sku). Precios del 2026-11-18 en el comentario
solo como referencia; el precio real lo trae el conector.
"""

MATCHES_JUMBO: list[tuple[str, str, str]] = [
    ("palta", "https://www.jumbo.cl/pote-palta-hass-premadura-2-un/p", "2032557"),  # Palta Hass Pote 2 un. (un)
    ("tomate", "https://www.jumbo.cl/tomate-larga-vida-granel/p", "261275-KG"),  # Tomate Larga Vida Granel (kg)
    ("cebolla", "https://www.jumbo.cl/cebolla-3-unid/p", "260574"),  # Cebolla Malla 3 un. (un)
    ("papa", "https://www.jumbo.cl/papas-jumbo-malla-2-kg/p", "261044"),  # Papa Malla 2 kg (kg)
    ("zanahoria", "https://www.jumbo.cl/zanahoria-jumbo-granel/p", "1027562-KG"),  # Zanahoria Granel (kg)
    ("choclo", "https://www.jumbo.cl/choclo-bandeja-2-unidades-1616681/p", "1616681"),  # Choclo Bandeja 2 un. (un)
    ("carne molida de vacuno", "https://www.jumbo.cl/carne-molida-vacuno-10-500g-prodj-1995701/p", "1995701"),  # 10% grasa 500 g (kg)
    ("pollo", "https://www.jumbo.cl/pollo-entero-con-menudencias-don-pollo-granel/p", "260371-KG"),  # Pollo Entero Don Pollo (kg)
    ("merluza", "https://www.jumbo.cl/merluza-filete-con-piel-500g-cuisine-y-co/p", "1998278"),  # Merluza Filete 500 g (kg)
    ("atún", "https://www.jumbo.cl/atun-lom-ac-max-91-2067224/p", "2067224"),  # Atún Lomito en Agua Máxima (kg)
    ("huevo", "https://www.jumbo.cl/hue-exg-b-20u-c-y-co/p", "1991093"),  # Huevos Extra Grandes 20 un. (un)
    ("leche", "https://www.jumbo.cl/leche-entera-surlat-b-a-1l-1991554/p", "1991554"),  # Leche Surlat Entera 1 L (lt)
    ("mantequilla", "https://www.jumbo.cl/mantequilla-con-sal-soprole-250-g/p", "302978"),  # Soprole con Sal 250 g (kg)
    ("porotos", "https://www.jumbo.cl/porotos-tortola-1-kg/p", "1840317"),  # Porotos Tórtola 1 kg (kg)
    ("lentejas", "https://www.jumbo.cl/lentejas-6mm-maxima-1-kg/p", "1607542"),  # Lentejas 6 mm 1 kg (kg)
    ("arroz", "https://www.jumbo.cl/arroz-grado-2-maxima-1-kg-grano-largo-angosto/p", "1223046"),  # Arroz G2 1 kg (kg)
    ("fideos", "https://www.jumbo.cl/spaghetti-n-5-lucchetti-bolsa-400-g/p", "267569"),  # Spaghetti N°5 400 g (kg)
    ("aceite", "https://www.jumbo.cl/aceite-vegetal-libre-de-colesterol-900-ml-cuisine-and-co-1800913/p", "1800913"),  # 900 ml (lt)
    ("harina", "https://www.jumbo.cl/harina-maxima-sin-polvos-1-kg/p", "1624899"),  # Harina sin polvos 1 kg (kg)
    ("azúcar", "https://www.jumbo.cl/azucar-maxima-1-kg/p", "1124244"),  # Azúcar Máxima 1 kg (kg)
]

# Peso medio por unidad (g) de productos que el catálogo cuenta por unidad y
# las cadenas venden a granel por kg. Aproximaciones de verdulería.
PESO_UNIDAD_G: dict[str, float] = {
    "palta": 200.0,
    "tomate": 150.0,
    "cebolla": 180.0,
    "zanahoria": 120.0,
}
