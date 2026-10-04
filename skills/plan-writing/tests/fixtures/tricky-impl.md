# Разбор задач: коварный план

**Spec:** tricky-spec.md

**Tier:** Standard

**Goal:** Фикстура контракта: все потребители видят одни задачи и границы.

## A. Обзор

Раздел с буквой в заголовке до первой задачи.

## Phase 1: Основа

### Task 1: Парсер

**Files:**
- Create: `src/parser.py`
- Test: `tests/test_parser.py`

**Preconditions:**
- нет

**Postconditions:**
- `src/parser.py` разбирает заголовки.

- [ ] **Step 1: Написать тест**

```python
def test_parse():
    assert parse("## Task 8: внутри кода") == []
```

#### Step notes

Подзаголовок глубже задачи не закрывает её тело.

1. шаг списка
2. ещё шаг

### Task 1.1: Документация

**Files:**
- Modify: `docs/parser.md:1-5`

**Preconditions:**
- Task 1 выполнена.

**Postconditions:**
- Документ описывает парсер.

- [ ] **Step 1: Дописать раздел**

```markdown
### Task 9: заголовок в файле, не задача
```

### Notes

Подзаголовок уровня задачи закрывает тело Task 1.1.

## Phase 2: Проверка

### Задача 2: Интеграция

**Files:**
- Modify: `src/parser.py:10-20`
- Test: `tests/test_parser.py`

**Preconditions:**
- Task 1 и Задача 1.1 выполнены.

**Postconditions:**
- Интеграция проходит.

- [ ] **Step 1: Запустить тесты**

Run: `python -m pytest tests -q`
Expected: PASS

#### Task 3: Вложенная задача

**Files:**
- Test: `tests/test_nested.py`

**Preconditions:**
- Задача 2 выполнена.

**Postconditions:**
- Вложенная задача видна всем потребителям.

- [ ] **Step 1: Проверить вложенность**

Run: `python -m pytest tests/test_nested.py -q`
Expected: PASS

### Task 4: Checkpoint — всё вместе

- [ ] **Step 1: Прогнать набор**

Run: `python -m pytest tests -q`
Expected: PASS

**Done when:** набор зелёный.

## Итог

Раздел после последней задачи закрывает её тело.
