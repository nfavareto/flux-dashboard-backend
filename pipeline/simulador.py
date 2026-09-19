"""
Simulador de KPIs — permite cambiar variables y ver impacto en tiempo real.

Usa la MISMA lógica de cálculo que el pipeline, pero acepta overrides de valores.
"""

def simular_telefonia(ivr=None, cola=None, gest=None, tmo=None, override_values=None):
    """
    Simula impacto de cambios en telefonía.
    
    Args:
        ivr: total de llamadas IVR (default: valores reales)
        cola: llamadas en cola
        gest: llamadas gestionadas (answered)
        tmo: Talking Time Medio (segundos)
        override_values: dict con valores a cambiar
    
    Returns:
        dict con indicadores simulados + impacto financiero
    """
    
    # Valores por defecto (reales actuales — se pueden reemplazar)
    if override_values is None:
        override_values = {}
    
    ivr = override_values.get('ivr', ivr or 10000)
    cola = override_values.get('cola', cola or 9500)
    gest = override_values.get('gest', gest or 8500)
    tmo = override_values.get('tmo', tmo or 300)  # segundos
    
    # Cálculos (misma lógica que pipeline)
    aband = ivr - gest
    abd_pct = round(aband / ivr * 100, 1) if ivr else 0
    nsvc = round(gest / cola * 100, 1) if cola else 0
    
    # Impacto financiero (ejemplos — ajustar según real)
    costo_por_llamada = 45  # ARS
    ingreso_por_llamada = 120  # ARS (promedio)
    
    costo_total = gest * costo_por_llamada
    ingreso_total = gest * ingreso_por_llamada
    margen = ingreso_total - costo_total
    
    # Impacto de cambios
    costo_llamadas_perdidas = aband * costo_por_llamada * 0.5  # mitad del costo (menos gestión)
    ingreso_perdido = aband * ingreso_por_llamada
    
    return {
        "variables_simuladas": {
            "ivr": ivr,
            "cola": cola,
            "gest": gest,
            "aband": aband,
            "nsvc": nsvc,
            "abd_pct": abd_pct,
            "tmo": tmo
        },
        "impacto_financiero": {
            "costo_total_gest": int(costo_total),
            "ingreso_total_gest": int(ingreso_total),
            "margen_bruto": int(margen),
            "ingreso_perdido": int(ingreso_perdido),
            "costo_evitado": int(costo_llamadas_perdidas),
            "margen_neto_simulado": int(margen - ingreso_perdido + costo_llamadas_perdidas)
        },
        "indicadores_derivados": {
            "sla_impacto": round(nsvc * 0.95, 1),  # SLA es 95% de NS
            "retencion_esperada": round(gest * 0.12, 0),  # 12% retención típica
            "ventas_esperadas": round(gest * 0.08, 0),  # 8% ventas típicas
        }
    }


def simular_s1(resolucion=None, csat=None, nps=None, tiempo_resolucion=None, override_values=None):
    """
    Simula impacto de cambios en S1 Contact Center.
    """
    if override_values is None:
        override_values = {}
    
    resolucion = override_values.get('resolucion', resolucion or 85)
    csat = override_values.get('csat', csat or 4.2)
    nps = override_values.get('nps', nps or 45)
    tiempo_resolucion = override_values.get('tiempo_resolucion', tiempo_resolucion or 24)  # horas
    
    volumen_casos = 1200  # casos/mes típico
    costo_caso = 50  # ARS
    
    # Cálculos
    casos_resueltos = int(volumen_casos * (resolucion / 100))
    casos_reabiertos = volumen_casos - casos_resueltos
    
    costo_total = casos_resueltos * costo_caso
    costo_reaperturas = casos_reabiertos * costo_caso * 1.5
    
    # Impacto en retención (CSAT alto = más retención)
    impacto_retension = (csat / 5) * 100  # % esperado
    
    return {
        "variables_simuladas": {
            "resolucion": resolucion,
            "csat": round(csat, 1),
            "nps": nps,
            "tiempo_resolucion": tiempo_resolucion
        },
        "impacto_operativo": {
            "casos_resueltos": casos_resueltos,
            "casos_reabiertos": casos_reabiertos,
            "costo_total": int(costo_total),
            "costo_reaperturas": int(costo_reaperturas),
            "costo_total_incl_reaperturas": int(costo_total + costo_reaperturas)
        },
        "impacto_comercial": {
            "impacto_retension_pct": round(impacto_retension, 1),
            "clientes_retenidos_estimado": int(volumen_casos * (impacto_retension / 100)),
            "ingresos_por_retension": int(volumen_casos * (impacto_retension / 100) * 500)  # 500 ARS ingreso promedio
        }
    }


