"""The Free backlog paragraph is the same in the seven pipeline SKILL.md files and in CLAUDE.md (spec 2 of
plan-refactoring-02). Run: python -m pytest skills/plan-writing/tests/test_shared_paragraphs.py -q
"""
import re
import unittest
from pathlib import Path


SKILLS = Path(__file__).resolve().parents[2]
CLAUDE_MD = SKILLS.parent / "CLAUDE.md"
PIPELINE = ("plan-brainstorming", "plan-writing", "plan-iterative-revision", "plan-splitter", "plan-executor",
            "plan-resolver", "plan-chain-runner")
FREE = "**Free backlog.**"
DIALOGUE = "**Dialogue language.**"


def paragraph(text, mark):
    """The paragraph of `text` that starts with `mark`, whitespace collapsed; None when there is none."""
    for block in re.split(r"\n\s*\n", text):
        if block.lstrip().startswith(mark):
            return " ".join(block.split())
    return None


class FreeBacklogParagraphTest(unittest.TestCase):
    def language(self, skill):
        text = (SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        return text.split("\n## Language\n", 1)[1].split("\n## ", 1)[0]

    def test_every_pipeline_skill_has_it_right_after_the_dialogue_language(self):
        for skill in PIPELINE:
            with self.subTest(skill=skill):
                section = self.language(skill)
                self.assertIsNotNone(paragraph(section, FREE))
                self.assertLess(section.index(DIALOGUE), section.index(FREE))

    def test_the_copies_are_identical_and_claude_md_quotes_them(self):
        copies = {skill: paragraph(self.language(skill), FREE) for skill in PIPELINE}
        self.assertEqual(len(set(copies.values())), 1, copies)
        claude = CLAUDE_MD.read_text(encoding="utf-8")
        self.assertEqual(paragraph(claude, FREE), copies["plan-writing"])
        self.assertIn("Three paragraphs are repeated word for word", claude)


if __name__ == "__main__":
    unittest.main()
