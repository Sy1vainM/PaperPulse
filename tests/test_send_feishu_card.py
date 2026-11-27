import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import subprocess

from scripts import send_feishu_card as card
from scripts.check_public_release import _scan_text


class CardTests(unittest.TestCase):
    def setUp(self):
        self.legacy = "# Digest\n> Collected: 123 candidates\n" + "".join(
            f"\n## [Paper {i}](https://example.org/{i})\n**Category**: 方向{i}\n### 一句话总结\n有证据的短句。其余细节。\n"
            for i in range(1, 7))

    def test_legacy_hierarchy_and_margins(self):
        c = card.build_card(self.legacy, "2026-11-26")
        self.assertEqual(c["schema"], "2.0")
        self.assertTrue(c["config"]["enable_forward"])
        self.assertEqual(c["header"]["icon"]["token"], "myai_colorful")
        blocks = c["body"]["elements"]
        self.assertEqual([b["tag"] for b in blocks], ["column_set","interactive_container","collapsible_panel","markdown"])
        self.assertEqual([b["margin"] for b in blocks], [card.GAP]*3+["0px"])
        self.assertEqual(blocks[0]["flex_mode"], "none")
        cols = blocks[0]["columns"]
        self.assertEqual([v["weight"] for v in cols],[1,1,1])
        for column in cols:
            self.assertNotIn("corner_radius", column)
        self.assertTrue(all(v["elements"][0]["text_align"]=="center" for v in cols))
        self.assertIn("覆盖方向",cols[1]["elements"][1]["content"])
        self.assertIn("123",cols[2]["elements"][0]["content"])
        self.assertEqual(len(blocks[1]["elements"]),6)
        self.assertNotIn("今日核心判断", str(c))
        self.assertNotIn("behaviors",blocks[1])
        self.assertEqual(blocks[2]["elements"], [card.md("[Paper 6](https://example.org/6)")])
        self.assertFalse(blocks[2]["expanded"])
        self.assertNotIn("icon",blocks[2]["header"])
        self.assertEqual(blocks[-1]["text_size"],"notation")
        self.assertNotIn("微信",str(c))
        self.assertNotIn("其余细节",str(c))
        self.assertIn("[Paper 1](https://example.org/1)",str(c))

    def test_grouped_papers_news_and_bounds(self):
        source = ("## 今日 3 条判断\n1. **第一条。**\n2. 第二条。\n3. " + "长"*100 +
                  "\n## 核心精读\n### [A](https://example.org/a)\n#### 核心突破与做法\n" + "文"*110 +
                  "\n## 精选速览\n### 无链接论文\n摘要在此。\n## 行业与开源速递（微信信源）\n"
                  "- 工具发布：[发现](https://mp.weixin.qq.com/s/a)，[官方](https://example.org/releases)\n")
        p,j,n,d,_ = card.digest_data(source)
        self.assertEqual((len(p),len(j),len(n),d),(2,3,1,1))
        self.assertEqual(n[0][1],"https://example.org/releases")
        self.assertTrue(all(len(v)<=60 for v in j))
        self.assertTrue(all(len(v["summary"])<=80 for v in p))
        c=card.build_card(source,"2026-11-27")
        self.assertIn("**无链接论文**",str(c))
        self.assertEqual(len(c["header"]["text_tag_list"]),2)
        self.assertIn("核心精读",str(c))
        self.assertEqual(len(card.build_card("## 行业与开源速递（微信信源）\n0 条经核验。","2026-11-27")["header"]["text_tag_list"]), 1)

    def test_only_explicit_judgments_change_the_recommendation_count(self):
        src = self.legacy.replace("### 一句话总结","**Read Depth**: 全文精读\n### 核心突破与做法") + "\n## 今日决策\n1. **先看证据。** 再看表现。"
        _, decisions, _, deep, _ = card.digest_data(src)
        self.assertEqual(deep, 6)
        self.assertEqual(decisions, ["先看证据。"])
        explicit = src + "\n## 今日 3 条判断\n1. 独立判断甲。\n2. 独立判断乙。\n3. 独立判断丙。"
        blocks = card.build_card(explicit, "2026-11-27")["body"]["elements"]
        self.assertEqual(len(blocks), 5)
        self.assertEqual(blocks[1]["background_style"], "blue-50")
        self.assertEqual(blocks[1]["elements"][1:], [card.md(f"{i}. 独立判断{v}。") for i, v in enumerate("甲乙丙", 1)])
        self.assertEqual(len(blocks[2]["elements"][1:]), 3)
        self.assertTrue(all("\n**核心**：" in item["content"] for item in blocks[2]["elements"][1:]))
        self.assertEqual(len(blocks[3]["elements"]), 3)
        self.assertIn("Paper 4", blocks[3]["elements"][0]["content"])

    def test_micro_summary_uses_distinct_fields_and_bounded_fallback(self):
        lines = ["### 核心突破与做法", "估计手部受力。结合肌电与视频。", "### 关键证据与适用边界",
                 "| 条件 | 旧方法 | 新方法 | 边界 |", "|---|---|---|---|", "| 同人 | 5 mm | 3 mm | 跨人待测 |"]
        core, method, evidence = card.micro_summary(lines)
        self.assertEqual((core, method), ("估计手部受力。", "结合肌电与视频。"))
        self.assertIn("同人", evidence)
        self.assertIn("新方法 3 mm", evidence)
        self.assertIn("跨人待测", evidence)
        self.assertEqual(card.micro_summary(["**Authors**: Example", "先定位。再跟踪。最后核验。第四句。"]),
                         ("先定位。再跟踪。最后核验。", "", ""))
        self.assertLessEqual(len(card.micro_summary(["句" * 180])[0]), 160)

    @patch("scripts.send_feishu_card.subprocess.run")
    def test_delivery_requires_both_signals(self,run):
        cfg=dict(enabled=True,lark_cli_bin="fake")
        for status,value,good in [(0,True,True),(0,False,False),(1,True,False),(0,1,False)]:
            run.return_value=subprocess.CompletedProcess([],status,json.dumps({"ok":value}),"")
            if good:
                card.deliver({},cfg,"user","--chat-id","fixture","stable-key")
            else:
                with self.assertRaises(ValueError): card.deliver({},cfg,"user","--chat-id","fixture","stable-key")
        self.assertEqual(run.call_args.args[0],["fake","im","+messages-send","--as","user","--chat-id","fixture","--msg-type","interactive","--content","{}","--idempotency-key","stable-key"])

    def test_dry_run_and_privacy(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"2026-11-26.md";p.write_text(self.legacy)
            out=Path(tmp)/"preview.json"
            with patch.object(card,"deliver") as send, patch("builtins.print"):
                card.main(["--digest",str(p),"--dry-run","--output-json",str(out)])
                send.assert_not_called()
            self.assertEqual(json.loads(out.read_text())["schema"],"2.0")
        for prefix,n in [("ou_",16),("oc_",16),("cli_",12)]:
            self.assertTrue(_scan_text("fixture",prefix+"a"*n))
            self.assertFalse(_scan_text("fixture",prefix+"a"*(n-1)))