def simular_presentismo(cumplimiento=None, ausencias=None, override_values=None):
    """
    Simula impacto de cambios en presentismo.
    """
    if override_values is None:
        override_values = {}
    
    cumplimiento = override_values.get('cumplimiento', cumplimiento or 92)
    ausencias = override_values.get('ausencias', ausencias or 8)
    
    agentes_total = 150  # agentes típico
    costo_agente_dia = 800  # ARS
    dias_mes = 22
    
    agentes_presentes = int(agentes_total * (cumplimiento / 100))
    agentes_ausentes = agentes_total - agentes_presentes
    
    # Cálculos
    costo_planilla_diaria = agentes_total * costo_agente_dia
    costo_ausencias = agentes_ausentes * costo_agente_dia * dias_mes
    
    # Impacto en cobertura (menos agentes = menos capacidad de atender)
    capacidad_impacto = (cumplimiento / 100) * 100
    
    return {
        "variables_simuladas": {
            "cumplimiento": cumplimiento,
            "ausencias": ausencias,
            "agentes_presentes": agentes_presentes,
            "agentes_ausentes": agentes_ausentes
        },
        "impacto_operativo": {
            "costo_planilla_mes": int(costo_planilla_diaria * dias_mes),
            "costo_ausencias_mes": int(costo_ausencias),
            "costo_total_mes": int((costo_planilla_diaria * dias_mes) + costo_ausencias),
            "capacidad_operativa_pct": round(capacidad_impacto, 1)
        },
        "riesgos": {
            "riesgo_sobrecarga": "ALTO" if cumplimiento < 85 else "MEDIO" if cumplimiento < 90 else "BAJO",
            "agentes_faltantes": agentes_ausentes
        }
    }


def simular_completo(telefonia_override=None, s1_override=None, presentismo_override=None):
    """
    Simulación COMPLETA: cambios en teléfonica + S1 + presentismo = impacto global.
    """
    
    sim_tel = simular_telefonia(override_values=telefonia_override or {})
    sim_s1 = simular_s1(override_values=s1_override or {})
    sim_pres = simular_presentismo(override_values=presentismo_override or {})
    
    # Síntesis de impacto
    impacto_global_ingresos = (
        sim_tel["impacto_financiero"]["ingreso_total_gest"] +
        sim_s1["impacto_comercial"]["ingresos_por_retension"]
    )
    
    impacto_global_costos = (
        sim_tel["impacto_financiero"]["costo_total_gest"] +
        sim_s1["impacto_operativo"]["costo_total_incl_reaperturas"] +
        sim_pres["impacto_operativo"]["costo_total_mes"]
    )
    
    margen_global = impacto_global_ingresos - impacto_global_costos
    
    return {
        "telefonica": sim_tel,
        "s1": sim_s1,
        "presentismo": sim_pres,
        "impacto_consolidado": {
            "ingresos_simulados": int(impacto_global_ingresos),
            "costos_simulados": int(impacto_global_costos),
            "margen_simulado": int(margen_global),
            "cambio_vs_actual": "TBD (comparar con datos reales)"
        }
    }
