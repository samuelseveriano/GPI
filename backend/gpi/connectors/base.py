"""Contrato comum dos conectores."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .http import SourceError


class FormatError(SourceError):
    def __init__(self, msg):
        super().__init__(msg, "formato")


@dataclass
class Job:
    key: str                      # identificador idempotente (mesmo job → mesma chave)
    params: dict
    refresh_days: int | None = 7  # None = período fechado: não precisa ser coletado de novo
    priority: int = 5             # menor = antes


@dataclass
class Batch:
    series_key: str
    meta: dict
    obs: list = field(default_factory=list)   # [(ref_date 'YYYY-MM-DD', valor)]


@dataclass
class Product:
    key: str
    fields: dict


class Connector:
    id: str = ""
    name: str = ""
    # v0.7.1: "Atualizar fonte" pode repetir o job do período corrente (1 requisição barata, dentro dos limites da API)
    manual_refresh: bool = False
    reliability: str = "A"
    docs_url: str = ""
    description: str = ""
    limitations: str = ""
    restricted_reason: str | None = None     # preenchido se a fonte exige credencial/autorização
    order: int = 50

    def available(self, ctx) -> bool:
        return self.restricted_reason is None

    def plan(self, ctx) -> list[Job]:
        return []

    def run(self, job: Job, ctx) -> tuple[list[Batch], list[Product]]:
        raise NotImplementedError

    def info(self) -> dict:
        return {"id": self.id, "nome": self.name, "confiabilidade": self.reliability,
                "documentacao": self.docs_url, "descricao": self.description,
                "limitacoes": self.limitations, "restricao": self.restricted_reason}


def year_jobs(prefix: str, start: int, today: date, params: dict, revise_years: int = 2) -> list[Job]:
    """Um job por ano. Anos antigos são fechados (sem nova coleta); os últimos
    `revise_years` anos são revisitados semanalmente para captar dados novos e revisões."""
    out = []
    for y in range(start, today.year + 1):
        recent = y > today.year - revise_years
        out.append(Job(f"{prefix}:{y}", {**params, "year": y}, 7 if recent else None,
                       priority=1 if recent else 3))
    return out


def month_end(d: date) -> date:
    from calendar import monthrange
    return date(d.year, d.month, monthrange(d.year, d.month)[1])


def require(cond, msg):
    if not cond:
        raise FormatError(msg)
