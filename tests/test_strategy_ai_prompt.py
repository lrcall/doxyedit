"""strategy.generate_ai_strategy — pin the prompt content that the
Claude CLI sees. Critical because the prompt carries the user's
STRICT WRITING RULES (no em dashes, no corporate buzzwords) that
must reach the model. A regression that drops them lets Claude
produce output the user has explicitly forbidden."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class TestGenerateAIStrategyPrompt(unittest.TestCase):
    def _run_and_capture_prompt(self, project, post):
        from doxyedit import strategy
        captured = {}

        def fake_cli(prompt, fallback):
            captured["prompt"] = prompt
            return "stub-output"

        with patch.object(strategy, "_generate_ai_strategy_cli",
                          side_effect=fake_cli):
            strategy.generate_ai_strategy(project, post)
        return captured["prompt"]

    def test_prompt_bans_em_dash(self):
        from doxyedit.models import Project, SocialPost
        prompt = self._run_and_capture_prompt(Project(), SocialPost())
        self.assertIn("ZERO em dashes", prompt)

    def test_prompt_bans_buzzwords(self):
        from doxyedit.models import Project, SocialPost
        prompt = self._run_and_capture_prompt(Project(), SocialPost())
        for word in ("leverage", "elevate", "showcase", "delve",
                     "craft", "resonate", "captivate"):
            self.assertIn(word, prompt)

    def test_prompt_includes_platforms(self):
        from doxyedit.models import Project, SocialPost
        post = SocialPost(platforms=["bluesky", "telegram"])
        prompt = self._run_and_capture_prompt(Project(), post)
        self.assertIn("bluesky", prompt)
        self.assertIn("telegram", prompt)

    def test_prompt_says_not_yet_selected_when_no_platforms(self):
        from doxyedit.models import Project, SocialPost
        prompt = self._run_and_capture_prompt(Project(), SocialPost())
        self.assertIn("not yet selected", prompt)

    def test_prompt_includes_creator_voice_and_notes(self):
        from doxyedit.models import Project, SocialPost
        proj = Project()
        proj.identity = {
            "name": "Doxy",
            "voice": "Cheeky and warm",
            "content_notes": "skip Mondays"}
        prompt = self._run_and_capture_prompt(proj, SocialPost())
        self.assertIn("Doxy", prompt)
        self.assertIn("Cheeky and warm", prompt)
        self.assertIn("skip Mondays", prompt)

    def test_recent_posts_block_present(self):
        from doxyedit.models import Project, SocialPost
        proj = Project()
        proj.posts = [SocialPost(id="prev",
                                  scheduled_time="2026-04-15T10:00",
                                  caption_default="Old caption text")]
        prompt = self._run_and_capture_prompt(proj, SocialPost(id="cur"))
        self.assertIn("Recent Posts", prompt)


if __name__ == "__main__":
    unittest.main()
