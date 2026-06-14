# Ревизия {{N}}: {{basename}}

**Iteration**: {{N}}
**Audited plan**: {{basename}}.md
**Plan SHA-256**: {{plan_sha256}}
**Plan size**: {{plan_size}} bytes
**Plan git blob**: {{plan_git_blob}}
**Audited at**: {{audited_at_utc}}
**Previous review**: {{previous_review_or_none}}
**Issues found**: {{total}} (blocker: {{n_blocker}}, major: {{n_major}}, minor: {{n_minor}}, nit: {{n_nit}})
**Flow**: +{{new}} / -{{resolved}} / {{persisted}} persisted / {{reintroduced}} reintro | Profile: ({{B}},{{M}},{{m}},{{n}})   <!-- опционально, observability -->

## Audit state

| Check | Status | Notes |
|---|---|---|
| Previous review contracts checked | {{previous_contracts_status}} | {{previous_contracts_notes}} |
| Taxonomy sweep completed | {{taxonomy_status}} | 10 classes |
| Code cross-check completed | {{code_cross_check_status}} | verified / not found / ambiguous / not applicable statuses used |
| Review validated | {{review_validated_status}} | `validate-review` before Phase B |
| Deferred conflicts carried | {{deferred_count}} | {{deferred_notes}} |
| Lenses used | {{lenses_used}} | опц.: число линз аудита |
| Cache hits | {{cache_hits}} | опц.: пропущено пересверок кода |

## Summary

{{summary_1_3_sentences}}

## Issues

### [{{N}}.1] {{SEVERITY}} · {{category}} · {{title}}

- **Location in plan**: {{plan_section}}
- **Location in code**: {{code_file_line_or_na}}
- **Code cross-check**: {{verified_or_not_found_or_ambiguous_or_not_applicable}} — {{code_check_note}}
- **Problem**:
  {{problem_description}}
- **Evidence**:
  > Цитата из плана:
  > {{plan_quote}}

  > Цитата из кода (если применимо):
  > ```{{lang}}
  > {{code_quote}}
  > ```
- **Required fix (contract)**:
  {{required_fix_unambiguous_contract}}
- **Acceptance**:
  {{acceptance_check}}
- **Fingerprint**: {{fingerprint8_from_script}}

<!-- Добавить блоки [{{N}}.2], [{{N}}.3], ... по той же схеме -->

## Deferred from previous review

<!-- Опционально. Список перенесённых issue с указанием прежнего id и новой severity. -->

## Notes for implementation

<!-- Опционально: общие подсказки для Фазы Б, порядок применения, риски. -->
