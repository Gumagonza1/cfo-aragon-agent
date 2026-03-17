"""
models.py – Tablas SQLite para el CFO Agent.
"""

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from db.database import Base


class Ingreso(Base):
    __tablename__ = "ingresos"

    id         = Column(Integer, primary_key=True, index=True)
    fecha      = Column(String(10), nullable=False)   # YYYY-MM-DD
    concepto   = Column(String(200), nullable=False)  # "Ventas taquería"
    tipo       = Column(String(50), nullable=False)   # "ventas", "otros"
    monto      = Column(Float, nullable=False)
    notas      = Column(Text, default="")
    creado_en  = Column(DateTime, server_default=func.now())


class Gasto(Base):
    __tablename__ = "gastos"

    id         = Column(Integer, primary_key=True, index=True)
    fecha      = Column(String(10), nullable=False)
    concepto   = Column(String(200), nullable=False)
    tipo       = Column(String(50), nullable=False)   # "operativo", "nomina", "materia_prima", "servicios", "otros"
    monto      = Column(Float, nullable=False)
    deducible  = Column(Integer, default=0)           # 0/1
    notas      = Column(Text, default="")
    creado_en  = Column(DateTime, server_default=func.now())


class InventarioItem(Base):
    __tablename__ = "inventario"

    id             = Column(Integer, primary_key=True, index=True)
    nombre         = Column(String(200), nullable=False, unique=True)
    categoria      = Column(String(50), default="insumo")  # "insumo", "producto", "herramienta"
    unidad         = Column(String(20), default="pza")      # "kg", "pza", "litro"
    cantidad       = Column(Float, default=0)
    costo_unitario = Column(Float, default=0)
    minimo         = Column(Float, default=0)               # alerta si baja de aquí
    actualizado    = Column(DateTime, server_default=func.now(), onupdate=func.now())


class AnalisisFiscal(Base):
    __tablename__ = "analisis_fiscal"

    id          = Column(Integer, primary_key=True, index=True)
    mes         = Column(String(7), nullable=False)   # "2026-03"
    tipo        = Column(String(20), default="recibidos")  # "recibidos", "emitidos", "ambos"
    resultado   = Column(Text)                         # JSON con análisis de Claude
    creado_en   = Column(DateTime, server_default=func.now())


class DeclaracionMensual(Base):
    __tablename__ = "declaracion_mensual"
    __table_args__ = (UniqueConstraint("mes", name="uq_declaracion_mes"),)

    id                      = Column(Integer, primary_key=True, index=True)
    mes                     = Column(String(7), nullable=False, index=True)   # "2026-03"
    anio                    = Column(Integer, nullable=False)                 # 2026

    # Ingresos
    ingresos_plataformas    = Column(Float, default=0.0)   # Didi, Uber, Rappi
    ingresos_propios        = Column(Float, default=0.0)   # ventas mostrador/directas

    # Deducciones
    gastos_deducibles       = Column(Float, default=0.0)   # materia prima, renta, servicios
    nomina                  = Column(Float, default=0.0)   # sueldos + IMSS

    # Retenciones de plataformas (ya enteradas por las apps)
    isr_retenido            = Column(Float, default=0.0)   # 2.1% sobre ingresos plataformas
    iva_retenido            = Column(Float, default=0.0)   # 50% × 16% = 8% sobre plataformas

    # ISR provisional calculado
    base_gravable_isr       = Column(Float, default=0.0)   # ingresos_acum − deducciones_acum
    isr_tarifa              = Column(Float, default=0.0)   # ISR según tarifa Art. 96
    isr_provisionales_previos = Column(Float, default=0.0) # pagos provisionales anteriores YTD
    isr_a_pagar             = Column(Float, default=0.0)   # isr_tarifa − isr_retenido − previos

    # IVA mensual
    iva_trasladado          = Column(Float, default=0.0)   # 16% sobre ventas propias
    iva_acreditable         = Column(Float, default=0.0)   # IVA pagado a proveedores
    iva_a_pagar             = Column(Float, default=0.0)   # iva_trasladado − iva_acreditable − iva_retenido

    # Estado ISR
    estado_isr              = Column(String(20), default="pendiente")  # pendiente/pagado/a_favor
    fecha_pago_isr          = Column(String(10), nullable=True)        # "2026-03-17"
    num_operacion_isr       = Column(String(50), nullable=True)

    # Estado IVA
    estado_iva              = Column(String(20), default="pendiente")
    fecha_pago_iva          = Column(String(10), nullable=True)
    num_operacion_iva       = Column(String(50), nullable=True)

    notas                   = Column(Text, default="")
    creado_en               = Column(DateTime, server_default=func.now())
    actualizado_en          = Column(DateTime, server_default=func.now(), onupdate=func.now())
