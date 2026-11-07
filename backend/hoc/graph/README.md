# Future: corporate dependency graph (not part of the PoC)

House of Cards will later trace what each company depends on (parents, subsidiaries, suppliers,
nested funds). It plugs in **after identity resolution**, keyed by `company_key`, so the ETF
ingestion pipeline (`sources/` -> `normalise/` -> `identity/`) never changes:

```python
class RelationshipSource(Protocol):
    def edges(self, company_keys: Sequence[str]) -> list[CompanyEdge]: ...

CompanyEdge(src_key, dst_key, kind, source, as_of)  # kind: parent | subsidiary | supplier | holds
```

Candidate sources: GLEIF level-2 relationships (by LEI), SEC Exhibit 21 subsidiaries (by CIK), and
"holds" edges for ETFs that own other funds. Exposed later as `GET /api/graph`.
